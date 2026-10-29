"""Conversão de números e valores comuns para português falado."""

from __future__ import annotations

import re


_UNIDADES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove")
_DEZ_A_DEZENOVE = (
    "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis",
    "dezessete", "dezoito", "dezenove",
)
_DEZENAS = (
    "", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta",
    "setenta", "oitenta", "noventa",
)
_CENTENAS = (
    "", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
    "seiscentos", "setecentos", "oitocentos", "novecentos",
)
_ORDINAIS_MASC = (
    "", "primeiro", "segundo", "terceiro", "quarto", "quinto", "sexto",
    "sétimo", "oitavo", "nono", "décimo",
)
_ORDINAIS_FEM = (
    "", "primeira", "segunda", "terceira", "quarta", "quinta", "sexta",
    "sétima", "oitava", "nona", "décima",
)
_DEZENAS_ORDINAIS = {
    20: ("vigésima", "vigésimo"),
    30: ("trigésima", "trigésimo"),
    40: ("quadragésima", "quadragésimo"),
    50: ("quinquagésima", "quinquagésimo"),
    60: ("sexagésima", "sexagésimo"),
    70: ("septuagésima", "septuagésimo"),
    80: ("octogésima", "octogésimo"),
    90: ("nonagésima", "nonagésimo"),
}


def _ate_999(numero: int) -> str:
    if numero < 10:
        return _UNIDADES[numero]
    if numero < 20:
        return _DEZ_A_DEZENOVE[numero - 10]
    if numero < 100:
        dezena, unidade = divmod(numero, 10)
        complemento = f" e {_UNIDADES[unidade]}" if unidade else ""
        return _DEZENAS[dezena] + complemento
    if numero == 100:
        return "cem"
    centena, resto = divmod(numero, 100)
    complemento = f" e {_ate_999(resto)}" if resto else ""
    return _CENTENAS[centena] + complemento


def numero_por_extenso(numero: int) -> str:
    """Escreve um número inteiro em português brasileiro."""
    if numero < 0:
        return "menos " + numero_por_extenso(-numero)
    if numero < 1000:
        return _ate_999(numero)
    if numero < 1_000_000:
        milhares, resto = divmod(numero, 1000)
        prefixo = "mil" if milhares == 1 else _ate_999(milhares) + " mil"
        return prefixo + _ligacao_numero(resto) + (_ate_999(resto) if resto else "")
    if numero < 1_000_000_000:
        milhoes, resto = divmod(numero, 1_000_000)
        prefixo = "um milhão" if milhoes == 1 else numero_por_extenso(milhoes) + " milhões"
        return prefixo + _ligacao_numero(resto) + (numero_por_extenso(resto) if resto else "")
    return " ".join(_UNIDADES[int(digito)] for digito in str(numero))


def _ligacao_numero(resto: int) -> str:
    if not resto:
        return ""
    return " e " if resto < 100 or resto % 100 == 0 else " "


def _ler_decimal(inteiro: str, fracao: str) -> str:
    parte_inteira = numero_por_extenso(int(inteiro or "0"))
    parte_fracionaria = numero_por_extenso(int(fracao))
    return f"{parte_inteira} vírgula {parte_fracionaria}"


def _ordinal(numero: int, feminino: bool) -> str:
    unidades = _ORDINAIS_FEM if feminino else _ORDINAIS_MASC
    if numero <= 10:
        return unidades[numero]
    if numero < 20:
        base = "décima" if feminino else "décimo"
        return base + " " + unidades[numero - 10]
    dezena, unidade = divmod(numero, 10)
    if dezena * 10 in _DEZENAS_ORDINAIS and unidade:
        forma = _DEZENAS_ORDINAIS[dezena * 10][0 if feminino else 1]
        return forma + " " + unidades[unidade]
    if numero in _DEZENAS_ORDINAIS:
        return _DEZENAS_ORDINAIS[numero][0 if feminino else 1]
    return numero_por_extenso(numero)


def _ler_numero(texto: str) -> str:
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", texto):
        inteiro, _, fracao = texto.partition(",")
        forma = numero_por_extenso(int(inteiro.replace(".", "")))
        return forma + (f" vírgula {numero_por_extenso(int(fracao))}" if fracao else "")
    separador = "," if "," in texto else "."
    if separador in texto:
        inteiro, fracao = texto.split(separador, 1)
        return _ler_decimal(inteiro, fracao)
    return numero_por_extenso(int(texto))


def _ler_moeda(inteiro: str, centavos: str | None) -> str:
    numero = int(inteiro.replace(".", ""))
    reais = numero_por_extenso(numero) + (" real" if numero == 1 else " reais")
    if centavos and int(centavos):
        cents = int(centavos)
        unidade = " centavo" if cents == 1 else " centavos"
        reais += " e " + numero_por_extenso(cents) + unidade
    return reais
