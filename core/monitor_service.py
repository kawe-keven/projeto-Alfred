"""
core/monitor_service.py — Serviço de monitoramento proativo em segundo plano.

Responsabilidades:
    • Monitorar uso de CPU, RAM e bateria via psutil.
    • Vigiar a pasta Downloads para novos arquivos importantes.
    • Transmitir alertas em tempo real para todos os clientes WebSocket conectados.
    • Manter um log circular das últimas 100 ocorrências (consultável pelo SystemAgent).

Cooldown:
    Cada categoria de alerta tem cooldown independente de 60 s para evitar
    inundação de notificações repetidas.

Uso:
    # No lifespan do FastAPI:
    await monitor_service.start()
    yield
    await monitor_service.stop()

    # No endpoint /ws/notifications:
    monitor_service.connect(ws)
    # … aguarda desconexão …
    monitor_service.disconnect(ws)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

import psutil
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurações de limiar
# ---------------------------------------------------------------------------

CPU_THRESHOLD  = 90.0   # % — alerta crítico de CPU
RAM_THRESHOLD  = 90.0   # % — alerta crítico de RAM
BATTERY_LOW    = 20.0   # % — bateria fraca (somente quando desconectado)
CHECK_INTERVAL = 10     # segundos entre cada verificação
ALERT_COOLDOWN = 60     # segundos de cooldown por categoria (anti-spam)

# Extensões de arquivos consideradas "importantes" no watcher de Downloads
IMPORTANT_EXTS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".exe", ".msi", ".dmg", ".pkg",
    ".py", ".js", ".ts", ".java", ".cs",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp4", ".avi", ".mkv", ".mov",
    ".iso", ".img",
})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# MonitorService
# ---------------------------------------------------------------------------

class MonitorService:
    """
    Serviço singleton de monitoramento proativo.

    Gerencia um loop asyncio em background que verifica recursos do sistema
    e observa mudanças na pasta Downloads. Alertas são enviados a todos os
    clientes WebSocket conectados e persistidos num log interno.
    """

    def __init__(self) -> None:
        self._clients:     Set[WebSocket]       = set()
        self._logs:        List[Dict[str, Any]] = []   # buffer circular ≤ 100
        self._running:     bool                 = False
        self._task:        asyncio.Task | None  = None
        self._downloads:   Path                 = Path.home() / "Downloads"
        self._known_files: Set[str]             = set()

    # ------------------------------------------------------------------
    # Gestão de conexões WebSocket
    # ------------------------------------------------------------------

    def connect(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        logger.debug("Monitor WS conectado. Total: %d", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug("Monitor WS desconectado. Total: %d", len(self._clients))

    # ------------------------------------------------------------------
    # Log de alertas — consultado pelo SystemAgent
    # ------------------------------------------------------------------

    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retorna os alertas mais recentes em ordem cronológica."""
        return self._logs[-limit:]

    def format_log_summary(self, limit: int = 15) -> str:
        """
        Formata o log de alertas como texto Markdown legível para o LLM.
        Retornado pelo SystemAgent quando o usuário pergunta sobre o monitor.
        """
        logs = self.get_recent_logs(limit)
        if not logs:
            return (
                "✅ Nenhum alerta de monitoramento registrado ainda. "
                "O sistema está operacional e sob observação."
            )

        level_icon = {"error": "🔴", "warning": "🟡", "info": "🔵", "success": "🟢"}
        lines = ["**Log de Monitoramento — Alertas Recentes**\n"]
        for entry in reversed(logs):
            ts    = entry.get("timestamp", "")[:19].replace("T", " ")
            cat   = entry.get("category", "—").upper()
            title = entry.get("title", "Alerta")
            msg   = entry.get("message", "")
            icon  = level_icon.get(entry.get("type", ""), "⚪")
            lines.append(f"{icon} `{ts}` [{cat}] **{title}**: {msg}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Inicia o loop de monitoramento em background."""
        if self._running:
            return
        self._running = True

        # Snapshot inicial dos arquivos em Downloads (evita falsos positivos)
        if self._downloads.exists():
            try:
                self._known_files = {
                    f.name for f in self._downloads.iterdir() if f.is_file()
                }
                logger.info(
                    "MonitorService: %d arquivos em Downloads indexados.",
                    len(self._known_files),
                )
            except PermissionError:
                logger.warning("MonitorService: sem permissão para ler Downloads.")

        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("MonitorService iniciado (intervalo=%ds, cooldown=%ds).", CHECK_INTERVAL, ALERT_COOLDOWN)

    async def stop(self) -> None:
        """Para o loop de monitoramento e aguarda sua conclusão."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MonitorService encerrado.")

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, alert: Dict[str, Any]) -> None:
        """
        Persiste o alerta no log circular e o envia para todos os clientes WS.
        Conexões mortas são descartadas silenciosamente.
        """
        # Persiste no log interno
        self._logs.append(alert)
        if len(self._logs) > 100:
            self._logs = self._logs[-100:]

        logger.info(
            "Monitor alert [%s/%s]: %s",
            alert.get("type", "?"),
            alert.get("category", "?"),
            alert.get("message", ""),
        )

        if not self._clients:
            return

        dead: Set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(alert)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """
        Loop assíncrono executado em background.
        Verifica CPU, RAM, bateria e Downloads a cada CHECK_INTERVAL segundos.
        """
        # Controle de cooldown por categoria
        _last: Dict[str, float] = {
            "cpu":     0.0,
            "ram":     0.0,
            "battery": 0.0,
        }

        while self._running:
            now = asyncio.get_event_loop().time()

            # ── CPU ──────────────────────────────────────────────────────────
            try:
                cpu_pct = psutil.cpu_percent(interval=0.3)
                if cpu_pct > CPU_THRESHOLD and (now - _last["cpu"]) > ALERT_COOLDOWN:
                    _last["cpu"] = now
                    await self.broadcast({
                        "type":      "error",
                        "category":  "cpu",
                        "title":     "CPU Crítica",
                        "message":   (
                            f"Uso de CPU em {cpu_pct:.1f}%! "
                            "Verifique processos pesados em execução."
                        ),
                        "timestamp": datetime.now().isoformat(),
                        "value":     cpu_pct,
                    })
            except Exception as exc:
                logger.debug("Erro ao ler CPU: %s", exc)

            # ── RAM ──────────────────────────────────────────────────────────
            try:
                vm = psutil.virtual_memory()
                if vm.percent > RAM_THRESHOLD and (now - _last["ram"]) > ALERT_COOLDOWN:
                    _last["ram"] = now
                    await self.broadcast({
                        "type":      "error",
                        "category":  "ram",
                        "title":     "Memória RAM Crítica",
                        "message":   (
                            f"RAM em {vm.percent:.1f}% utilizada "
                            f"({_fmt_bytes(vm.used)} / {_fmt_bytes(vm.total)})."
                        ),
                        "timestamp": datetime.now().isoformat(),
                        "value":     vm.percent,
                    })
            except Exception as exc:
                logger.debug("Erro ao ler RAM: %s", exc)

            # ── Bateria ───────────────────────────────────────────────────────
            try:
                battery = psutil.sensors_battery()
                if (
                    battery is not None
                    and not battery.power_plugged
                    and battery.percent < BATTERY_LOW
                    and (now - _last["battery"]) > ALERT_COOLDOWN
                ):
                    _last["battery"] = now
                    await self.broadcast({
                        "type":      "warning",
                        "category":  "battery",
                        "title":     "Bateria Fraca",
                        "message":   (
                            f"Bateria em {battery.percent:.0f}% e sem carregador. "
                            "Conecte o cabo agora."
                        ),
                        "timestamp": datetime.now().isoformat(),
                        "value":     battery.percent,
                    })
            except Exception as exc:
                logger.debug("Erro ao ler bateria: %s", exc)

            # ── Watcher de Downloads ──────────────────────────────────────────
            if self._downloads.exists():
                try:
                    current: Set[str] = {
                        f.name for f in self._downloads.iterdir() if f.is_file()
                    }
                    new_files = current - self._known_files
                    for fname in sorted(new_files):
                        if Path(fname).suffix.lower() in IMPORTANT_EXTS:
                            await self.broadcast({
                                "type":      "info",
                                "category":  "file",
                                "title":     "Novo Arquivo",
                                "message":   f"Arquivo recebido em Downloads: **{fname}**",
                                "timestamp": datetime.now().isoformat(),
                                "value":     fname,
                            })
                    self._known_files = current
                except PermissionError:
                    pass

            await asyncio.sleep(CHECK_INTERVAL)


# ---------------------------------------------------------------------------
# Singleton — importado por main.py e system_agent.py
# ---------------------------------------------------------------------------

monitor_service = MonitorService()
