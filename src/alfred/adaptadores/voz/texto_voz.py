"""Prepara textos em português brasileiro para síntese de fala."""

from __future__ import annotations

import re

from alfred.adaptadores.voz.numeros import (
    _ler_decimal,
    _ler_moeda,
    _ler_numero,
    _ordinal,
    numero_por_extenso,
)
from alfred.adaptadores.voz.pronuncias import (
    aplicar_pronuncias,
    carregar_dicionario_pronuncia,
)


_MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def _ler_url(valor: str) -> str:
    valor = re.sub(r"^https?://", "", valor, flags=re.IGNORECASE)
    substituicoes = (
        (".", " ponto "),
        ("/", " barra "),
        ("-", " hífen "),
        ("_", " sublinhado "),
        ("?", " interrogação "),
        ("=", " igual a "),
        ("&", " e "),
        ("#", " cerquilha "),
    )
    for original, falado in substituicoes:
        valor = valor.replace(original, falado)
    return re.sub(r"\s+", " ", valor).strip()


def _normalizar_url_encontrada(match: re.Match[str]) -> str:
    original = match.group(0)
    endereco = original.rstrip(".,;:!?")
    return _ler_url(endereco) + original[len(endereco) :]


def normalizar_texto_para_voz(texto: str) -> str:
    """Expande formas comuns sem alterar o conteúdo semântico da resposta."""
    texto = re.sub(
        r"https?://[^\s<>()]+",
        _normalizar_url_encontrada,
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        lambda match: match.group(0).replace("@", " arroba ").replace(".", " ponto "),
        texto,
    )
    texto = re.sub(
        r"\b([0-3]?\d)/([01]?\d)/(\d{4})\b",
        _normalizar_data_brasileira,
        texto,
    )
    texto = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", _normalizar_data_iso, texto)
    texto = re.sub(
        r"\b([01]?\d|2[0-3]):([0-5]\d)\b",
        _normalizar_horario,
        texto,
    )
    texto = re.sub(
        r"R\$\s*(\d[\d.]*)[,]?(\d{2})?\b",
        lambda match: _ler_moeda(match.group(1), match.group(2)),
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(
        r"\b(\d+(?:[.,]\d+)?)\s*%",
        lambda match: _ler_numero(match.group(1)) + " por cento",
        texto,
    )
    texto = re.sub(
        r"\b(\d+(?:[,.]\d+)?)\s*(km|kg|g|cm|mm|m|°C)\b",
        _normalizar_medida,
        texto,
        flags=re.IGNORECASE,
    )
    texto = re.sub(r"\b(\d{1,2})(?:º|ª)\b", _normalizar_ordinal, texto)
    texto = re.sub(
        r"\b(\d{1,3}(?:\.\d{3})+)(?:,(\d+))?\b",
        _normalizar_numero_milhar,
        texto,
    )
    texto = re.sub(
        r"\b(\d+)[,.](\d+)\b",
        lambda match: _ler_decimal(match.group(1), match.group(2)),
        texto,
    )
    texto = re.sub(r"\b\d+\b", lambda match: numero_por_extenso(int(match.group(0))), texto)
    texto = _normalizar_siglas(texto)
    texto = _normalizar_abreviacoes(texto)
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]{}*_#~\x60]+", " ", texto)).strip()


def _normalizar_data_brasileira(match: re.Match[str]) -> str:
    dia, mes, ano = map(int, match.groups())
    if not 1 <= mes <= 12:
        return match.group(0)
    return f"{numero_por_extenso(dia)} de {_MESES[mes - 1]} de {numero_por_extenso(ano)}"


def _normalizar_data_iso(match: re.Match[str]) -> str:
    ano, mes, dia = map(int, match.groups())
    if not 1 <= mes <= 12 or not 1 <= dia <= 31:
        return match.group(0)
    return f"{numero_por_extenso(dia)} de {_MESES[mes - 1]} de {numero_por_extenso(ano)}"


def _normalizar_horario(match: re.Match[str]) -> str:
    hora, minuto = map(int, match.groups())
    complemento = f" e {numero_por_extenso(minuto)} minutos" if minuto else ""
    return f"{numero_por_extenso(hora)} horas{complemento}"


def _normalizar_medida(match: re.Match[str]) -> str:
    unidades = {
        "km": "quilômetros",
        "kg": "quilogramas",
        "g": "gramas",
        "cm": "centímetros",
        "mm": "milímetros",
        "m": "metros",
        "°c": "graus Celsius",
    }
    numero, unidade = match.groups()
    return f"{_ler_numero(numero)} {unidades[unidade.lower()]}"


def _normalizar_ordinal(match: re.Match[str]) -> str:
    numero = int(match.group(1))
    feminino = match.group(0).endswith("ª")
    return _ordinal(numero, feminino) if numero <= 99 else numero_por_extenso(numero)


def _normalizar_numero_milhar(match: re.Match[str]) -> str:
    inteiro, fracao = match.groups()
    forma = numero_por_extenso(int(inteiro.replace(".", "")))
    if fracao:
        forma += f" vírgula {numero_por_extenso(int(fracao))}"
    return forma


def _normalizar_siglas(texto: str) -> str:
    # AI fica intacta para preservar a pronúncia inglesa prevista no perfil de voz.
    pronuncias = {
        "IA": "i a",
        "API": "a pê i",
        "GPS": "gê pê ésse",
        "URL": "u erre ele",
        "SMS": "ésse eme ésse",
    }
    return re.sub(
        r"\b(?:IA|AI|API|GPS|URL|SMS)\b",
        lambda match: pronuncias.get(match.group(0), match.group(0)),
        texto,
    )


def _normalizar_abreviacoes(texto: str) -> str:
    abreviacoes = (
        ("Dra.", "doutora"),
        ("Dr.", "doutor"),
        ("Sra.", "senhora"),
        ("Sr.", "senhor"),
    )
    for abreviacao, forma in abreviacoes:
        texto = re.sub(re.escape(abreviacao), forma, texto, flags=re.IGNORECASE)
    return texto


def dividir_primeira_frase_em_oracoes(texto: str, minimo_caracteres: int = 90) -> list[str]:
    """Divide orações longas por pontuação, sem cortar decimais."""
    if len(texto) < minimo_caracteres:
        return [texto]
    partes = re.split(r"(?<!\d)([,;—–])(?!\d)\s*", texto)
    resultado: list[str] = []
    atual = ""
    for indice, parte in enumerate(partes):
        atual += parte
        if indice % 2 and atual.strip():
            resultado.append(atual.strip())
            atual = ""
    if atual.strip():
        resultado.append(atual.strip())
    return resultado if len(resultado) > 1 else [texto]


__all__ = [
    "aplicar_pronuncias",
    "carregar_dicionario_pronuncia",
    "dividir_primeira_frase_em_oracoes",
    "normalizar_texto_para_voz",
    "numero_por_extenso",
]
