"""Atalhos conservadores de voz para intenções frequentes e não sensíveis."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from alfred.nucleo.provedor_llm import ChamadaFerramenta


_SALAS = {
    "sala": "sala",
    "quarto": "quarto",
    "cozinha": "cozinha",
    "banheiro": "banheiro",
    "escritorio": "escritório",
    "sala de estar": "sala de estar",
}
_HORA = re.compile(r"^(?:que horas sao|qual e a hora|me diz que horas sao)(?: agora)?$")
_LUZ = re.compile(r"^(acende|acenda|liga|ligue|apaga|apague|desliga|desligue) (?:a )?(?:luz|lampada) (?:da|do|de) (.+)$")
_MUSICA = re.compile(r"^(?:toca|toque|busca|procura) (?:a )?musica(?: por| chamada| para)? (.+)$")


@dataclass(frozen=True)
class RoteamentoRapido:
    chamada: ChamadaFerramenta
    categoria: str


def _normalizar(texto: str) -> str:
    sem_acentos = unicodedata.normalize("NFKD", texto.casefold())
    texto_base = "".join(c for c in sem_acentos if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto_base.strip(" \t\r\n?!.,;:"))


def resposta_saudacao(texto: str) -> str | None:
    """Responde saudações exatas sem abrir o modelo nem buscar contexto."""
    fala = re.sub(r"\s+alfred$", "", _normalizar(texto))
    if fala in {"bom dia", "boa tarde", "boa noite"}:
        saudacao = fala[0].upper() + fala[1:]
        return f"{saudacao}! Como posso ajudar?"
    if fala in {"oi", "ola", "e ai", "opa"}:
        return "Olá! Como posso ajudar?"
    return None


def rotear_comando(texto: str) -> RoteamentoRapido | None:
    """Retorna apenas chamadas com padrão exato, argumentos completos e baixa ambiguidade."""
    fala = _normalizar(texto)
    if _HORA.fullmatch(fala):
        return RoteamentoRapido(ChamadaFerramenta("consultar_hora", {}), "hora")

    luz = _LUZ.fullmatch(fala)
    if luz:
        comodo = _SALAS.get(luz.group(2))
        if comodo:
            acao = "desligar" if luz.group(1) in {"apaga", "apague", "desliga", "desligue"} else "ligar"
            return RoteamentoRapido(
                ChamadaFerramenta("controlar_luz", {"comodo": comodo, "acao": acao}),
                "luz",
            )

    musica = _MUSICA.fullmatch(fala)
    if musica:
        busca = musica.group(1).strip()
        if busca and len(busca) <= 120 and not re.search(r"\b(?:liga|telefone|arquivo|apaga)\b", busca):
            return RoteamentoRapido(
                ChamadaFerramenta("tocar_musica", {"busca": busca}),
                "musica",
            )
    return None


def resposta_curta(categoria: str, argumentos: dict[str, str], resultado: str) -> str:
    """Descreve o retorno da ferramenta sem transformar simulação em ação real."""
    if categoria == "hora":
        horario = re.search(r"\b([01]\d|2[0-3]):([0-5]\d)\b", resultado)
        if horario:
            from alfred.adaptadores.voz.texto_voz import numero_por_extenso
            hora, minuto = (int(valor) for valor in horario.groups())
            forma_hora = "uma" if hora == 1 else numero_por_extenso(hora)
            forma = f"Agora são {forma_hora} hora" + ("" if hora == 1 else "s")
            if minuto:
                forma += f" e {numero_por_extenso(minuto)} minuto" + ("" if minuto == 1 else "s")
            return forma + "."
        return "A consulta da hora local foi concluída."
    if categoria == "luz":
        comodo = argumentos["comodo"]
        verbo = "ligar" if argumentos["acao"] == "ligar" else "apagar"
        artigo = {
            "sala": "da", "sala de estar": "da", "cozinha": "da",
            "quarto": "do", "banheiro": "do", "escritório": "do",
        }.get(comodo, "da")
        return f"A solicitação para {verbo} a luz {artigo} {comodo} foi recebida em modo de simulação."
    busca = argumentos["busca"]
    return f"A busca por {busca} foi recebida em modo de simulação."
