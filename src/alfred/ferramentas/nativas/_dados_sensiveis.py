"""Recusa segredos e identificadores pessoais de alto risco em fatos."""

from __future__ import annotations

import re

_ROTULO_SENSIVEL = re.compile(
    r"\b(?:cpf|rg|cnh|passaporte|senha|password|token|"
    r"c[oó]digo\s+de\s+(?:verifica[cç][aã]o|seguran[cç]a)|"
    r"documento\s+de\s+identidade|cart[aã]o\s+de\s+cr[eé]dito)\b",
    re.IGNORECASE,
)
_CONTA_BANCARIA = re.compile(
    r"\b(?:conta\s+(?:banc[aá]ria|corrente|poupan[cç]a)|ag[eê]ncia)\b.{0,40}\d{3,}",
    re.IGNORECASE,
)
_SEQUENCIA_DIGITOS = re.compile(r"(?<!\d)(?:\d[\s-]?){12,18}\d(?!\d)")


def contem_dado_de_alto_risco(texto: str) -> bool:
    if _ROTULO_SENSIVEL.search(texto) or _CONTA_BANCARIA.search(texto):
        return True
    return any(_luhn_valido(match.group()) for match in _SEQUENCIA_DIGITOS.finditer(texto))


def _luhn_valido(texto: str) -> bool:
    digitos = [int(caractere) for caractere in texto if caractere.isdigit()]
    if not 13 <= len(digitos) <= 19:
        return False
    soma = 0
    paridade = len(digitos) % 2
    for indice, digito in enumerate(digitos):
        if indice % 2 == paridade:
            digito *= 2
            if digito > 9:
                digito -= 9
        soma += digito
    return soma % 10 == 0
