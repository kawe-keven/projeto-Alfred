"""Classificação de riscos e limites fixos do gerador de blueprints.

LIMITES_FIXOS_BLUEPRINT é a única fonte de política para pedidos cujo objetivo
é causar dano grave. Avisos para riscos de execução são tratados separadamente.
"""

from __future__ import annotations

import re
import unicodedata


LIMITES_FIXOS_BLUEPRINT = {
    "armas_e_explosivos": {
        "padroes": (r"\b(?:criar|construir|fabricar|projetar|montar|desenvolver|produzir)\s+(?:(?:um|uma)\s+)?(?:armas?|municoes?|explosivos?|bombas?|armamento)\b", r"\bprojeto\s+(?:de\s+)?(?:armas?|municoes?|explosivos?|bombas?|armamento)\s+(?:funcional|letal|de\s+ataque|de\s+combate)\b", r"\b(?:armas?|municoes?|explosivos?|bombas?|armamento)\b.{0,25}\b(?:funcional|letal|ataque|combate)\b"),
        "alternativa": "um projeto de segurança, detecção ou treinamento sem arma funcional",
    },
    "armas_quimicas_biologicas_nucleares": {
        "padroes": (r"\b(?:arma|armas|agente|agentes)\s+(?:quimic[oa]s?|biologic[oa]s?|nuclear(?:es)?)\b", r"\btoxina(?:s)?\s+(?:para|de)\s+(?:ataque|armamento)\b"),
        "alternativa": "uma simulação educacional segura, sem agentes perigosos",
    },
    "malware_e_ataques_a_terceiros": {
        "padroes": (r"\bmalware\b", r"\bransomware\b", r"\bbotnet\b", r"\b(?:invadir|atacar|derrubar|infectar)\b.{0,50}\b(?:terceiros?|empresa|site|servidor|rede|conta)\b"),
        "alternativa": "um laboratório de segurança isolado, com alvos próprios e dados fictícios",
    },
    "vigilancia_ou_perseguicao_de_pessoas": {
        "padroes": (r"\b(?:vigiar|monitorar|perseguir|seguir|rastrear|espionar)\b.{0,50}\b(?:pessoa|pessoas|alvo|ex[- ]?parceir[oa]|funcionario|vizinho)\b", r"\b(?:vigilancia|rastreamento|localizacao)\s+(?:de|da|do)\s+(?:pessoa|pessoas|alvo|ex[- ]?parceir[oa])\b"),
        "alternativa": "um sistema de segurança consentido, voltado a equipamentos ou áreas sem identificar pessoas",
    },
}

_ALTO_RISCO = {
    "baterias de lítio": (r"\b(?:bateria|baterias|celula|pack)\b.{0,30}\b(?:litio|lipo|li-?ion)\b", r"\b(?:litio|lipo|li-?ion)\b.{0,30}\b(?:bateria|baterias|celula|pack)\b"),
    "contexto de uso militar": (r"\b(?:militar|defesa|tatico|tática)\b",),
    "eletricidade de alta tensão ou rede elétrica": (r"\b(?:alta tensao|media tensao|rede eletrica|instalacao eletrica|quadro eletrico|painel eletrico)\b",),
    "trabalho em altura": (r"\b(?:trabalho|servico|instalacao|manutencao)\b.{0,35}\b(?:altura|telhado|escada|andaime)\b",),
    "drones e aeronaves não tripuladas": (r"\b(?:drone|vant|aeronave nao tripulada)\b",),
    "estruturas e cargas": (r"\b(?:estrutura|viga|laje|ponte|mezanino|telhado|suporte estrutural)\b",),
    "produtos químicos": (r"\b(?:produto quimico|solvente|acido|base corrosiva|resina|tinta industrial)\b",),
    "máquinas e ferramentas de corte": (r"\b(?:serra|torno|fresadora|esmerilhadeira|maquina de corte|cortadora)\b",),
}
_MEDIO_RISCO = {
    "soldagem e trabalho térmico": (r"\b(?:solda|soldagem|ferro de solda|solder)\b",),
    "ferramentas manuais ou elétricas": (r"\b(?:furadeira|parafusadeira|lixadeira|ferramenta eletrica)\b",),
    "segurança ofensiva em laboratório próprio": (r"\b(?:pentest|teste de invasao|seguranca ofensiva|laboratorio de ciberseguranca)\b",),
    "eletrônica de baixa tensão": (r"\b(?:eletronica|esp32|arduino|circuito|solda)\b",),
}


def _normalizar(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in valor if not unicodedata.combining(c))


def limite_aplicavel(descricao: str) -> tuple[str, str] | None:
    """Retorna uma recusa curta e uma alternativa segura se houver limite."""
    texto = _normalizar(descricao)
    for categoria, regra in LIMITES_FIXOS_BLUEPRINT.items():
        if any(re.search(padrao, texto) for padrao in regra["padroes"]):
            return categoria, str(regra["alternativa"])
    return None


def classificar_risco(descricao: str) -> tuple[str, tuple[str, ...]]:
    """Devolve baixo/médio/alto e os fatores encontrados no pedido."""
    texto = _normalizar(descricao)
    altos = tuple(
        nome for nome, padroes in _ALTO_RISCO.items()
        if any(re.search(padrao, texto) for padrao in padroes)
    )
    if altos:
        return "alto", altos
    medios = tuple(
        nome for nome, padroes in _MEDIO_RISCO.items()
        if any(re.search(padrao, texto) for padrao in padroes)
    )
    if medios:
        return "medio", medios
    return "baixo", ()


def bloco_cuidados(nivel: str, fatores: tuple[str, ...]) -> str:
    """Bloco prático curto para incluir no documento de riscos e no resumo."""
    if nivel == "baixo":
        return ""
    fatores_texto = ", ".join(fatores) if fatores else "riscos do projeto a confirmar"
    return (
        f"> **Cuidados — risco {nivel}:** fatores identificados: {fatores_texto}. "
        "Antes de executar, faça uma análise de risco específica, selecione EPIs e "
        "proteções adequados e prepare um ambiente controlado. Não execute atividade "
        "regulada ou estrutural sem profissional habilitado; confirme licenças e regras "
        "locais vigentes."
    )

