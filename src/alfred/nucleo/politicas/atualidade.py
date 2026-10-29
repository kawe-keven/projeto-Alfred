"""Sinaliza pedidos que dependem de informação temporalmente instável."""

from __future__ import annotations

import re


_TERMOS_ATUAIS = re.compile(
    r"\b(hoje|agora|atualmente|atual|mais recente|últim[oa]s?|notícias?|"
    r"preço|preços|cotação|cotacoes|valor de|lei|legislação|regulamento|"
    r"regulamentação|taxa|clima|previsão do tempo|placar|resultado do jogo)\b",
    re.IGNORECASE,
)


def marcador_de_atualidade(texto: str, ferramentas: tuple[str, ...]) -> str:
    if not _TERMOS_ATUAIS.search(texto):
        return ""
    web = {"pesquisar_web", "buscar_web", "consultar_web", "buscar_na_internet"}
    if web.intersection(ferramentas):
        return (
            '<consulta_atualidade status="ferramenta_disponivel">'
            "Use a ferramenta de pesquisa para verificar fatos instáveis e informe a fonte."
            "</consulta_atualidade>"
        )
    return (
        '<consulta_atualidade status="sem_fonte_atual">'
        "O pedido depende de informação que pode mudar. Não há ferramenta de pesquisa externa "
        "disponível nesta sessão. Informe que não pode verificar a atualidade e não apresente "
        "conhecimento geral como dado confirmado. A data e a hora do sistema só confirmam "
        "o relógio local, não verificam notícias, preços, leis ou condições atuais."
        "</consulta_atualidade>"
    )
