"""Valida nomes e confina caminhos das ferramentas de arquivos."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_NOME_SIMPLES = re.compile(r"^[\w][\w .-]*$", re.UNICODE)
_IDENTIFICADOR = re.compile(r"^[a-z0-9_]{1,40}$")
_RESERVADOS_WINDOWS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validar_nome_simples(nome: str, *, limite: int = 100) -> str:
    """Valida um componente de nome sem permitir caminho ou ADS do Windows."""
    if not isinstance(nome, str):
        raise ValueError("O nome precisa ser texto.")
    valor = nome.strip()
    if (
        not valor
        or len(valor) > limite
        or valor in {".", ".."}
        or not _NOME_SIMPLES.fullmatch(valor)
        or valor.endswith((" ", "."))
        or nome.endswith(" ")
        or ":" in valor
        or ".." in valor
        or _reservado_windows(valor)
    ):
        raise ValueError("Use um nome simples, sem caminho ou caracteres reservados.")
    return valor


def normalizar_identificador(nome_exibicao: str) -> str:
    """Gera identificador ASCII previsível para uma pessoa."""
    nome = validar_nome_simples(nome_exibicao, limite=80)
    sem_acentos = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", nome.casefold())
        if not unicodedata.combining(caractere)
    )
    identificador = re.sub(r"[^a-z0-9]+", "_", sem_acentos).strip("_")
    return validar_identificador(identificador)


def validar_identificador(identificador: str) -> str:
    if (
        not isinstance(identificador, str)
        or not _IDENTIFICADOR.fullmatch(identificador)
        or _reservado_windows(identificador)
    ):
        raise ValueError("Identificador inválido; use até 40 letras, números ou _.")
    return identificador


def resolver_pasta_confinada(
    raiz: Path, *componentes: str, criar: bool = False
) -> Path:
    """Resolve subpastas sob a raiz, recusando links e escapes do diretório."""
    raiz_real = Path(raiz).resolve(strict=True)
    destino = raiz_real
    for componente in componentes:
        parte = validar_nome_simples(componente, limite=100)
        destino = destino / parte
        if _eh_link_ou_juncao(destino):
            raise ValueError("Links simbólicos ou junctions não são permitidos.")
        destino_real = _resolver(destino)
        if not _esta_dentro(destino_real, raiz_real):
            raise ValueError("O caminho precisa permanecer dentro da pasta autorizada.")
        if criar and not destino.exists():
            destino.mkdir()
            destino_real = _resolver(destino)
            if not _esta_dentro(destino_real, raiz_real):
                raise ValueError("O caminho precisa permanecer dentro da pasta autorizada.")
    return destino_real


def resolver_pasta_absoluta(
    pasta: Path, *, criar: bool = False, permitir_ausente: bool = False
) -> Path:
    """Valida uma pasta configurada, incluindo symlinks nos pais existentes."""
    caminho = Path(pasta)
    if not caminho.is_absolute():
        raise ValueError("A pasta configurada precisa ser absoluta.")
    atual = Path(caminho.anchor)
    for componente in caminho.parts[1:]:
        if componente == "..":
            raise ValueError("A pasta configurada não pode conter traversal.")
        atual = atual / componente
        if _eh_link_ou_juncao(atual):
            raise ValueError("Links simbólicos ou junctions não são permitidos.")
        if not atual.exists():
            if not criar:
                if not permitir_ausente:
                    raise ValueError("A pasta configurada não existe.")
                restante = caminho.parts[len(atual.parts):]
                for parte in restante:
                    if parte == "..":
                        raise ValueError("A pasta configurada não pode conter traversal.")
                    atual = atual / parte
                return _resolver(atual)
            try:
                atual.mkdir()
            except FileExistsError:
                pass
        if not atual.is_dir():
            raise ValueError("Um componente do caminho não é uma pasta.")
        atual = _resolver(atual)
    return atual


def resolver_arquivo_confinado(pasta: Path, nome_arquivo: str) -> Path:
    """Monta e valida um arquivo filho direto de uma pasta já confinada."""
    nome = validar_nome_simples(nome_arquivo, limite=120)
    pasta_real = Path(pasta).resolve(strict=True)
    arquivo = pasta_real / nome
    if _eh_link_ou_juncao(arquivo):
        raise ValueError("Links simbólicos ou junctions não são permitidos.")
    arquivo_real = _resolver(arquivo)
    if not _esta_dentro(arquivo_real, pasta_real) or arquivo_real.parent != pasta_real:
        raise ValueError("O arquivo precisa permanecer diretamente na pasta autorizada.")
    return arquivo


def _reservado_windows(nome: str) -> bool:
    base = nome.split(".", 1)[0].upper()
    return base in _RESERVADOS_WINDOWS


def _eh_link_ou_juncao(caminho: Path) -> bool:
    eh_juncao = getattr(caminho, "is_junction", lambda: False)
    return caminho.is_symlink() or eh_juncao()


def _resolver(caminho: Path) -> Path:
    try:
        return caminho.resolve(strict=False)
    except (OSError, RuntimeError):
        raise ValueError("Não foi possível validar o caminho solicitado.") from None


def _esta_dentro(caminho: Path, raiz: Path) -> bool:
    try:
        caminho.relative_to(raiz)
    except ValueError:
        return False
    return True
