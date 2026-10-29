"""Verificação conservadora de afirmações de ações concluídas."""

from __future__ import annotations

import re
from collections.abc import Iterable

from alfred.ferramentas.resultado import ResultadoFerramenta


_ACAO = re.compile(
    r"\b(criei|criou|salvei|gravei|escrevi|enviei|liguei|telefonei|acendi|"
    r"desliguei|apaguei|removi|atualizei|adicionei|agendei|marquei|consultei|"
    r"enviei|enviado|enviada|mandei|encaminhei|encaminhado|"
    r"busquei|procurei|li|lembrarei|lembro)\b|\bvou\s+lembrar\b",
    re.IGNORECASE,
)


def ferramenta_da_alegacao(frase: str) -> str | None:
    """Retorna a ferramenta que deve comprovar a alegação, ou None se ambígua."""
    texto = frase.casefold()
    if not _ACAO.search(texto):
        return ""
    regras = (
        (r"\b(e-?mail|correio eletrônico|mensagem)\b", "enviar_email"),
        (r"\b(?:vou\s+lembrar|lembrarei|lembro)\b", "lembrar_memoria"),
        (r"\b(perfil|pessoa)\b", "usar_arquivo_perfil"),
        (r"\b(arquivo|documento|nota)\b", "criar_arquivo"),
        (r"\b(lembrete)\b", "criar_lembrete"),
        (r"\b(luz|lâmpada|lampada)\b", "controlar_luz"),
        (r"\b(ligação|ligacao|telefone|contato)\b", "ligar_para"),
        (r"\b(música|musica|canção|cancao)\b", "tocar_musica"),
        (r"\b(hora|horário|horario)\b", "consultar_hora"),
    )
    encontrados = {ferramenta for padrao, ferramenta in regras if re.search(padrao, texto)}
    return encontrados.pop() if len(encontrados) == 1 else None


def alegacao_confirmada(frase: str, resultados: Iterable[ResultadoFerramenta]) -> bool:
    ferramenta_esperada = ferramenta_da_alegacao(frase)
    if ferramenta_esperada in ("", None):
        return ferramenta_esperada == ""
    return any(
        resultado.ferramenta == ferramenta_esperada and resultado.estado == "sucesso"
        for resultado in resultados
    )


def e_alegacao_de_acao(frase: str) -> bool:
    return ferramenta_da_alegacao(frase) != ""


RESPOSTA_SEM_CONFIRMACAO = "Não consigo confirmar que essa ação foi realizada."
PEDIDO_DE_REVISAO = (
    "VERIFICAÇÃO DO CÓDIGO: sua resposta anterior continha uma afirmação de ação "
    "sem resultado de ferramenta que a confirme. Responda novamente com base apenas "
    "nos resultados disponíveis; se não houver confirmação, diga isso claramente."
)
