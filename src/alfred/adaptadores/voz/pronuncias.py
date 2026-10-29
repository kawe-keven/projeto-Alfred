"""Carregamento e aplicação de pronúncias personalizadas para síntese de voz."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path


def carregar_dicionario_pronuncia(
    caminho_publico: Path | None = None,
    caminho_pessoal: Path | None = None,
) -> dict[str, str]:
    """Carrega pronúncias do pacote e, em execução, as pessoais do usuário."""
    raiz_pacote = Path(__file__).resolve().parents[2]
    raiz_projeto = Path(__file__).resolve().parents[4]
    caminhos = (
        caminho_publico or raiz_pacote / "configuracao" / "pronuncias.toml",
        caminho_pessoal or raiz_projeto / "dados" / "perfil" / "pronuncias_pessoais.toml",
    )
    resultado: dict[str, str] = {}
    for caminho in caminhos:
        termos = _ler_termos(caminho)
        resultado.update(termos)
    return resultado


def _ler_termos(caminho: Path) -> dict[str, str]:
    if not caminho.is_file():
        return {}
    try:
        with caminho.open("rb") as arquivo:
            documento = tomllib.load(arquivo)
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError("Arquivo de pronúncias inválido; confira o formato TOML.") from None

    termos = documento.get("termos", {})
    if not isinstance(termos, dict) or any(
        not isinstance(origem, str) or not origem.strip()
        or not isinstance(destino, str) or not destino.strip()
        for origem, destino in termos.items()
    ):
        raise ValueError("As pronúncias devem mapear termos para formas faláveis não vazias.")
    return termos


def aplicar_pronuncias(texto: str, dicionario: Mapping[str, str]) -> str:
    """Aplica respellings para a síntese sem alterar o texto original."""
    for termo in sorted(dicionario, key=len, reverse=True):
        substituto = dicionario[termo]
        texto = re.sub(
            rf"(?<!\w){re.escape(termo)}(?!\w)",
            lambda _match, forma=substituto: forma,
            texto,
            flags=re.IGNORECASE,
        )
    return texto
