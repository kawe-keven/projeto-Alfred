"""Ponto de entrada para o ciclo de voz local."""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
from datetime import datetime
import sys
from threading import Event, Thread
from time import monotonic
from urllib.parse import urlparse

from alfred.adaptadores.llm.fabrica import criar_provedor
from alfred.adaptadores.voz.captura_audio import CapturaAudio
from alfred.adaptadores.voz.palavra_de_ativacao import DetectorOpenWakeWord
from alfred.adaptadores.voz.stt import TranscritorLocal
from alfred.adaptadores.voz.tts import SintetizadorPiper
from alfred.adaptadores.voz.texto_voz import carregar_dicionario_pronuncia
from alfred.adaptadores.voz.tts_voicestudio import SintetizadorVoiceStudio
from alfred.adaptadores.voz.vad import DetectorDeVoz
from alfred.configuracao.configuracao import carregar_configuracao
from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz
from alfred.memoria.perfil.carregador import carregar_perfil
from alfred.memoria.perfil.montador_prompt import montar_prompt_sistema
from alfred.memoria.perfil.pessoas import RepositorioDePessoas, carregar_pessoas_mencionadas, montar_bloco_pessoas
from alfred.memoria.armazenamento.rag import criar_rag
from alfred.nucleo.politicas.fontes import (
    eh_pergunta_de_historico,
    resultado_busca_historico,
)
from alfred.nucleo.agente.agente import Agente


def _executar_com_progresso(etapa: str, acao, *, intervalo_s: float = 10.0) -> float:
    """Mostra avanço de cargas bloqueantes sem registrar dados da conversa."""
    inicio = monotonic()
    parar = Event()
    print(f"[voz] Iniciando: {etapa}.")

    def informar_espera() -> None:
        while not parar.wait(intervalo_s):
            decorrido = monotonic() - inicio
            print(f"[voz] Ainda carregando {etapa} ({decorrido:.0f}s).")

    informante = Thread(target=informar_espera, name="alfred-progresso-inicializacao", daemon=True)
    informante.start()
    try:
        acao()
    except Exception:
        parar.set()
        informante.join(timeout=1)
        decorrido = monotonic() - inicio
        print(f"[voz] Falha ao carregar {etapa} ({decorrido:.1f}s).")
        raise
    parar.set()
    informante.join(timeout=1)
    decorrido = monotonic() - inicio
    print(f"[voz] Pronto: {etapa} ({decorrido:.1f}s).")
    return decorrido


def montar_contexto_memoria(rag, texto: str) -> str:
    """Recupera conversas e declara resultado vazio ou indisponibilidade na voz."""
    if rag is None:
        return ""
    if eh_pergunta_de_historico(texto):
        buscar_historico = getattr(rag, "recuperar_conversas_recentes", None)
        contexto = (
            buscar_historico(texto)
            if callable(buscar_historico)
            else rag.recuperar(texto)
        )
    else:
        contexto = rag.recuperar(texto)
    partes = [contexto] if contexto else []
    if eh_pergunta_de_historico(texto):
        marcador = resultado_busca_historico(
            disponivel=(
                rag is not None
                and getattr(rag, "ultima_busca_disponivel", True)
            ),
            encontrado=bool(contexto),
        )
        if marcador:
            partes.append(marcador)
    return "\n\n".join(partes)


def registrar_turno_memoria(rag, sessao_id: str | None, usuario: str, alfred: str) -> None:
    """Registra a fala concluída sem propagar falhas de persistência à voz."""
    if rag is not None and sessao_id is not None:
        rag.registrar_turno(usuario, alfred, sessao_id)


def criar_orquestrador(
    *, modo: str | None = None, debug: bool | None = None, aquecer_modelo: bool = False
) -> OrquestradorDeVoz:
    config = carregar_configuracao()
    endereco = urlparse(config.ollama_url)
    if endereco.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("A voz aceita apenas um provedor local na própria máquina")
    perfil = carregar_perfil(config.pasta_perfil)
    prompt_base = Path(__file__).resolve().parents[4] / "prompts" / "system.txt"
    prompt_personalizado = prompt_base.read_text(encoding="utf-8").strip() if prompt_base.is_file() else ""
    sistema = "\n\n".join(parte for parte in (
        prompt_personalizado, montar_prompt_sistema(perfil, datetime.now().astimezone())
    ) if parte)
    provedor = criar_provedor(config, voz=True)
    rag = criar_rag(
        config,
        interface="voz",
        interativo_disponivel=sys.stdin.isatty(),
    )
    id_sessao = rag.iniciar_sessao(config.modelo) if rag is not None else None

    def montar_contexto(texto: str) -> str:
        partes = [montar_bloco_pessoas(
            carregar_pessoas_mencionadas(
                texto,
                RepositorioDePessoas(
                    config.pasta_pessoas,
                    limite_pessoas=config.pessoas_limite_total,
                    limite_palavras=config.pessoa_limite_palavras,
                ),
                maximo=3,
            )
        )]
        contexto = montar_contexto_memoria(rag, texto)
        if contexto:
            partes.append(contexto)
        return "\n\n".join(parte for parte in partes if parte)

    agente = Agente(provedor, sistema, limite_interacoes=config.voz_limite_historico,
                    registro=RegistroDeFerramentas(memoria=rag, provedor=provedor),
                    modo_voz=True,
                    depuracao=config.voz_debug if debug is None else debug,
                    contexto_por_mensagem=montar_contexto,
                    registrar_conversa=(
                        lambda usuario, alfred: registrar_turno_memoria(
                            rag, id_sessao, usuario, alfred
                        )
                    ))
    import asyncio
    # Limita o atraso se o event loop ficar sobrecarregado: frames antigos
    # não podem acumular indefinidamente enquanto o microfone segue capturando.
    fila = asyncio.Queue(maxsize=16)
    bloco = round(config.voz_taxa_amostragem * config.voz_bloco_ms / 1000)
    captura = CapturaAudio(fila, config.voz_taxa_amostragem, bloco)
    ativacao = DetectorOpenWakeWord(config.voz_modelo_ativacao, palavra_desejada=config.voz_palavra_ativacao)
    duracao_frame_ms = bloco / config.voz_taxa_amostragem * 1000
    vad = DetectorDeVoz(
        config.voz_limiar_vad_inicio, config.voz_limiar_vad_fim,
        silencio_fim=max(1, round(config.voz_vad_silencio_completo_ms / duracao_frame_ms)),
        silencio_fim_hesitacao=max(1, round(config.voz_vad_silencio_hesitacao_ms / duracao_frame_ms)),
        limiar_interrupcao=config.voz_vad_limiar_interrupcao,
        frames_minimos_interrupcao=max(1, round(config.voz_vad_interrupcao_minima_ms / duracao_frame_ms)),
    )
    repositorio_pessoas = RepositorioDePessoas(
        config.pasta_pessoas,
        limite_pessoas=config.pessoas_limite_total,
        limite_palavras=config.pessoa_limite_palavras,
    )
    vocabulario_stt = tuple(
        termo
        for pessoa in repositorio_pessoas.listar_indice()
        for termo in (pessoa.nome_exibicao, *pessoa.apelidos)
    ) + config.voz_vocabulario_stt
    stt = TranscritorLocal(
        config.voz_modelo_stt, config.voz_dispositivo_stt, config.voz_compute_type,
        config.voz_perfil_stt, vocabulario_stt, engine=config.voz_engine_stt,
    )
    pronuncias = carregar_dicionario_pronuncia()
    piper = (
        SintetizadorPiper(
            str(config.voz_caminho_modelo_voz),
            length_scale=config.voz_piper_length_scale,
            pronuncias=pronuncias,
        )
        if config.tts_fallback == "piper" else None
    )
    tts = SintetizadorVoiceStudio(
        config.voicestudio_url,
        config.voicestudio_motor,
        config.voicestudio_voz,
        formato=config.voicestudio_formato,
        taxa_amostragem=config.voicestudio_taxa_amostragem,
        timeout_conexao_s=config.voicestudio_timeout_conexao_s,
        timeout_leitura_s=config.voicestudio_timeout_leitura_s,
        fallback=config.tts_fallback,
        sintetizador_fallback=piper,
        pronuncias=pronuncias,
        velocidade=config.voicestudio_velocidade,
        seed=config.voicestudio_estabilidade_seed,
        estilo=config.voicestudio_estilo,
    )
    print("Preparando os modelos locais. Na primeira execução, alguns podem ser baixados.")
    nome_tts = f"perfil VoiceStudio do Alfred ({config.voicestudio_voz}; Piper Faber como fallback)"
    preparacoes = (
        (f"transcrição {config.voz_engine_stt} v3", stt.carregar),
        ("detecção de fala Silero VAD", vad.carregar),
        (nome_tts, tts.carregar),
    )
    with ThreadPoolExecutor(max_workers=len(preparacoes), thread_name_prefix="alfred-modelo") as executor:
        tarefas = [
            executor.submit(_executar_com_progresso, etapa, carregar)
            for etapa, carregar in preparacoes
        ]
        for tarefa in tarefas:
            tarefa.result()
    if aquecer_modelo:
        _executar_com_progresso(
            f"modelo de conversa Ollama ({config.modelo})",
            lambda: provedor.aquecer(agente.sistema),
        )
    else:
        print("[voz] Aquecimento inicial do Ollama ignorado; a primeira resposta pode demorar mais.")
    print("Modelos prontos.")
    return OrquestradorDeVoz(
        captura, vad, stt, tts,
        agente, ativacao=ativacao, modo=modo or config.voz_modo,
        interromper_com_palavra=config.voz_interromper_com_palavra,
        debug=config.voz_debug if debug is None else debug,
        debug_dir=config.voz_debug_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Conversa por voz local com Alfred")
    parser.add_argument(
        "--modo", choices=("apertar", "palavra", "conversa"),
        help="push-to-talk, palavra de ativação ou conversa contínua",
    )
    parser.add_argument("--debug", action="store_true", default=None, help="mostra e salva áudio/transcrições para avaliar o STT")
    grupo_aquecimento = parser.add_mutually_exclusive_group()
    grupo_aquecimento.add_argument(
        "--aquecer-modelo", dest="aquecer_modelo", action="store_true",
        help="carrega o Ollama antes de iniciar a escuta (pode demorar)",
    )
    grupo_aquecimento.add_argument(
        "--sem-aquecimento", dest="aquecer_modelo", action="store_false",
        help="inicia a escuta sem esperar o Ollama carregar",
    )
    parser.set_defaults(aquecer_modelo=False)
    argumentos = parser.parse_args()
    handler = None
    voz_log = None
    try:
        config = carregar_configuracao()
        caminho_logs = config.pasta_perfil.parent / "logs" / "voz.log"
        caminho_logs.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(caminho_logs, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        voz_log = logging.getLogger("alfred.voz")
        voz_log.setLevel(logging.INFO)
        voz_log.addHandler(handler)
        orquestrador = criar_orquestrador(
            modo=argumentos.modo,
            debug=argumentos.debug,
            aquecer_modelo=argumentos.aquecer_modelo,
        )
        if orquestrador.modo not in {"apertar", "palavra", "conversa"}:
            raise ValueError("ALFRED_VOZ_MODO deve ser 'apertar', 'palavra' ou 'conversa'")
        asyncio.run(orquestrador.executar())
    except KeyboardInterrupt:
        print("Alfred encerrado.")
        return 0
    except Exception as erro:
        # Mensagens operacionais sem texto da conversa ou argumentos do modelo.
        print(f"Não foi possível iniciar a voz do Alfred: {erro}")
        return 1
    finally:
        if handler is not None and voz_log is not None:
            voz_log.removeHandler(handler)
            handler.close()
    return 0
