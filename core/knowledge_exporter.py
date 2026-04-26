"""
core/knowledge_exporter.py — Exportador de base de conhecimento para NotebookLM.

Consolida todo o código-fonte do projeto Alfred em um único arquivo Markdown
estruturado, pronto para upload no NotebookLM ou outro processador de documentos.

Fluxo:
    1. Varre os diretórios de backend (agents/, core/, memory/) e main.py.
    2. Varre frontend/src/ em busca de .tsx e .ts.
    3. Varre data/docs/ em busca de documentos textuais (.md, .txt, .rst).
    4. Gera Alfred_Knowledge_Base.md na raiz do projeto.
    5. Retorna o Path absoluto do arquivo gerado.

Segurança:
    • Nenhum dado é enviado a APIs externas — operação 100% local.
    • Leitura restrita a extensões de código e documento definidas em allowlists.
    • Pastas sensíveis (.venv, node_modules, .git) são sempre ignoradas.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração static
# ---------------------------------------------------------------------------

# Raiz do projeto — core/ está um nível abaixo deste arquivo
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Extensões de código-fonte aceitas
_CODE_EXTENSIONS = frozenset({".py", ".tsx", ".ts"})

# Extensões de documento aceitas para a seção de docs
_DOC_EXTENSIONS = frozenset({".md", ".txt", ".rst"})

# Pastas de backend varridas em profundidade (relativas à raiz)
_BACKEND_DIRS: List[str] = ["agents", "core", "memory"]

# Arquivos avulsos na raiz do projeto
_ROOT_FILES: List[str] = ["main.py"]

# Sub-diretório de src do frontend
_FRONTEND_SRC: str = "frontend/src"

# Diretório de documentação adicional
_DOCS_DIR: str = "data/docs"

# Diretórios que nunca devem ser incluídos (verificado em cada segmento do path)
_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".venv", "venv", "node_modules",
    ".git", "dist", "build", ".mypy_cache", ".pytest_cache",
    "coverage", ".tox",
})

# Mapeamento de extensão → linguagem para fence code blocks
_LANG_MAP: dict[str, str] = {
    ".py":  "python",
    ".tsx": "tsx",
    ".ts":  "typescript",
    ".md":  "markdown",
    ".txt": "",
    ".rst": "rst",
}


# ---------------------------------------------------------------------------
# KnowledgeExporter
# ---------------------------------------------------------------------------

class KnowledgeExporter:
    """
    Consolida o código-fonte e os documentos do projeto Alfred em um arquivo
    Markdown estruturado para ingestão pelo NotebookLM.

    Args:
        project_root: Raiz do projeto. Padrão: diretório pai de ``core/``.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self._root: Path = (project_root or _PROJECT_ROOT).resolve()
        self._output_path: Path = self._root / "Alfred_Knowledge_Base.md"

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def export(self) -> Path:
        """
        Gera o arquivo ``Alfred_Knowledge_Base.md`` na raiz do projeto.

        Returns:
            Path absoluto do arquivo gerado.
        """
        sections: List[str] = []
        total_files, total_lines = self._count_stats()
        now = datetime.now().strftime("%d/%m/%Y às %H:%M")

        # ── Cabeçalho ─────────────────────────────────────────────────
        sections.append(
            f"# Alfred AI — Base de Conhecimento Técnico\n\n"
            f"> **Gerado em:** {now}  \n"
            f"> **Arquivos incluídos:** {total_files}  \n"
            f"> **Total de linhas:** {total_lines:,}\n\n"
            "Este documento foi gerado automaticamente pelo `KnowledgeExporter` do Alfred AI. "
            "Ele consolida todo o código-fonte e a documentação do projeto em um único arquivo "
            "para análise, documentação assistida e integração com o NotebookLM.\n\n"
            "---\n"
        )

        # ── Índice ────────────────────────────────────────────────────
        sections.append(
            "## Índice\n\n"
            "1. [Ponto de Entrada](#ponto-de-entrada)\n"
            "2. [Agentes](#agentes)\n"
            "3. [Core](#core)\n"
            "4. [Memória](#memoria)\n"
            "5. [Frontend](#frontend)\n"
            "6. [Documentação e README](#documentacao-e-readme)\n\n"
            "---\n"
        )

        # ── Ponto de entrada (main.py) ────────────────────────────────
        sections.append("\n## Ponto de Entrada\n\n")
        for fname in _ROOT_FILES:
            fpath = self._root / fname
            if fpath.exists():
                sections.append(self._render_code_file(fpath, base=self._root))

        # ── Diretórios de backend ─────────────────────────────────────
        _section_labels = {
            "agents": "Agentes",
            "core":   "Core",
            "memory": "Memória",
        }
        for dir_name in _BACKEND_DIRS:
            dir_path = self._root / dir_name
            if not dir_path.is_dir():
                continue
            label = _section_labels.get(dir_name, dir_name.title())
            sections.append(f"\n## {label}\n\n")
            for fpath in sorted(dir_path.rglob("*")):
                if self._should_include_code(fpath):
                    sections.append(self._render_code_file(fpath, base=self._root))

        # ── Frontend ──────────────────────────────────────────────────
        frontend_path = self._root / _FRONTEND_SRC
        if frontend_path.is_dir():
            sections.append("\n## Frontend\n\n")
            for fpath in sorted(frontend_path.rglob("*")):
                if self._should_include_code(fpath):
                    sections.append(self._render_code_file(fpath, base=self._root))

        # ── Documentação e README ─────────────────────────────────────
        sections.append("\n## Documentação e README\n\n")

        docs_path = self._root / _DOCS_DIR
        if docs_path.is_dir():
            doc_files = sorted(
                p for p in docs_path.rglob("*")
                if p.is_file() and p.suffix.lower() in _DOC_EXTENSIONS
            )
            if doc_files:
                for fpath in doc_files:
                    sections.append(self._render_doc_file(fpath, base=self._root))
            else:
                sections.append("*Nenhum documento encontrado em `data/docs/`.*\n\n")
        else:
            sections.append("*Pasta `data/docs/` não encontrada.*\n\n")

        readme = self._root / "README.md"
        if readme.exists():
            sections.append("### `README.md`\n\n")
            try:
                sections.append(readme.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                sections.append(f"*Erro ao ler README.md: {exc}*\n")
            sections.append("\n\n---\n")

        # ── Grava arquivo ─────────────────────────────────────────────
        content = "\n".join(sections)
        self._output_path.write_text(content, encoding="utf-8")

        size_kb = self._output_path.stat().st_size / 1024
        logger.info(
            "KnowledgeExporter | gerado=%s | tamanho=%.1f KB | arquivos=%d | linhas=%d",
            self._output_path.name,
            size_kb,
            total_files,
            total_lines,
        )
        return self._output_path

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _should_include_code(self, path: Path) -> bool:
        """Retorna True se o arquivo deve ser incluído como código-fonte."""
        if not path.is_file():
            return False
        if path.suffix.lower() not in _CODE_EXTENSIONS:
            return False
        for part in path.parts:
            if part in _SKIP_DIRS:
                return False
        return True

    def _render_code_file(self, path: Path, base: Path | None = None) -> str:
        """Renderiza um arquivo de código como seção Markdown com fence block."""
        rel = path.relative_to(base) if base else Path(path.name)
        lang = _LANG_MAP.get(path.suffix.lower(), "")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Não foi possível ler '%s': %s", path, exc)
            return f"### `{rel}`\n\n*Erro ao ler arquivo: {exc}*\n\n---\n"

        line_count = content.count("\n") + 1
        return (
            f"### `{rel}` — {line_count} linhas\n\n"
            f"```{lang}\n"
            f"{content}\n"
            f"```\n\n---\n"
        )

    def _render_doc_file(self, path: Path, base: Path | None = None) -> str:
        """Renderiza um arquivo de documentação como seção Markdown simples."""
        rel = path.relative_to(base) if base else Path(path.name)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Não foi possível ler '%s': %s", path, exc)
            return f"### `{rel}`\n\n*Erro ao ler documento: {exc}*\n\n---\n"

        return f"### `{rel}`\n\n{content}\n\n---\n"

    def _count_stats(self) -> Tuple[int, int]:
        """Conta o total de arquivos e linhas que serão exportados (sem ler duas vezes)."""
        files = 0
        lines = 0

        candidates: List[Path] = []

        for fname in _ROOT_FILES:
            fpath = self._root / fname
            if fpath.exists():
                candidates.append(fpath)

        for dir_name in _BACKEND_DIRS:
            dir_path = self._root / dir_name
            if dir_path.is_dir():
                candidates.extend(
                    p for p in dir_path.rglob("*") if self._should_include_code(p)
                )

        frontend_path = self._root / _FRONTEND_SRC
        if frontend_path.is_dir():
            candidates.extend(
                p for p in frontend_path.rglob("*") if self._should_include_code(p)
            )

        docs_path = self._root / _DOCS_DIR
        if docs_path.is_dir():
            candidates.extend(
                p for p in docs_path.rglob("*")
                if p.is_file() and p.suffix.lower() in _DOC_EXTENSIONS
            )

        for fpath in candidates:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                files += 1
                lines += content.count("\n") + 1
            except OSError:
                pass

        return files, lines
