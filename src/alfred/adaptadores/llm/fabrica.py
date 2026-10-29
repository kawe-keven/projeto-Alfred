"""Cria o provedor de linguagem selecionado na configuração local."""

from alfred.adaptadores.llm.colibri import ProvedorColibri
from alfred.adaptadores.llm.ollama import ProvedorOllama


def criar_provedor(config, *, voz: bool = False):
    if config.provedor_llm == "colibri":
        return ProvedorColibri(
            modelo=config.modelo,
            url_base=config.url_llm,
            timeout=config.tempo_limite_s,
            max_tokens=config.voz_num_predict if voz else 512,
            temperatura=config.voz_temperatura if voz else 0.8,
        )
    if voz:
        return ProvedorOllama(
            config.modelo,
            config.url_llm,
            config.tempo_limite_s,
            keep_alive=config.voz_ollama_keep_alive,
            num_ctx=config.voz_num_ctx,
            num_predict=config.voz_num_predict,
            temperatura=config.voz_temperatura,
        )
    return ProvedorOllama(
        modelo=config.modelo,
        url_base=config.url_llm,
        timeout=config.tempo_limite_s,
    )
