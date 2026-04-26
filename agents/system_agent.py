"""
agents/system_agent.py — Agente de interação com o Sistema Operacional.

Responsabilidades:
    • Abrir aplicações (VS Code, navegador, explorador, etc.)
    • Gerenciar arquivos e pastas (criar, listar, verificar)
    • Recuperar métricas do sistema (CPU, RAM, disco, processos)

Segurança:
    • Comandos shell são proibidos — todas as operações usam APIs Python
      (os, pathlib, subprocess com lista de argumentos, psutil).
    • Caminhos são validados para não escapar de raízes permitidas.
    • Nenhuma entrada do usuário é passada diretamente ao shell.
    • Executáveis permitidos constam numa allowlist explícita.
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from agents.base_agent import BaseAgent
from core.monitor_service import monitor_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlists de segurança
# ---------------------------------------------------------------------------

# Mapeamento canônico: nome amigável → executável por plataforma
_APP_MAP: Dict[str, Dict[str, str]] = {
    "vscode":     {"Windows": "code",       "Darwin": "code",       "Linux": "code"},
    "notepad":    {"Windows": "notepad.exe","Darwin": "TextEdit",   "Linux": "gedit"},
    "explorer":   {"Windows": "explorer",   "Darwin": "open",       "Linux": "xdg-open"},
    "chrome":     {"Windows": "chrome",     "Darwin": "Google Chrome","Linux": "google-chrome"},
    "firefox":    {"Windows": "firefox",    "Darwin": "Firefox",    "Linux": "firefox"},
    "terminal":   {"Windows": "wt",         "Darwin": "Terminal",   "Linux": "x-terminal-emulator"},
    "calculator": {"Windows": "calc",       "Darwin": "Calculator", "Linux": "gnome-calculator"},
}

# Pastas de usuário que o agente pode listar/criar dentro
_ALLOWED_ROOTS: List[Path] = [
    Path.home(),
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Projects",
]

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

_PLATFORM = platform.system()  # "Windows" | "Darwin" | "Linux"


def _safe_resolve(raw_path: str) -> Path:
    """
    Resolve o caminho e garante que ele esteja dentro de uma raiz permitida.

    Raises:
        PermissionError: se o caminho estiver fora das raízes permitidas.
    """
    # Expande ~, variáveis de ambiente e resolve symlinks
    resolved = Path(os.path.expandvars(raw_path)).expanduser().resolve()

    for root in _ALLOWED_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue

    raise PermissionError(
        f"Acesso negado: o caminho '{resolved}' está fora das pastas permitidas. "
        f"Raízes permitidas: {[str(r) for r in _ALLOWED_ROOTS]}"
    )


def _open_app(app_key: str) -> str:
    """Abre um aplicativo da allowlist usando subprocess sem shell."""
    entry = _APP_MAP.get(app_key.lower())
    if not entry:
        available = ", ".join(_APP_MAP.keys())
        return f"Aplicativo '{app_key}' não está na lista de aplicativos permitidos. Disponíveis: {available}."

    executable = entry.get(_PLATFORM)
    if not executable:
        return f"Plataforma '{_PLATFORM}' não suportada para '{app_key}'."

    try:
        if _PLATFORM == "Windows":
            subprocess.Popen(  # noqa: S603 — lista explícita, sem shell
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        elif _PLATFORM == "Darwin":
            subprocess.Popen(  # noqa: S603
                ["open", "-a", executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(  # noqa: S603
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return f"Certo, estou abrindo **{app_key.title()}** para você."
    except FileNotFoundError:
        return (
            f"Não consegui encontrar o executável de '{app_key}'. "
            "Verifique se o aplicativo está instalado e no PATH do sistema."
        )
    except OSError as exc:
        logger.error("Erro ao abrir '%s': %s", app_key, exc)
        return f"Erro ao tentar abrir '{app_key}': {exc}"


def _create_folder(raw_path: str) -> str:
    """Cria uma pasta dentro das raízes permitidas."""
    try:
        target = _safe_resolve(raw_path)
    except PermissionError as exc:
        return str(exc)

    if target.exists():
        return f"A pasta **'{target}'** já existe."

    try:
        target.mkdir(parents=True, exist_ok=True)
        return f"Pasta **'{target.name}'** criada com sucesso em `{target.parent}`."
    except OSError as exc:
        logger.error("Erro ao criar pasta '%s': %s", raw_path, exc)
        return f"Não consegui criar a pasta: {exc}"


def _list_folder(raw_path: str) -> str:
    """Lista o conteúdo de uma pasta dentro das raízes permitidas."""
    try:
        target = _safe_resolve(raw_path)
    except PermissionError as exc:
        return str(exc)

    if not target.exists():
        return f"A pasta **'{target}'** não foi encontrada."
    if not target.is_dir():
        return f"**'{target}'** não é uma pasta."

    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            return f"A pasta **'{target.name}'** está vazia."

        lines: List[str] = [f"📂 Conteúdo de `{target}` ({len(entries)} itens):\n"]
        for entry in entries[:50]:   # limite de segurança
            icon = "📄" if entry.is_file() else "📁"
            size = ""
            if entry.is_file():
                try:
                    sz = entry.stat().st_size
                    size = f"  ({_fmt_size(sz)})"
                except OSError:
                    pass
            lines.append(f"  {icon} {entry.name}{size}")

        if len(entries) > 50:
            lines.append(f"\n  … e mais {len(entries) - 50} itens.")

        return "\n".join(lines)
    except PermissionError:
        return f"Sem permissão para listar a pasta '{target}'."


def _fmt_size(n: int) -> str:
    """Formata tamanho em bytes de forma legível."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def _monitor_status() -> str:
    """Retorna o log de alertas recentes do MonitorService como texto formatado."""
    return monitor_service.format_log_summary(limit=15)


def _export_knowledge() -> str:
    """
    Consolida o código-fonte do projeto em Alfred_Knowledge_Base.md
    e abre o NotebookLM no navegador para upload imediato.
    """
    import webbrowser

    from core.knowledge_exporter import KnowledgeExporter

    try:
        exporter = KnowledgeExporter()
        output_path = exporter.export()
        webbrowser.open("https://notebooklm.google.com/")
        return (
            f"Senhor, consolidei todo o conhecimento técnico do projeto. "
            f"O arquivo **{output_path.name}** foi gerado em `{output_path.parent}`. "
            f"O navegador está pronto para o upload no NotebookLM."
        )
    except Exception as exc:
        logger.error("Erro ao exportar base de conhecimento: %s", exc)
        return f"Não consegui gerar a base de conhecimento: {exc}"


def _take_screenshot() -> str:
    """Captura a tela e retorna base64 PNG. Usado pelo VisionAgent via SystemAgent."""
    try:
        import io
        import base64
        import pyautogui  # type: ignore[import]

        screenshot = pyautogui.screenshot()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.error("Erro ao capturar screenshot: %s", exc)
        return f"Erro ao capturar screenshot: {exc}"


def _system_info() -> str:
    """Retorna um relatório compacto das métricas do sistema."""
    try:
        cpu_pct    = psutil.cpu_percent(interval=0.5)
        cpu_count  = psutil.cpu_count(logical=False)
        cpu_logic  = psutil.cpu_count(logical=True)

        vm         = psutil.virtual_memory()
        ram_total  = _fmt_size(vm.total)
        ram_used   = _fmt_size(vm.used)
        ram_pct    = vm.percent

        disk       = psutil.disk_usage(str(Path.home()))
        disk_total = _fmt_size(disk.total)
        disk_used  = _fmt_size(disk.used)
        disk_pct   = disk.percent

        uname      = platform.uname()
        os_str     = f"{uname.system} {uname.release}"

        return (
            f"**Informações do Sistema**\n\n"
            f"🖥️  **SO**: {os_str}\n"
            f"⚙️  **CPU**: {cpu_pct:.1f}% utilização  "
            f"({cpu_count} físicos / {cpu_logic} lógicos)\n"
            f"🧠 **RAM**: {ram_used} / {ram_total} ({ram_pct:.1f}% usada)\n"
            f"💾 **Disco** (home): {disk_used} / {disk_total} ({disk_pct:.1f}% usado)"
        )
    except Exception as exc:  # pragma: no cover
        logger.error("Erro ao obter métricas do sistema: %s", exc)
        return f"Não consegui obter as métricas do sistema: {exc}"


# ---------------------------------------------------------------------------
# SystemAgent
# ---------------------------------------------------------------------------

# Mapa de intenção → handler (usado pelo próprio agente após dispatch)
_ACTION_HANDLERS = {
    "open_app":         _open_app,
    "create_folder":    _create_folder,
    "list_folder":      _list_folder,
    "system_info":      _system_info,
    "screenshot":       _take_screenshot,
    "monitor_status":   _monitor_status,
    "export_knowledge": _export_knowledge,
}


class SystemAgent(BaseAgent):
    """
    Agente de interação segura com o Sistema Operacional.

    Recebe do orquestrador um dict `parsed_intent` em metadata com:
        {
            "action":  "open_app" | "create_folder" | "list_folder" | "system_info",
            "payload": <str>  — argumento da ação (nome do app, caminho, etc.)
        }

    Quando `parsed_intent` não está disponível, executa uma extração
    básica diretamente da mensagem (fallback).
    """

    def __init__(self) -> None:
        super().__init__(name="SystemAgent")

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
    ) -> str:
        intent = self._extract_intent(message)
        action  = intent.get("action", "")
        payload = intent.get("payload", "")

        logger.info(
            "SystemAgent | session=%s | action=%s | payload=%.60s",
            session_id, action, payload,
        )

        handler = _ACTION_HANDLERS.get(action)
        if not handler:
            return (
                "Não reconheci qual ação de sistema executar. "
                "Posso **abrir aplicativos**, **criar pastas**, **listar arquivos** "
                "ou **mostrar métricas do sistema**. Como posso ajudar?"
            )

        if action in ("system_info", "monitor_status", "export_knowledge"):
            return handler()          # type: ignore[call-arg]
        return handler(payload)       # type: ignore[call-arg]

    # ------------------------------------------------------------------
    # Extração de intenção
    # ------------------------------------------------------------------

    def _extract_intent(self, message: str) -> Dict[str, str]:
        """
        Extrai ação + payload da mensagem de forma determinística.
        Esta lógica é usada apenas quando o orquestrador não pré-classificou.

        Retorna dict {"action": str, "payload": str}.
        """
        msg = message.lower().strip()

        # ── Abrir aplicativo ─────────────────────────────────────
        OPEN_TRIGGERS = ("abr", "open", "inicia", "start", "lança", "launch")
        if any(t in msg for t in OPEN_TRIGGERS):
            for key in _APP_MAP:
                aliases = {key, key.replace("vscode", "vs code").replace("vscode", "visual studio code")}
                if any(alias in msg for alias in aliases):
                    return {"action": "open_app", "payload": key}
            # Tenta extrair depois de "abrir"/"open"
            for trigger in OPEN_TRIGGERS:
                idx = msg.find(trigger)
                if idx != -1:
                    rest = message[idx + len(trigger):].strip(" .,!?")
                    if rest:
                        return {"action": "open_app", "payload": rest.split()[0].lower()}

        # ── Informações do sistema ───────────────────────────────
        SYS_TRIGGERS = ("uso de cpu", "uso da cpu", "cpu usage", "uso de memória",
                        "uso da memória", "uso de ram", "ram usage", "quanto de memória",
                        "status do sistema", "system info", "informações do sistema",
                        "performance", "uso do processador", "espaço em disco")
        if any(t in msg for t in SYS_TRIGGERS):
            return {"action": "system_info", "payload": ""}

        # ── Status do monitoramento / alertas ────────────────────
        MONITOR_TRIGGERS = (
            "o que está rodando", "o que esta rodando", "what's running",
            "what is running", "log de monitoramento", "monitor de sistema",
            "últimos alertas", "ultimos alertas", "alertas recentes",
            "histórico de alertas", "historico de alertas", "status do monitor",
            "o que aconteceu", "o que alfred viu", "o que está acontecendo",
            "processos ativos", "o que alfred monitorou",
        )
        if any(t in msg for t in MONITOR_TRIGGERS):
            return {"action": "monitor_status", "payload": ""}

        # ── Listar arquivos / pasta ──────────────────────────────
        LIST_TRIGGERS = ("lista", "list", "mostre", "show", "ver", "quais arquivos",
                         "conteúdo", "conteudo", "o que tem")
        if any(t in msg for t in LIST_TRIGGERS):
            path = self._extract_path(message) or str(Path.home())
            return {"action": "list_folder", "payload": path}

        # ── Criar pasta ──────────────────────────────────────────
        CREATE_TRIGGERS = ("cri", "create", "nova pasta", "new folder", "mkdir",
                           "crie uma pasta", "crie a pasta", "criar pasta")
        if any(t in msg for t in CREATE_TRIGGERS):
            path = self._extract_path(message) or self._extract_quoted_name(message)
            if path:
                # Se não for caminho absoluto, cria na home
                target = Path(path)
                if not target.is_absolute():
                    target = Path.home() / path
                return {"action": "create_folder", "payload": str(target)}

        return {"action": "", "payload": ""}

    @staticmethod
    def _extract_path(text: str) -> str:
        """Extrai o primeiro token que parece um caminho do sistema."""
        import re
        # Caminho Windows ou UNIX
        patterns = [
            r'[A-Za-z]:\\[^\s]+',           # C:\foo\bar
            r'~/[^\s]*',                     # ~/Documents
            r'/[^\s]+',                      # /home/user
            r'[A-Za-z]:/[^\s]+',             # C:/foo
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0).rstrip('.,!?"\' ')
        return ""

    @staticmethod
    def _extract_quoted_name(text: str) -> str:
        """Extrai texto entre aspas ou após palavras-chave de nome."""
        import re
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
        # Tenta pegar "chamada X" / "chamado X" / "named X"
        m2 = re.search(r'(?:chamad[ao]|named?)\s+([^\s.,!?]+)', text, re.IGNORECASE)
        if m2:
            return m2.group(1)
        return ""
