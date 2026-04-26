from __future__ import annotations
"""
agents/dev_agent.py — Agente de Desenvolvimento do Alfred.

Responsabilidades:
    • git_status     — verifica arquivos modificados/untracked no projeto.
    • summarize_file — lê um arquivo .py / .tsx e gera resumo técnico.
    • suggest_commit — analisa o diff e sugere mensagem Conventional Commits.
    • tech_stack     — detecta as tecnologias do projeto e persiste na memória
                       vetorial (ChromaDB) para enriquecer sugestões futuras.
    • lab_status     — retorna linha de status usada pelo Morning Briefing.

Segurança:
    • Todas as chamadas Git usam subprocess com lista de argumentos (sem shell=True).
    • O diretório de projeto é validado antes de qualquer operação.
    • O leitor de arquivos limita a leitura a MAX_FILE_BYTES para evitar DoS.
    • Nenhum dado sensível (.env, credenciais) é enviado ao LLM.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

MAX_FILE_BYTES = 32_768          # 32 KB — limite seguro para resumo de arquivo
_SAFE_EXTENSIONS = {             # extensões permitidas para leitura/resumo
    ".py", ".tsx", ".ts", ".js", ".jsx",
    ".md", ".json", ".yaml", ".yml", ".toml",
    ".css", ".html", ".sh",
}

# ---------------------------------------------------------------------------
# LLM builder para edição de arquivos
# ---------------------------------------------------------------------------

def _build_edit_llms() -> list:
    """Retorna lista de LLMs para edição de arquivos (Gemini → Groq fallback)."""
    from core.config import get_settings

    settings = get_settings()
    llms = []

    if settings.gemini_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import]
            llms.append(ChatGoogleGenerativeAI(
                model=settings.model_name,
                google_api_key=settings.gemini_api_key,
                temperature=0.1,
                max_output_tokens=4096,
            ))
        except Exception:
            pass

    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq  # type: ignore[import]
            from pydantic import SecretStr as _SecretStr
            llms.append(ChatGroq(
                model=settings.groq_model,
                api_key=_SecretStr(settings.groq_api_key),
                temperature=0.1,
                max_tokens=4096,
            ))
        except Exception:
            pass

    return llms

# Mapeamento de marcadores de tecnologia → nome humano
_TECH_MARKERS: Dict[str, str] = {
    "requirements.txt":  "Python/pip",
    "pyproject.toml":    "Python/pyproject",
    "package.json":      "Node.js/npm",
    "tsconfig.json":     "TypeScript",
    "tailwind.config.js":"Tailwind CSS",
    "vite.config.ts":    "Vite",
    "Dockerfile":        "Docker",
    "docker-compose.yml":"Docker Compose",
    "docker-compose.yaml":"Docker Compose",
    ".fastapi":          "FastAPI",           # marcador virtual (ver _detect_tech)
    "chromadb":          "ChromaDB",          # marcador virtual
    "langchain":         "LangChain",         # marcador virtual
}

# Padrões de import Python que indicam tecnologia usada
_IMPORT_TECH: Dict[str, str] = {
    "fastapi":           "FastAPI",
    "langchain":         "LangChain",
    "chromadb":          "ChromaDB",
    "pydantic":          "Pydantic",
    "sqlalchemy":        "SQLAlchemy",
    "uvicorn":           "Uvicorn",
    "sentence_transformers": "Sentence-Transformers",
    "react":             "React",
    "openai":            "OpenAI SDK",
    "google.generativeai": "Google Generative AI",
}


# ---------------------------------------------------------------------------
# Git helpers (subprocess — sem shell=True)
# ---------------------------------------------------------------------------

def _validate_project_path(path: Path) -> None:
    """Lança ValueError se o caminho não for um diretório Git acessível."""
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Diretório de projeto não encontrado: {path}")
    git_dir = path / ".git"
    if not git_dir.exists():
        raise ValueError(
            f"'{path}' não é um repositório Git. "
            "Inicialize com `git init` antes de usar o DevAgent."
        )


def _run_git(args: List[str], cwd: Path, timeout: int = 10) -> str:
    """
    Executa um comando git com lista de argumentos (sem shell=True).
    Retorna stdout como string. Lança RuntimeError se o comando falhar.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and result.stderr:
            raise RuntimeError(result.stderr.strip())
        return result.stdout.strip()
    except FileNotFoundError as exc:
        raise RuntimeError("Git não encontrado. Instale o Git para usar esta função.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timeout ao executar o Git.") from exc


def _git_status(project_path: Path) -> Dict[str, Any]:
    """
    Retorna um dict com:
        - modified:    lista de arquivos modificados
        - untracked:   lista de arquivos novos não rastreados
        - staged:      lista de arquivos no stage (prontos para commit)
        - branch:      nome do branch atual
        - ahead_behind: string "↑2 ↓0" se remoto disponível, senão ""
    """
    _validate_project_path(project_path)

    # Status curto (machine-readable)
    raw = _run_git(["status", "--short", "--porcelain"], project_path)
    modified:  List[str] = []
    untracked: List[str] = []
    staged:    List[str] = []

    for line in raw.splitlines():
        if len(line) < 3:
            continue
        index_status  = line[0]   # status na staging area
        worktree_status = line[1] # status na worktree
        filepath = line[3:].strip()

        if index_status in ("A", "M", "R", "D"):
            staged.append(filepath)
        if worktree_status in ("M", "D"):
            modified.append(filepath)
        if index_status == "?" and worktree_status == "?":
            untracked.append(filepath)

    # Branch atual
    try:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], project_path)
    except RuntimeError:
        branch = "desconhecido"

    # Ahead / behind do remoto (opcional — falha silenciosa se não houver remoto)
    ahead_behind = ""
    try:
        ab = _run_git(
            ["rev-list", "--left-right", "--count", f"{branch}@{{upstream}}...HEAD"],
            project_path,
        )
        parts = ab.split()
        if len(parts) == 2:
            behind, ahead = parts
            ahead_behind = f"↑{ahead} ↓{behind}"
    except RuntimeError:
        pass

    return {
        "modified":    modified,
        "untracked":   untracked,
        "staged":      staged,
        "branch":      branch,
        "ahead_behind": ahead_behind,
    }


def _git_diff_stat(project_path: Path) -> str:
    """Retorna `git diff --stat HEAD` para alimentar a sugestão de commit."""
    try:
        diff = _run_git(["diff", "--stat", "HEAD"], project_path)
        if not diff:
            diff = _run_git(["diff", "--stat", "--cached"], project_path)
        return diff[:2000]   # limita tamanho
    except RuntimeError:
        return ""


# ---------------------------------------------------------------------------
# File reader
# ---------------------------------------------------------------------------

def _safe_read_file(path: Path) -> str:
    """
    Lê um arquivo de código-fonte de forma segura (limite de tamanho,
    extensão permitida). Lança ValueError para entradas inválidas.
    """
    if path.suffix.lower() not in _SAFE_EXTENSIONS:
        raise ValueError(
            f"Extensão '{path.suffix}' não suportada. "
            f"Extensões permitidas: {', '.join(sorted(_SAFE_EXTENSIONS))}"
        )
    if not path.is_file():
        raise ValueError(f"Arquivo não encontrado: {path}")

    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Arquivo muito grande ({size // 1024} KB). "
            f"Limite: {MAX_FILE_BYTES // 1024} KB."
        )

    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Tech stack detection
# ---------------------------------------------------------------------------

def _detect_tech(project_path: Path) -> List[str]:
    """
    Detecta as tecnologias usadas no projeto de forma estática
    (sem executar código): lê arquivos de marcador e scanneia imports.
    """
    techs: set[str] = set()

    # Marcadores de arquivo
    for marker, tech in _TECH_MARKERS.items():
        if marker.startswith("."):
            continue  # marcadores virtuais ignorados aqui
        if (project_path / marker).exists():
            techs.add(tech)

    # Scan de requirements.txt para pacotes Python
    req_file = project_path / "requirements.txt"
    if req_file.exists():
        content = req_file.read_text(encoding="utf-8", errors="replace").lower()
        for pkg, tech in _IMPORT_TECH.items():
            if pkg in content:
                techs.add(tech)

    # Scan de package.json para dependências JS/TS
    pkg_json = project_path / "package.json"
    if pkg_json.exists():
        content = pkg_json.read_text(encoding="utf-8", errors="replace").lower()
        if "react" in content:
            techs.add("React")
        if "tailwindcss" in content:
            techs.add("Tailwind CSS")
        if "vite" in content:
            techs.add("Vite")
        if "typescript" in content:
            techs.add("TypeScript")
        if "axios" in content:
            techs.add("Axios")
        if "lucide" in content:
            techs.add("Lucide React")

    return sorted(techs)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _format_git_status(status: Dict[str, Any], project_name: str) -> str:
    total_changes = (
        len(status["staged"])
        + len(status["modified"])
        + len(status["untracked"])
    )

    if total_changes == 0:
        return (
            f"✅ **{project_name}** está limpo.\n"
            f"🌿 Branch: `{status['branch']}`  —  Nada a commitar."
        )

    lines: List[str] = [
        f"📁 **Status do Repositório — {project_name}**",
        f"🌿 Branch: `{status['branch']}`"
        + (f"  {status['ahead_behind']}" if status["ahead_behind"] else ""),
        "",
    ]

    if status["staged"]:
        lines.append(f"✅ **Staged ({len(status['staged'])})**")
        for f in status["staged"][:10]:
            lines.append(f"  • `{f}`")
        if len(status["staged"]) > 10:
            lines.append(f"  … e mais {len(status['staged']) - 10}")

    if status["modified"]:
        lines.append(f"📝 **Modificados ({len(status['modified'])})**")
        for f in status["modified"][:10]:
            lines.append(f"  • `{f}`")
        if len(status["modified"]) > 10:
            lines.append(f"  … e mais {len(status['modified']) - 10}")

    if status["untracked"]:
        lines.append(f"❓ **Não rastreados ({len(status['untracked'])})**")
        for f in status["untracked"][:5]:
            lines.append(f"  • `{f}`")
        if len(status["untracked"]) > 5:
            lines.append(f"  … e mais {len(status['untracked']) - 5}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DevAgent
# ---------------------------------------------------------------------------

class DevAgent(BaseAgent):
    """
    Agente de desenvolvimento: Git, resumo de código, Conventional Commits
    e memória de stack técnica no ChromaDB.

    Recebe o VectorStore do orquestrador para salvar/recuperar contexto
    de tecnologias sem criar um segundo cliente ChromaDB.
    """

    def __init__(self, vector_store: Any = None) -> None:
        super().__init__(name="DevAgent")
        self._settings   = get_settings()
        self._vector_store = vector_store   # injetado pelo orquestrador
        self._edit_llms: list | None = None  # inicialização lazy

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
    ) -> str:
        action, payload = self._extract_action(message)

        logger.info(
            "DevAgent | session=%s | action=%s | payload=%.60s",
            session_id, action, payload,
        )

        if action == "git_status":
            return self._action_git_status()
        if action == "summarize_file":
            return self._action_summarize_file(payload, session_id)
        if action == "suggest_commit":
            return self._action_suggest_commit()
        if action == "tech_stack":
            return self._action_tech_stack(session_id)
        if action == "lab_status":
            return self.lab_status_line()
        if action == "edit_file":
            return self._action_edit_file(message, session_id)
        if action == "self_improve":
            return self._action_self_improve(message, session_id)

        # Fallback: status git é a ação mais útil por padrão
        return self._action_git_status()

    # ------------------------------------------------------------------
    # Lab Status (chamado pelo IntegrationAgent no morning briefing)
    # ------------------------------------------------------------------

    def lab_status_line(self) -> str:
        """
        Retorna uma linha curta para o Morning Briefing.
        Exemplo: "Senhor, o projeto alfred tem 3 arquivos modificados aguardando commit."
        """
        project_path = self._project_path()
        project_name = project_path.name

        try:
            status = _git_status(project_path)
        except (ValueError, RuntimeError) as exc:
            return f"⚙️ **Status do Lab:** {exc}"

        total_pending = len(status["modified"]) + len(status["untracked"])
        staged_count  = len(status["staged"])

        if total_pending == 0 and staged_count == 0:
            return (
                f"⚙️ **Status do Lab:** Projeto `{project_name}` — "
                f"repositório limpo no branch `{status['branch']}`."
            )

        parts: List[str] = []
        if status["staged"]:
            parts.append(f"{staged_count} arquivo(s) no stage")
        if total_pending:
            parts.append(f"{total_pending} arquivo(s) modificados/novos aguardando commit")

        summary = " e ".join(parts)
        return (
            f"⚙️ **Status do Lab:** Senhor, o projeto `{project_name}` tem "
            f"{summary}. Branch: `{status['branch']}`"
            + (f" {status['ahead_behind']}" if status["ahead_behind"] else "")
            + "."
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_git_status(self) -> str:
        project_path = self._project_path()
        try:
            status = _git_status(project_path)
            return _format_git_status(status, project_path.name)
        except (ValueError, RuntimeError) as exc:
            return f"⚠️ Não foi possível verificar o status Git: {exc}"

    def _action_summarize_file(self, filepath: str, session_id: str) -> str:
        if not filepath:
            return (
                "📄 Informe o caminho do arquivo para resumir.\n"
                "Exemplo: *'resuma o arquivo agents/dev_agent.py'*"
            )

        # Resolve relativo ao projeto ou absoluto
        path = Path(filepath)
        if not path.is_absolute():
            path = self._project_path() / filepath

        try:
            code = _safe_read_file(path)
        except ValueError as exc:
            return f"⚠️ {exc}"

        summary = _summarize_code(path.name, path.suffix.lower(), code)

        # Persiste o resumo na memória vetorial para RAG futuro
        if self._vector_store:
            try:
                self._vector_store.add_memory(
                    text=f"Resumo técnico de {path.name}:\n{summary}",
                    metadata={
                        "session_id": session_id,
                        "type": "code_summary",
                        "filename": path.name,
                        "extension": path.suffix.lower(),
                    },
                )
            except Exception:
                pass   # falha silenciosa — não bloqueia a resposta

        return summary

    def _action_suggest_commit(self) -> str:
        project_path = self._project_path()
        try:
            status = _git_status(project_path)
            diff   = _git_diff_stat(project_path)
        except (ValueError, RuntimeError) as exc:
            return f"⚠️ Não foi possível obter o diff Git: {exc}"

        total = (
            len(status["staged"])
            + len(status["modified"])
            + len(status["untracked"])
        )
        if total == 0:
            return "✅ Nenhuma alteração encontrada. Repositório limpo."

        return _suggest_conventional_commit(status, diff)

    def _action_edit_file(self, message: str, session_id: str) -> str:
        """
        Edita um arquivo de código com base na instrução em linguagem natural.
        Faz backup automático (.bak) antes de escrever.
        """
        import re as _re

        # ── Extrai caminho do arquivo ──────────────────────────────────
        m = _re.search(
            r'(?:arquivo|file)\s+["\']?([^\s"\',]+\.[a-zA-Z]{2,5})["\']?',
            message, _re.IGNORECASE,
        )
        if not m:
            m = _re.search(
                r'([\w/\\\-]+\.(?:py|tsx|ts|js|jsx|md|json|yaml|yml|toml|css|html|sh))',
                message,
            )
        if not m:
            return (
                "Não identifiquei qual arquivo editar. "
                "Exemplo: *'edite o arquivo agents/dev_agent.py e adicione X'*"
            )

        filepath_str = m.group(1)
        path = Path(filepath_str)
        if not path.is_absolute():
            path = self._project_path() / filepath_str

        # ── Valida extensão e existência ───────────────────────────────
        if path.suffix.lower() not in _SAFE_EXTENSIONS:
            return (
                f"Extensão '{path.suffix}' não é editável pelo Alfred. "
                f"Extensões suportadas: {', '.join(sorted(_SAFE_EXTENSIONS))}"
            )
        if not path.is_file():
            return f"Arquivo não encontrado: `{path}`"

        # ── Lê conteúdo atual ──────────────────────────────────────────
        try:
            current_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Não consegui ler o arquivo: {exc}"

        if path.stat().st_size > MAX_FILE_BYTES * 4:  # 128 KB max para edição
            return (
                f"Arquivo muito grande ({path.stat().st_size // 1024} KB) para edição automática. "
                "Limite: 128 KB."
            )

        # ── Inicializa LLMs se necessário ─────────────────────────────
        if self._edit_llms is None:
            self._edit_llms = _build_edit_llms()
        if not self._edit_llms:
            return "Nenhum LLM disponível para edição. Configure GEMINI_API_KEY ou GROQ_API_KEY no .env"

        # ── Prompt de edição ──────────────────────────────────────────
        system_prompt = (
            "Você é um assistente especialista em código. "
            "Receberá o conteúdo atual de um arquivo e uma instrução de mudança. "
            "Retorne APENAS o novo conteúdo completo do arquivo, sem nenhuma explicação, "
            "sem markdown, sem blocos de código (``` não deve aparecer). "
            "Preserve a indentação e o estilo do código original."
        )
        user_prompt = (
            f"Arquivo: {path.name}\n\n"
            f"Conteúdo atual:\n{current_content}\n\n"
            f"Instrução: {message}\n\n"
            "Retorne o arquivo completo com as alterações aplicadas:"
        )

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        # ── Chama LLM com fallback ────────────────────────────────────
        new_content: str | None = None
        last_exc: Exception | None = None
        for llm in self._edit_llms:
            try:
                response = llm.invoke(messages)
                new_content = str(response.content).strip()
                break
            except Exception as exc:
                logger.warning("DevAgent edit_file: provider falhou: %s", exc)
                last_exc = exc

        if new_content is None:
            return f"Não foi possível editar o arquivo: {last_exc}"

        # Remove blocos de código markdown caso o modelo os adicione
        import re as _re2
        new_content = _re2.sub(
            r'^```[\w]*\n?|\n?```$', '', new_content, flags=_re2.MULTILINE
        ).strip()

        # ── Backup e escrita ──────────────────────────────────────────
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            backup_path.write_text(current_content, encoding="utf-8")
            path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return f"Erro ao gravar o arquivo: {exc}"

        lines_before = current_content.count("\n") + 1
        lines_after  = new_content.count("\n") + 1
        delta = lines_after - lines_before
        delta_str = f"+{delta}" if delta >= 0 else str(delta)

        logger.info(
            "DevAgent | edit_file | session=%s | file=%s | linhas=%d→%d",
            session_id, path.name, lines_before, lines_after,
        )
        return (
            f"Arquivo `{path.name}` atualizado com sucesso. "
            f"({lines_before}→{lines_after} linhas, {delta_str}). "
            f"Backup salvo em `{backup_path.name}`."
        )

    def _action_self_improve(self, message: str, session_id: str) -> str:
        """
        Auto-incrementa o Alfred: usa LLM para planejar e implementar
        uma nova funcionalidade descrita pelo usuário em linguagem natural.
        """
        import re as _re

        project_path = self._project_path()

        # ── Monta árvore do projeto ──────────────────────────────────
        _SKIP = {".venv", "__pycache__", ".git", "node_modules", "dist", ".bak"}
        tree_lines: List[str] = []
        for p in sorted(project_path.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".py", ".tsx", ".ts"}:
                continue
            rel = str(p.relative_to(project_path)).replace("\\", "/")
            if any(s in rel for s in _SKIP):
                continue
            tree_lines.append(rel)
        project_tree = "\n".join(tree_lines[:70])

        # ── Lê arquivos-chave para contexto ──────────────────────────
        def _ctx(relpath: str, maxchars: int = 3000) -> str:
            fp = project_path / relpath
            if fp.exists():
                return fp.read_text(encoding="utf-8", errors="replace")[:maxchars]
            return "— não encontrado —"

        ctx_base    = _ctx("agents/base_agent.py")
        ctx_orch    = _ctx("core/orchestrator.py", 2500)
        ctx_intent  = _ctx("core/intent_classifier.py", 2500)

        # ── Prompt ──────────────────────────────────────────────
        system_prompt = (
            "Você é especialista em expandir o sistema Alfred AI.\n"
            "Ao receber uma solicitação de nova funcionalidade, gere o código necessário.\n\n"
            "Responda EXATAMENTE neste formato (sem texto fora dos marcadores):\n\n"
            "PLAN: <descrição do que será implementado em 1-2 frases>\n\n"
            "FILE_START <caminho/relativo.py> <CREATE|MODIFY>\n"
            "<conteúdo COMPLETO do arquivo>\n"
            "FILE_END\n\n"
            "Repita FILE_START...FILE_END para cada arquivo.\n\n"
            "Regras:\n"
            "- Novos agentes herdam de BaseAgent e implementam process()\n"
            "- Registre novos agentes no dict self._agents em core/orchestrator.py\n"
            "- Adicione regras nos _DEV_RULES/_SYSTEM_RULES de core/intent_classifier.py\n"
            "- Caminhos relativos à raiz do projeto (ex: agents/novo.py)\n"
            "- Apenas diretórios: agents/, core/ (PROIBIDO alterar main.py, memory/, frontend/)\n"
            "- Conteúdo do arquivo sempre COMPLETO, sem truncar\n"
            "- Responda SOMENTE com PLAN + FILE_START...FILE_END, nada mais"
        )
        user_prompt = (
            f"=== ESTRUTURA DO PROJETO ===\n{project_tree}\n\n"
            f"=== agents/base_agent.py ===\n{ctx_base}\n\n"
            f"=== core/orchestrator.py (trecho) ===\n{ctx_orch}\n\n"
            f"=== core/intent_classifier.py (trecho) ===\n{ctx_intent}\n\n"
            f"=== SOLICITAÇÃO ===\n{message}\n\n"
            "Gere o plano e os arquivos:"
        )

        # ── Inicializa LLMs ────────────────────────────────────────
        if self._edit_llms is None:
            self._edit_llms = _build_edit_llms()
        if not self._edit_llms:
            return "Nenhum LLM disponível. Configure GEMINI_API_KEY ou GROQ_API_KEY no .env"

        # ── Chama LLM com fallback ─────────────────────────────────
        from langchain_core.messages import HumanMessage, SystemMessage
        lc_msgs = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        raw: str | None = None
        for llm in self._edit_llms:
            try:
                resp = llm.invoke(lc_msgs)
                raw = str(resp.content).strip()
                break
            except Exception as exc:
                logger.warning("self_improve: LLM falhou: %s", exc)

        if not raw:
            return "Não foi possível gerar o plano de implementação. Verifique os logs."

        # ── Parseia resposta ───────────────────────────────────────
        plan_m    = _re.search(r"PLAN:\s*(.+?)(?=\nFILE_START|\Z)", raw, _re.DOTALL)
        plan_desc = plan_m.group(1).strip() if plan_m else "sem descrição"

        file_blocks = _re.findall(
            r"FILE_START\s+(\S+)\s+(CREATE|MODIFY)\s*\n(.*?)FILE_END",
            raw, _re.DOTALL,
        )

        if not file_blocks:
            return (
                f"⚠️ O LLM não gerou arquivos no formato esperado.\n\n"
                f"**Resposta bruta:**\n```\n{raw[:1000]}\n```"
            )

        # ── Aplica arquivos (com validação de segurança) ──────────────
        ALLOWED_TOP = {"agents", "core"}
        ALLOWED_EXT = {".py", ".tsx", ".ts", ".js", ".jsx", ".css"}
        created:  List[str] = []
        modified: List[str] = []
        errors:   List[str] = []

        for rel_path, action, content in file_blocks:
            rel_path = rel_path.replace("\\", "/").lstrip("/")
            content  = content.strip()
            # Remove markdown code fences caso o modelo os inclua
            content  = _re.sub(r"^```[\w]*\n?|\n?```$", "", content, flags=_re.MULTILINE).strip()

            # Previne path traversal
            abs_path = (project_path / rel_path).resolve()
            try:
                abs_path.relative_to(project_path)
            except ValueError:
                errors.append(f"❌ Caminho fora do projeto: {rel_path}")
                continue

            if abs_path.suffix.lower() not in ALLOWED_EXT:
                errors.append(f"❌ Extensão não permitida: {abs_path.suffix} ({rel_path})")
                continue

            top_dir = rel_path.split("/")[0]
            if top_dir not in ALLOWED_TOP:
                errors.append(f"❌ Diretório protegido: {top_dir}/ (permitido: agents/, core/)")
                continue

            try:
                if action == "MODIFY" and abs_path.exists():
                    bak = abs_path.with_suffix(abs_path.suffix + ".bak")
                    bak.write_text(abs_path.read_text(encoding="utf-8"), encoding="utf-8")
                    abs_path.write_text(content, encoding="utf-8")
                    modified.append(rel_path)
                else:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(content, encoding="utf-8")
                    created.append(rel_path)
            except OSError as exc:
                errors.append(f"❌ Erro ao escrever {rel_path}: {exc}")

        logger.info(
            "DevAgent | self_improve | session=%s | created=%d | modified=%d | errors=%d",
            session_id, len(created), len(modified), len(errors),
        )

        # ── Relatório ────────────────────────────────────────────
        lines = ["\U0001f916 **Alfred Auto-Incremento**\n", f"\U0001f4cb **Plano:** {plan_desc}\n"]
        if created:
            lines.append(f"\u2705 **Arquivos criados ({len(created)}):**")
            lines += [f"  \u2022 `{f}`" for f in created]
        if modified:
            lines.append(f"\U0001f4dd **Arquivos modificados ({len(modified)}):**")
            lines += [f"  \u2022 `{f}` (backup .bak salvo)" for f in modified]
        if errors:
            lines.append(f"\n\u26a0\ufe0f **Erros ({len(errors)}):**")
            lines += [f"  {e}" for e in errors]
        if not created and not modified:
            lines.append("\u26a0\ufe0f Nenhum arquivo foi gerado pelo plano.")
        else:
            lines.append("\n\U0001f504 **Reinicie o backend** para carregar as novas funcionalidades.")

        return "\n".join(lines)

    def _action_tech_stack(self, session_id: str) -> str:
        project_path = self._project_path()
        techs = _detect_tech(project_path)

        if not techs:
            return (
                f"🔍 Não detectei tecnologias conhecidas em `{project_path.name}`.\n"
                "Verifique se o caminho do projeto está correto no `.env`."
            )

        # Persiste no ChromaDB — enriquece o RAG para sugestões futuras
        if self._vector_store:
            tech_text = (
                f"Stack tecnológica do projeto {project_path.name}: "
                + ", ".join(techs)
            )
            try:
                self._vector_store.add_memory(
                    text=tech_text,
                    metadata={
                        "session_id": session_id,
                        "type": "tech_stack",
                        "project": project_path.name,
                        "technologies": ", ".join(techs),
                    },
                    doc_id=f"tech_stack_{project_path.name}",
                )
                logger.info(
                    "DevAgent: stack técnica salva na memória vetorial | %d tecnologias",
                    len(techs),
                )
            except Exception as exc:
                logger.warning("DevAgent: falha ao salvar tech stack: %s", exc)

        lines = [
            f"🔧 **Stack Tecnológica — {project_path.name}**\n",
            *[f"  • {t}" for t in techs],
            "",
            "✅ Stack salva na memória de longo prazo do Alfred.",
            "   Nas próximas interações, usarei esse contexto para sugestões mais precisas.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _project_path(self) -> Path:
        """Retorna o caminho do projeto configurado (ou CWD como fallback)."""
        raw = getattr(self._settings, "project_path", "") or ""
        path = Path(raw).expanduser() if raw else Path.cwd()
        return path.resolve()

    @staticmethod
    def _extract_action(message: str) -> tuple[str, str]:
        """
        Detecta a ação do DevAgent e extrai payload (ex.: caminho de arquivo).
        Retorna (action, payload).
        """
        msg = message.lower()

        # Auto-incremento — verificar ANTES de editar arquivo
        if any(t in msg for t in (
            "adicione funcionalidade", "crie uma feature", "nova feature",
            "crie um agente", "auto incrementar", "auto melhorar",
            "adicione capacidade", "novo recurso", "new feature",
            "expanda o alfred", "melhore o alfred", "adicione habilidade",
            "implemente uma funcionalidade", "alfred se incremente",
            "adicione ao alfred", "crie para o alfred",
            "ensine o alfred", "self improve", "self increment",
        )):
            return "self_improve", ""

        # Editar arquivo — verificar antes do resumo
        if any(t in msg for t in (
            "edite", "altere", "modifique", "mude o arquivo", "editar arquivo",
            "alterar arquivo", "modificar arquivo", "edit file", "edit the file",
            "modify file", "update file", "atualize o arquivo", "reescreva",
            "adicione ao arquivo", "remova do arquivo", "insira no arquivo",
            "corrija o arquivo", "fix the file",
        )):
            return "edit_file", ""

        # Arquivo para resumo — extrai o caminho
        if any(t in msg for t in (
            "resuma", "resume", "summarize", "resumo do arquivo",
            "explique o arquivo", "documente", "descreva o arquivo",
        )):
            # Tenta extrair pathname da mensagem original
            import re
            m = re.search(
                r'(?:arquivo|file)\s+["\']?([^\s"\']+\.[a-zA-Z]{2,5})["\']?',
                message, re.IGNORECASE,
            )
            if not m:
                m = re.search(r'([^\s"\']+\.(?:py|tsx|ts|js|jsx|md|json|yaml|yml|toml))', message)
            payload = m.group(1) if m else ""
            return "summarize_file", payload

        # Sugestão de commit
        if any(t in msg for t in (
            "commit", "mensagem de commit", "conventional commit",
            "sugest", "o que commitar", "git commit",
        )):
            return "suggest_commit", ""

        # Tech stack
        if any(t in msg for t in (
            "stack", "tecnologia", "tecnologias", "tech stack",
            "quais tecnologias", "que tecnologia", "linguagem",
            "frameworks", "framework", "library", "bibliotecas",
            "memorize a stack", "salve a stack",
        )):
            return "tech_stack", ""

        # Status do lab
        if any(t in msg for t in (
            "lab status", "status do lab",
        )):
            return "lab_status", ""

        # Git status (padrão)
        return "git_status", ""


# ---------------------------------------------------------------------------
# Code summarizer (análise estática — sem LLM, zero custo)
# ---------------------------------------------------------------------------

def _summarize_code(filename: str, ext: str, code: str) -> str:
    """
    Gera um resumo técnico estático de um arquivo de código.
    Identifica: funções/classes definidas, imports, linhas de código,
    e padrões arquiteturais (FastAPI routes, React hooks, etc.).
    """
    import re

    lines = code.splitlines()
    loc   = len([l for l in lines if l.strip() and not l.strip().startswith("#")])

    sections: List[str] = [f"📄 **Resumo Técnico — `{filename}`**\n"]
    sections.append(f"📊 Linhas de código efetivas: **{loc}**\n")

    if ext == ".py":
        # Classes
        classes = re.findall(r"^class\s+(\w+)", code, re.MULTILINE)
        if classes:
            sections.append(f"🏗️ **Classes ({len(classes)}):** " + ", ".join(f"`{c}`" for c in classes))

        # Funções / métodos de nível
        funcs = re.findall(r"^(?:async\s+)?def\s+(\w+)", code, re.MULTILINE)
        public_funcs = [f for f in funcs if not f.startswith("_")]
        private_funcs = [f for f in funcs if f.startswith("_")]
        if public_funcs:
            sections.append(f"⚡ **Funções públicas ({len(public_funcs)}):** " + ", ".join(f"`{f}`" for f in public_funcs[:12]))
        if private_funcs:
            sections.append(f"🔒 **Privadas ({len(private_funcs)}):** " + ", ".join(f"`{f}`" for f in private_funcs[:8]))

        # FastAPI routes
        routes = re.findall(r'@app\.\w+\(["\']([^"\']+)["\']', code)
        if routes:
            sections.append(f"🚀 **FastAPI Routes ({len(routes)}):** " + ", ".join(f"`{r}`" for r in routes[:8]))

        # Imports principais
        imports = re.findall(r"^(?:import|from)\s+(\S+)", code, re.MULTILINE)
        top_imports = list(dict.fromkeys(imports))[:8]
        if top_imports:
            sections.append(f"📦 **Imports:** " + ", ".join(f"`{i}`" for i in top_imports))

    elif ext in (".tsx", ".ts", ".jsx", ".js"):
        # Componentes React (PascalCase)
        components = re.findall(r"(?:export\s+(?:default\s+)?function|const)\s+([A-Z]\w+)", code)
        if components:
            sections.append(f"⚛️ **Componentes ({len(components)}):** " + ", ".join(f"`{c}`" for c in components[:10]))

        # Hooks
        hooks_used = re.findall(r"\b(use[A-Z]\w+)\b", code)
        unique_hooks = list(dict.fromkeys(hooks_used))[:8]
        if unique_hooks:
            sections.append(f"🪝 **Hooks usados:** " + ", ".join(f"`{h}`" for h in unique_hooks))

        # Interfaces / types
        types_found = re.findall(r"(?:interface|type)\s+(\w+)", code)
        if types_found:
            sections.append(f"📐 **Types/Interfaces ({len(types_found)}):** " + ", ".join(f"`{t}`" for t in types_found[:8]))

        # Imports
        imports = re.findall(r"^import\s+.+\s+from\s+['\"]([^'\"]+)['\"]", code, re.MULTILINE)
        unique_imports = list(dict.fromkeys(imports))[:8]
        if unique_imports:
            sections.append(f"📦 **Imports:** " + ", ".join(f"`{i}`" for i in unique_imports))

    sections.append(
        "\n💡 *Resumo gerado por análise estática. "
        "Para documentação detalhada, use o GeneralAgent com o código colado.*"
    )
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Conventional Commits suggester (heurístico — sem LLM)
# ---------------------------------------------------------------------------

_CC_TYPES = {
    # (keywords no diff/status) → (tipo CC, emoji)
    "feat":     ("feat",     "✨"),
    "fix":      ("fix",      "🐛"),
    "docs":     ("docs",     "📚"),
    "style":    ("style",    "💄"),
    "refactor": ("refactor", "♻️"),
    "test":     ("test",     "🧪"),
    "chore":    ("chore",    "🔧"),
    "ci":       ("ci",       "👷"),
    "perf":     ("perf",     "⚡"),
}

_SCOPE_HINTS: List[tuple[str, str]] = [
    ("agent",       "agents"),
    ("frontend",    "frontend"),
    ("component",   "ui"),
    ("config",      "config"),
    ("api",         "api"),
    ("memory",      "memory"),
    ("voice",       "voice"),
    ("test",        "tests"),
    ("docker",      "docker"),
    ("readme",      "docs"),
]


def _suggest_conventional_commit(
    status: Dict[str, Any], diff_stat: str
) -> str:
    """
    Heurística para sugerir uma mensagem de commit Conventional Commits
    com base nos arquivos modificados e no diff --stat.
    """
    all_files = status["staged"] + status["modified"] + status["untracked"]
    combined  = " ".join(all_files).lower() + " " + diff_stat.lower()

    # Detecta tipo de commit
    cc_type, emoji = "chore", "🔧"
    if any(k in combined for k in ("test", "_test", "spec", ".test.")):
        cc_type, emoji = "test", "🧪"
    elif any(k in combined for k in ("readme", ".md", "docs", "doc")):
        cc_type, emoji = "docs", "📚"
    elif any(k in combined for k in ("style", "css", "tailwind", ".css")):
        cc_type, emoji = "style", "💄"
    elif any(k in combined for k in ("fix", "bug", "error", "hotfix")):
        cc_type, emoji = "fix", "🐛"
    elif any(k in combined for k in ("perf", "optim", "performance", "speed")):
        cc_type, emoji = "perf", "⚡"
    elif any(k in combined for k in ("refactor", "renam", "clean", "restruct")):
        cc_type, emoji = "refactor", "♻️"
    elif any(k in combined for k in ("add", "creat", "new", "feat", "implement")):
        cc_type, emoji = "feat", "✨"

    # Detecta escopo
    scope = ""
    for hint, sc in _SCOPE_HINTS:
        if hint in combined:
            scope = sc
            break

    # Gera descrição baseada nos arquivos mais relevantes
    sample_files = all_files[:4]
    if len(sample_files) == 1:
        fname = Path(sample_files[0]).stem.replace("_", " ").replace("-", " ")
        description = f"atualiza {fname}"
    elif len(all_files) <= 4:
        fnames = ", ".join(Path(f).stem for f in sample_files)
        description = f"atualiza {fnames}"
    else:
        description = f"atualiza {len(all_files)} arquivos"

    scope_str = f"({scope})" if scope else ""
    msg = f"{cc_type}{scope_str}: {description}"

    modified_count  = len(status["modified"])
    untracked_count = len(status["untracked"])
    staged_count    = len(status["staged"])

    lines = [
        f"{emoji} **Sugestão de Commit — Conventional Commits**\n",
        f"```",
        f"{msg}",
        f"```",
        "",
        "📋 **Detalhes:**",
    ]

    if staged_count:
        lines.append(f"  • {staged_count} arquivo(s) no stage")
    if modified_count:
        lines.append(f"  • {modified_count} arquivo(s) modificados")
    if untracked_count:
        lines.append(f"  • {untracked_count} arquivo(s) novos não rastreados")

    lines += [
        "",
        "💡 **Outras opções:**",
        f"  • `feat{scope_str}: adiciona <feature>` — para nova funcionalidade",
        f"  • `fix{scope_str}: corrige <bug>` — para correção de bug",
        f"  • `refactor{scope_str}: refatora <módulo>` — para refatoração",
        "",
        "⚡ Após revisar a mensagem, execute:",
        f"```bash",
        f"git add -A && git commit -m \"{msg}\"",
        f"```",
    ]
    return "\n".join(lines)
