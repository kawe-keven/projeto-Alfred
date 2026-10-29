"""Resultado tipado de ferramenta; o conteúdo é dado não confiável para o LLM."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal


EstadoResultado = Literal["sucesso", "simulacao", "falha", "cancelada"]


@dataclass(frozen=True)
class ResultadoFerramenta:
    ferramenta: str
    estado: EstadoResultado
    conteudo: str

    def para_modelo(self) -> str:
        """Serializa o resultado em envelope delimitado, escapando tags do conteúdo."""
        return (
            f'<resultado_ferramenta nome="{escape(self.ferramenta, quote=True)}" '
            f'estado="{self.estado}">\n'
            f'<dado_nao_confiavel>{escape(self.conteudo)}</dado_nao_confiavel>\n'
            "</resultado_ferramenta>"
        )
