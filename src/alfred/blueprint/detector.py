"""Detecção conservadora de pedidos de criação de projetos."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


_PADROES_INTENCAO = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(?:crie|cria|criar|monte|monta|montar|desenvolva|desenvolver|planeje|planejar)\s+(?:um\s+|uma\s+)?(?:novo\s+|nova\s+)?projeto\b",
    r"\b(?:quero|preciso|vamos)\s+(?:criar|montar|desenvolver|planejar|construir)\b",
    r"\b(?:faz|faca|fazer|gere|gerar)\s+(?:o\s+|um\s+|uma\s+)?blueprint\b",
    r"\bblueprint\s+(?:de|para)\s+(?:um\s+|uma\s+)?projeto\b",
    r"\bestou\s+(?:criando|montando|desenvolvendo)\s+(?:um\s+|uma\s+)?projeto\b",
))
_PEDIDO_EXIBIR_BLUEPRINT = re.compile(
    r"\b(?:mostre|mostra|mostrar|exiba|exibir|apresente|abrir|abra|ver|visualizar)\b"
    r".{0,80}\b(?:blueprint|plano do projeto|projeto)\b|"
    r"\bblueprint\b.{0,60}\b(?:desse|deste|do|da)\s+projeto\b",
    re.IGNORECASE,
)

_DIGITAL = re.compile(
    r"\b(?:app|aplicativo|aplicacao|software|sistema|site|web|api|plataforma|"
    r"banco de dados|saas|jogo digital|mobile|android|ios|inteligencia artificial)\b",
    re.IGNORECASE,
)
_FISICO = re.compile(
    r"\b(?:fisico|hardware|maquina|dispositivo|estrutura|construcao|casa|movel|moveis|"
    r"drone|robo|robotica|circuito|eletronica|iot|esp32|arduino|sensor|placa|"
    r"instalacao eletrica|painel solar|produto|equipamento|oficina|impressao 3d)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PedidoProjeto:
    """Intenção detectada e descrição a encaminhar ao gerador."""

    descricao: str
    tipo: str


def _normalizar(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in valor if not unicodedata.combining(c))


def classificar_tipo(descricao: str) -> str:
    """Classifica o projeto como digital, físico ou híbrido."""
    texto = _normalizar(descricao)
    digital = bool(_DIGITAL.search(texto))
    fisico = bool(_FISICO.search(texto))
    if digital and fisico:
        return "hibrido"
    if fisico:
        return "fisico"
    return "digital"


def detectar_pedido(texto: str) -> PedidoProjeto | None:
    """Retorna None para conversa geral e o projeto para pedidos de criação."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    texto_limpo = texto.strip()
    correspondencia = next(
        (resultado for padrao in _PADROES_INTENCAO
         if (resultado := padrao.search(texto_limpo))),
        None,
    )
    if correspondencia is None:
        return None
    descricao = texto_limpo[correspondencia.start():].strip(" .,!?:;")
    return PedidoProjeto(descricao=descricao or texto_limpo, tipo=classificar_tipo(texto_limpo))


def eh_pedido_exibir_blueprint(texto: str) -> bool:
    """Reconhece pedidos de exibição do projeto já em contexto."""
    return isinstance(texto, str) and bool(_PEDIDO_EXIBIR_BLUEPRINT.search(texto))


def extrair_nome_projeto(descricao: str) -> str:
    """Obtém rótulo inicial simples; o slug final é validado pelo gerador."""
    nome = descricao.strip()
    nome = re.sub(
        r"^(?:alfred[, ]+)?(?:crie|cria|criar|monte|monta|montar|desenvolva|desenvolver|"
        r"planeje|planejar|construa|construir|gere|gerar)\s+",
        "", nome, flags=re.IGNORECASE,
    )
    for padrao in _PADROES_INTENCAO:
        correspondencia = padrao.search(nome)
        if correspondencia:
            nome = nome[correspondencia.end():].strip(" .,!?:;")
            break
    nome = re.sub(
        r"^(?:(?:de|do|da|dos|das|um|uma|o|a|os|as|novo|nova)\s+)+",
        "", nome, flags=re.IGNORECASE,
    )
    nome = re.split(r"\b(?:com|usando|porque|pois|que|incluindo|considerando)\b", nome, maxsplit=1, flags=re.IGNORECASE)[0]
    palavras = [palavra for palavra in re.findall(r"[\w]+", nome, re.UNICODE) if len(palavra) > 1]
    return " ".join(palavras[:6]) or "projeto"

