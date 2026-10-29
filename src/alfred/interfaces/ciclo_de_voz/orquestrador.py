"""Orquestra captura, VAD, transcrição, agente e reprodução."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import wave
from collections import deque
from enum import StrEnum
from pathlib import Path
from typing import Any

from alfred.adaptadores.voz.vad import DetectorDeVoz
from alfred.adaptadores.voz.stt import normalizar_transcricao_pt_br
from alfred.adaptadores.voz.palavra_de_ativacao import DetectorDePalavraDeAtivacao
from alfred.nucleo.agente.agente import Agente
from alfred.nucleo.agente.streaming import DivisorDeFrases as DivisorDeFrases
from alfred.nucleo.saudacao import saudacao_por_horario

log = logging.getLogger("alfred.voz")
PAUSA_ENTRE_FRASES_S = 0.22
DURACAO_MAXIMA_FALA_S = 120.0

__all__ = ["EstadoVoz", "OrquestradorDeVoz", "DivisorDeFrases"]


class EstadoVoz(StrEnum):
    OCIOSO = "ocioso"
    OUVINDO = "ouvindo"
    TRANSCREVENDO = "transcrevendo"
    PENSANDO = "pensando"
    FALANDO = "falando"


class OrquestradorDeVoz:
    def __init__(self, captura: Any, vad: DetectorDeVoz, stt: Any, tts: Any,
                 agente: Agente, *, ativacao: DetectorDePalavraDeAtivacao | None = None,
                 modo: str = "apertar", interromper_com_palavra: bool = False,
                 debug: bool = False, limiar_confianca: float = 0.35,
                 debug_dir: Path | None = None) -> None:
        self.captura, self.vad, self.stt, self.tts, self.agente = captura, vad, stt, tts, agente
        self.ativacao, self.modo = ativacao, modo
        self.interromper_com_palavra, self.debug = interromper_com_palavra, debug
        self.debug_dir = debug_dir or Path("dados/debug_voz")
        self.limiar_confianca = limiar_confianca
        self.estado = EstadoVoz.OCIOSO
        self.mudo = False
        self._apertado = False
        self._aguardando_confirmacao = False
        # Preserva a fala completa para o STT; o turno é encerrado em 120 s
        # para manter este buffer limitado sem truncar silenciosamente.
        self._frames_fala: deque[Any] = deque()
        self._turnos: asyncio.Queue[tuple[Any, float] | None] = asyncio.Queue(maxsize=2)
        self._tempos: dict[str, list[float]] = {k: [] for k in ("primeira_palavra", "transcricao", "primeiro_token", "primeira_frase", "primeiro_audio")}
        self._marco_fim_fala = 0.0
        self._marco_inicio_fala = 0.0
        self._audio_medida = False
        self._cancelamento_stream_ativo: threading.Event | None = None
        # Mantém alguns frames recentes para não cortar o início da fala que
        # interrompe o Alfred. O buffer não é usado como áudio de conversa normal.
        self._frames_recentes: deque[Any] = deque(maxlen=6)
        caminho_estado = os.getenv("ALFRED_VOZ_ESTADO_ARQUIVO")
        self._arquivo_estado = Path(caminho_estado) if caminho_estado else None

    def mostrar_estado(self, estado: EstadoVoz) -> None:
        self.estado = estado
        log.info("estado=%s", estado.value)
        if self._arquivo_estado is not None:
            try:
                temporario = self._arquivo_estado.with_suffix(".tmp")
                temporario.write_text(estado.value, encoding="utf-8")
                temporario.replace(self._arquivo_estado)
            except OSError:
                log.debug("Não foi possível atualizar o estado visual da voz.")
        print(f"[Alfred: microfone {estado.value}]")

    def ativar_manual(self) -> None:
        if self.mudo:
            print("Microfone silenciado; pressione m para reativar antes de falar.")
            return
        self.vad.resetar()
        self._frames_fala.clear()
        self._frames_recentes.clear()
        self._apertado = True
        if hasattr(self.ativacao, "ativar"):
            self.ativacao.ativar()
        log.info("push_to_talk=ativado")
        self.mostrar_estado(EstadoVoz.OUVINDO)
        print("Pode falar agora.")

    async def executar(self) -> None:
        if self.debug:
            print(f"AVISO: --debug exibe transcrições no console e salva áudio/transcrições em {self.debug_dir}.")
        try:
            await self.captura.iniciar()
        except Exception as erro:
            log.error("falha etapa=captura codigo=%s", type(erro).__name__)
            await self._falar_texto("Não consegui acessar o microfone. Confira a conexão e as permissões.")
            await self.captura.fechar()
            self.tts.fechar()
            return
        await self._falar_texto(saudacao_por_horario())
        captura = asyncio.create_task(self._capturar_com_tratamento(), name="alfred-captura")
        teclado = asyncio.create_task(self._ler_teclado(), name="alfred-teclado")
        try:
            while True:
                turno = await self._turnos.get()
                if turno is None:
                    await self._falar_texto("A escuta foi interrompida. Confira o microfone e o modelo de ativação.")
                    break
                amostras, fim = turno
                if self.mudo:
                    continue
                self._tarefa_turno = asyncio.create_task(self._processar(amostras, fim))
                try:
                    await self._tarefa_turno
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            for tarefa in (captura, teclado):
                tarefa.cancel()
            if hasattr(self, "_tarefa_turno"):
                self._tarefa_turno.cancel()
            self.tts.parar()
            await self.captura.fechar()
            self.tts.fechar()
            self._resumo_tempos()

    async def _capturar_com_tratamento(self) -> None:
        try:
            await self._ler_microfone()
        except asyncio.CancelledError:
            raise
        except Exception as erro:
            log.error("falha etapa=escuta codigo=%s", type(erro).__name__)
            try:
                self._turnos.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    self._turnos.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._turnos.put_nowait(None)

    async def _ler_microfone(self) -> None:
        self.mostrar_estado(EstadoVoz.OCIOSO)
        if self.modo == "apertar":
            print("Pressione espaço para falar; m alterna o mudo.")
        elif self.modo == "conversa":
            print("Conversa contínua ativa; fale naturalmente. Pressione m para silenciar.")
        else:
            nome_modelo = getattr(self.ativacao, "modelo_nome", "modelo personalizado")
            nome_desejado = getattr(self.ativacao, "palavra_desejada", "Alfred")
            print(f"Ouvindo a ativação: modelo {nome_modelo}; palavra desejada: {nome_desejado}.")
        async for frame in self.captura.frames():
            if self.mudo:
                continue
            self._frames_recentes.append(frame)
            if self.estado == EstadoVoz.FALANDO:
                # No push-to-talk, só interrompa a reprodução depois que a
                # pessoa pedir a vez com espaço; o VAD sozinho confundia eco
                # da própria voz com uma interrupção e cortava palavras.
                if self.modo == "apertar" and not self._apertado:
                    continue
                reconheceu = False
                if self.interromper_com_palavra:
                    if self.ativacao and await asyncio.to_thread(self.ativacao.detectar, frame):
                        reconheceu = True
                else:
                    acao, _ = await asyncio.to_thread(self.vad.processar, frame, durante_fala=True)
                    if acao == "interromper":
                        reconheceu = True
                if reconheceu:
                    self.tts.parar()
                    if hasattr(self, "_tarefa_turno"):
                        self._tarefa_turno.cancel()
                    self._frames_fala = deque(self._frames_recentes)
                    self._apertado = True
                    self._marco_inicio_fala = time.perf_counter()
                    if hasattr(self.vad, "registrar_interrupcao"):
                        self.vad.registrar_interrupcao(frame)
                        self.mostrar_estado(EstadoVoz.OUVINDO)
                        continue
                    self.vad.resetar()
                    self.mostrar_estado(EstadoVoz.OUVINDO)
                else:
                    continue
            if self.modo == "apertar" and not self._apertado:
                continue
            if self.modo == "palavra":
                if not self._apertado and self.ativacao and await asyncio.to_thread(self.ativacao.detectar, frame):
                    self._apertado = True
                    print("Palavra de ativação detectada.")
                if not self._apertado:
                    continue
            if hasattr(self.vad, "silencio_frames"):
                evento, trecho = await asyncio.to_thread(self.vad.processar, frame)
            else:
                evento, trecho = await asyncio.to_thread(self.vad.processar, frame)
            if evento == "inicio":
                self._marco_inicio_fala = time.perf_counter()
                tarefa_turno = getattr(self, "_tarefa_turno", None)
                if (
                    not self._aguardando_confirmacao
                    and tarefa_turno is not None
                    and not tarefa_turno.done()
                ):
                    # Um novo começo de fala substitui o processamento anterior,
                    # inclusive se ele ainda estiver em STT ou aguardando o LLM.
                    self.tts.parar()
                    tarefa_turno.cancel()
                # Inclui o pequeno pré-buffer da captura: o VAD só reconhece
                # a fala depois do primeiro som, então usar apenas este frame
                # costuma cortar consoantes iniciais de fala baixa ou rápida.
                self._frames_fala = deque(self._frames_recentes)
                self.mostrar_estado(EstadoVoz.OUVINDO)
            elif evento == "continuar" and self._frames_fala:
                if time.perf_counter() - self._marco_inicio_fala >= DURACAO_MAXIMA_FALA_S:
                    evento = "fim"
                    log.warning("fala_maxima_encerrada segundos=%.0f", DURACAO_MAXIMA_FALA_S)
                else:
                    self._frames_fala.append(frame)
                    continue
            if evento == "fim" and self._frames_fala:
                import numpy as np
                self._frames_fala.append(frame)
                audio = np.concatenate(self._frames_fala)
                self._frames_fala.clear()
                self.vad.resetar()
                self._apertado = False
                inicio = time.perf_counter()
                self._marco_fim_fala = inicio
                self._audio_medida = False
                log.info("marco etapa=fim_fala")
                if self._turnos.full():
                    try: self._turnos.get_nowait()
                    except asyncio.QueueEmpty: pass
                self._turnos.put_nowait((audio, inicio))

    async def _processar(self, audio: Any, fim_fala: float) -> None:
        self.mostrar_estado(EstadoVoz.TRANSCREVENDO)
        try:
            transcricao = await asyncio.to_thread(self.stt.transcrever, audio)
        except Exception as erro:
            if self.debug:
                await asyncio.to_thread(self._salvar_debug, audio, "")
            log.error("falha etapa=stt codigo=%s", type(erro).__name__)
            await self._falar_texto("Não consegui entender. Pode repetir, por favor?")
            return
        resultado_transcricao = "transcrito" if transcricao.texto.strip() else "sem_fala"
        self._registrar_conversa("escutado", transcricao.texto, resultado_transcricao)
        log.info("stt_confianca valor=%.3f", transcricao.confianca)
        if transcricao.texto.strip() and self._marco_inicio_fala:
            self._tempos["primeira_palavra"].append(time.perf_counter() - self._marco_inicio_fala)
        delta_transcricao = time.perf_counter() - fim_fala
        self._tempos["transcricao"].append(delta_transcricao)
        log.info("medicao etapa=transcricao ms=%.0f", delta_transcricao * 1000)
        if self.debug:
            await asyncio.to_thread(self._salvar_debug, audio, transcricao.texto)
        if not transcricao.texto.strip() or transcricao.confianca < self.limiar_confianca:
            await self._falar_texto("Não entendi bem. Pode repetir, por favor?")
            return
        texto_normalizado = normalizar_transcricao_pt_br(transcricao.texto)
        if self.debug:
            print(f"[DEBUG transcrição] {transcricao.texto}")
        if texto_normalizado.casefold() == "/mudo":
            self.mudo = True
            self.mostrar_estado(EstadoVoz.OCIOSO)
            return
        self.mostrar_estado(EstadoVoz.PENSANDO)
        fila_audio: asyncio.Queue[str | None] = asyncio.Queue(maxsize=2)
        self._fila_audio_ativa = fila_audio
        self._audio_medida = False
        frases_enfileiradas: list[str] = []
        frases_reproduzidas: list[str] = []
        async def falar_frase(frase: str) -> None:
            await fila_audio.put(frase)
            frases_enfileiradas.append(frase)
        tarefa_audio = asyncio.create_task(
            self._reproduzir_fila(fila_audio, frases_reproduzidas)
        )
        primeira_frase = True
        def registrar_primeiro_token() -> None:
            delta = time.perf_counter() - fim_fala
            self._tempos["primeiro_token"].append(delta)
            log.info("medicao etapa=primeiro_token ms=%.0f", delta * 1000)

        try:
            async for frase in self.agente.responder(
                texto_normalizado,
                receber_confirmacao=self._aguardar_confirmacao,
                ao_primeiro_token=registrar_primeiro_token,
            ):
                if primeira_frase:
                    delta = time.perf_counter() - fim_fala
                    self._tempos["primeira_frase"].append(delta)
                    log.info("medicao etapa=primeira_frase ms=%.0f", delta * 1000)
                    # Cada nova chamada ao TTS pode reiniciar a geração de voz.
                    # Preserve a frase inteira em uma única síntese para evitar
                    # mudanças de timbre entre orações da mesma frase.
                    partes_fala = [frase]
                    primeira_frase = False
                else:
                    partes_fala = [frase]
                politica = getattr(self.agente, "confirmacao", None)
                if getattr(politica, "pendente", None) is not None:
                    while not self._turnos.empty():
                        try:
                            self._turnos.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    self._aguardando_confirmacao = True
                for parte_fala in partes_fala:
                    await falar_frase(parte_fala)
        except asyncio.CancelledError:
            if self._cancelamento_stream_ativo is not None:
                self._cancelamento_stream_ativo.set()
            cancelar = getattr(self.agente.provedor, "cancelar", None)
            if cancelar:
                cancelar()
            self.tts.parar()
            tarefa_audio.cancel()
            try:
                await tarefa_audio
            except asyncio.CancelledError:
                pass
            self._fila_audio_ativa = None
            return
        except Exception as erro:
            log.error("falha etapa=agente codigo=%s", type(erro).__name__)
            from alfred.nucleo.provedor_llm import ModeloOllamaNaoInstalado, TempoEsgotadoOllama
            if isinstance(erro, ModeloOllamaNaoInstalado):
                modelo = getattr(self.agente.provedor, "modelo", "modelo configurado")
                await falar_frase(f"O modelo não está instalado. Execute ollama pull {modelo}.")
            elif isinstance(erro, TempoEsgotadoOllama):
                await falar_frase("O modelo demorou demais para responder. Tente novamente.")
            else:
                await falar_frase("Desculpe, não consegui acessar o Ollama local.")
        await fila_audio.put(None)
        await tarefa_audio
        # O fim da síntese não garante que o dispositivo terminou de tocar o
        # áudio. Só confirmamos uma frase quando a reprodução retorna sem erro.
        # Uma falha de reprodução recebe uma única tentativa extra antes de
        # devolver o ciclo ao microfone.
        restantes = list(frases_reproduzidas)
        nao_confirmadas: list[str] = []
        for frase in frases_enfileiradas:
            try:
                restantes.remove(frase)
            except ValueError:
                nao_confirmadas.append(frase)
        for frase in nao_confirmadas:
            self._registrar_conversa("dito", frase, "reproducao_inicial_falhou")
            if not await self._falar_texto(frase):
                log.error("resposta_nao_confirmada caracteres=%d", len(frase))
        self._fila_audio_ativa = None
        self.mostrar_estado(EstadoVoz.OUVINDO if not self.mudo else EstadoVoz.OCIOSO)

    async def _reproduzir_fila(
        self, fila: asyncio.Queue[str | None], confirmadas: list[str] | None = None
    ) -> None:
        frase = await fila.get()
        audio_pronto: tuple[Any, int] | None = None
        while frase is not None:
            self.mostrar_estado(EstadoVoz.FALANDO)
            tarefa_reproducao: asyncio.Task[Any]
            cancelamento_stream: threading.Event | None = None
            if audio_pronto is None and hasattr(self.tts, "reproduzir_texto_stream"):
                print(f"[Alfred] {frase}")
                cancelamento_stream = threading.Event()
                self._cancelamento_stream_ativo = cancelamento_stream
                tarefa_reproducao = asyncio.create_task(
                    asyncio.to_thread(
                        self._reproduzir_texto_stream, frase, cancelamento_stream
                    )
                )
            else:
                try:
                    audio, taxa = audio_pronto or await asyncio.to_thread(self.tts.sintetizar, frase)
                    audio_pronto = None
                except asyncio.CancelledError:
                    self.tts.parar()
                    raise
                except Exception as erro:
                    self._registrar_falha_tts(erro)
                    self._registrar_conversa("dito", frase, "sintese_falhou")
                    fila.task_done()
                    frase = await fila.get()
                    continue
                print(f"[Alfred] {frase}")
                tarefa_reproducao = asyncio.create_task(
                    asyncio.to_thread(self._reproduzir_audio, audio, taxa)
                )
            proxima = await fila.get()
            if proxima is None:
                try:
                    await self._aguardar_reproducao(
                        tarefa_reproducao, cancelamento_stream
                    )
                    if confirmadas is not None:
                        confirmadas.append(frase)
                    self._registrar_conversa("dito", frase, "reproducao_concluida")
                except asyncio.CancelledError:
                    self.tts.parar()
                    raise
                except Exception as erro:
                    self._registrar_falha_tts(erro)
                    self._registrar_conversa("dito", frase, "reproducao_falhou")
                finally:
                    fila.task_done()
                    fila.task_done()
                break

            tarefa_sintese = asyncio.create_task(
                asyncio.to_thread(
                    self.tts.sintetizar,
                    proxima,
                    **({"cancelar": cancelamento_stream} if cancelamento_stream else {}),
                )
            )
            try:
                await self._aguardar_reproducao(
                    tarefa_reproducao, cancelamento_stream
                )
                if confirmadas is not None:
                    confirmadas.append(frase)
                self._registrar_conversa("dito", frase, "reproducao_concluida")
            except asyncio.CancelledError:
                tarefa_sintese.cancel()
                self.tts.parar()
                raise
            except Exception as erro:
                self._registrar_falha_tts(erro)
                print(f"Alfred: {frase}")
                self._registrar_conversa("dito", frase, "reproducao_falhou")
            finally:
                fila.task_done()
            if frase.rstrip().endswith((".", "!", "?", "…")):
                await asyncio.sleep(PAUSA_ENTRE_FRASES_S)
            try:
                audio_pronto = await tarefa_sintese
            except asyncio.CancelledError:
                self.tts.parar()
                raise
            except Exception as erro:
                self._registrar_falha_tts(erro)
                print(f"Alfred: {proxima}")
                self._registrar_conversa("dito", proxima, "sintese_falhou")
                fila.task_done()
                audio_pronto = None
                frase = await fila.get()
                continue
            frase = proxima
        if frase is None and not self.mudo:
            fila.task_done()
        self.mostrar_estado(EstadoVoz.OUVINDO if not self.mudo else EstadoVoz.OCIOSO)

    def _registrar_inicio_audio(self, latencia_s: float = 0.0) -> None:
        if self._audio_medida:
            return
        delta = time.perf_counter() + max(0.0, latencia_s) - self._marco_fim_fala
        self._tempos["primeiro_audio"].append(delta)
        log.info("medicao etapa=primeiro_audio ms=%.0f", delta * 1000)
        self._audio_medida = True

    @staticmethod
    def _registrar_falha_tts(erro: Exception) -> None:
        codigo = type(erro).__name__
        etapa = "saida_audio" if codigo == "PortAudioError" else "tts"
        log.error("falha etapa=%s codigo=%s", etapa, codigo)
        if etapa == "saida_audio":
            print(
                "Falha ao reproduzir no dispositivo de áudio do Windows; "
                "a resposta não foi falada."
            )
        else:
            print("Falha na síntese do VoiceStudio; a resposta não foi falada.")

    def _reproduzir_audio(self, audio: Any, taxa: int) -> None:
        if hasattr(self.tts, "latencia_dispositivo_s"):
            self.tts.reproduzir(audio, taxa, ao_inicio=self._registrar_inicio_audio)
        else:
            self._registrar_inicio_audio()
            self.tts.reproduzir(audio, taxa)

    async def _aguardar_reproducao(
        self,
        tarefa: asyncio.Task[Any],
        cancelamento: threading.Event | None,
    ) -> None:
        try:
            await tarefa
        except asyncio.CancelledError:
            if cancelamento is not None:
                cancelamento.set()
            self.tts.parar()
            raise
        finally:
            if (
                cancelamento is not None
                and not cancelamento.is_set()
                and self._cancelamento_stream_ativo is cancelamento
            ):
                self._cancelamento_stream_ativo = None

    def _reproduzir_texto_stream(
        self, texto: str, cancelar: threading.Event | None = None
    ) -> None:
        self.tts.reproduzir_texto_stream(
            texto, ao_inicio=self._registrar_inicio_audio, cancelar=cancelar
        )

    async def _falar_texto(self, texto: str) -> bool:
        self.mostrar_estado(EstadoVoz.FALANDO)
        try:
            audio, taxa = await asyncio.to_thread(self.tts.sintetizar, texto)
            await asyncio.to_thread(self.tts.reproduzir, audio, taxa)
            self._registrar_conversa("dito", texto, "reproducao_concluida")
            return True
        except Exception as erro:
            self._registrar_falha_tts(erro)
            self._registrar_conversa("dito", texto, "reproducao_falhou")
            return False
        finally:
            self.mostrar_estado(EstadoVoz.OCIOSO)

    async def _aguardar_confirmacao(self) -> str:
        fila_audio = getattr(self, "_fila_audio_ativa", None)
        if fila_audio is not None:
            await fila_audio.join()
        self.mostrar_estado(EstadoVoz.OUVINDO)
        self._aguardando_confirmacao = True
        try:
            turno = await asyncio.wait_for(self._turnos.get(), 10)
        except TimeoutError:
            return ""
        finally:
            self._aguardando_confirmacao = False
        if turno is None:
            return ""
        audio, _ = turno
        self.mostrar_estado(EstadoVoz.TRANSCREVENDO)
        resultado = await asyncio.to_thread(self.stt.transcrever, audio)
        self._registrar_conversa("escutado", resultado.texto, "confirmacao_transcrita")
        if not resultado.texto.strip() or resultado.confianca < self.limiar_confianca:
            log.info(
                "confirmacao_cancelada motivo=transcricao_incerta confianca=%.3f",
                resultado.confianca,
            )
            self.mostrar_estado(EstadoVoz.PENSANDO)
            return ""
        if self.debug:
            print(f"[DEBUG confirmação] {resultado.texto}")
        if resultado.texto.strip().casefold() == "/mudo":
            self.mudo = True
            self.mostrar_estado(EstadoVoz.OCIOSO)
            return ""
        self.mostrar_estado(EstadoVoz.PENSANDO)
        return resultado.texto

    @staticmethod
    def _registrar_conversa(evento: str, texto: str, resultado: str) -> None:
        """Registra input/output em campos explícitos e escapa quebras de linha."""
        campo = "frase_input" if evento == "escutado" else "frase_output"
        log.info("conversa %s=%s resultado=%s", campo, json.dumps(texto, ensure_ascii=False), resultado)

    async def _ler_teclado(self) -> None:
        caminho_controle = os.getenv("ALFRED_VOZ_CONTROLE_ARQUIVO")
        if caminho_controle:
            prefixo_controle = Path(caminho_controle)
            while True:
                comandos = sorted(prefixo_controle.parent.glob(f"{prefixo_controle.name}-*.cmd"))
                for arquivo_controle in comandos:
                    try:
                        tecla = arquivo_controle.read_text(encoding="utf-8").strip()
                    except OSError:
                        tecla = ""
                    arquivo_controle.unlink(missing_ok=True)
                    for acao in tecla:
                        if acao.casefold() == "m":
                            self.mudo = not self.mudo
                            if self.mudo:
                                self._apertado = False
                                self._frames_fala.clear()
                                self._frames_recentes.clear()
                                self.vad.resetar()
                            log.info("microfone_mudo=%s", self.mudo)
                        elif acao in {" ", "\r", "\n"} and self.modo == "apertar":
                            self.ativar_manual()
                await asyncio.sleep(0.12)
        try:
            import msvcrt
        except ImportError:
            return
        while True:
            tecla = await asyncio.to_thread(_ler_tecla, msvcrt)
            if tecla.casefold() == "m":
                self.mudo = not self.mudo
                if self.mudo:
                    self._apertado = False
                    self._frames_fala.clear()
                    self._frames_recentes.clear()
                    self.vad.resetar()
                print("Microfone silenciado." if self.mudo else "Escuta ativada.")
                log.info("microfone_mudo=%s", self.mudo)
            elif tecla in {" ", "\r", "\n"} and self.modo == "apertar":
                self.ativar_manual()

    def _resumo_tempos(self) -> None:
        rotulos = {"primeira_palavra": "primeira palavra", "primeiro_token": "primeiro token", "primeira_frase": "primeira frase completa", "primeiro_audio": "fim de fala até primeiro áudio", "transcricao": "transcrição"}
        for etapa, registros in self._tempos.items():
            valores = [t * 1000 for t in registros]
            if valores:
                ordenados = sorted(valores)
                meio = len(ordenados) // 2
                mediana = ordenados[meio] if len(ordenados) % 2 else (ordenados[meio - 1] + ordenados[meio]) / 2
                indice_p95 = max(0, min(len(ordenados) - 1, int(len(ordenados) * 0.95 + 0.999999) - 1))
                log.info("tempo etapa=%s amostras=%d mediana_ms=%.0f p95_ms=%.0f pior_ms=%.0f",
                         etapa, len(valores), mediana, ordenados[indice_p95], max(valores))
                if etapa in rotulos:
                    print(f"[métrica] {rotulos[etapa]}: mediana {mediana:.0f} ms; p95 {ordenados[indice_p95]:.0f} ms ({len(valores)} amostras)")

    def _salvar_debug(self, audio: Any, texto: str) -> None:
        """Salva captura e transcrição para avaliação somente no modo --debug."""
        import numpy as np
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        base = self.debug_dir / f"fala-{time.time_ns()}"
        amostras = np.asarray(audio, dtype=np.float32).reshape(-1)
        pcm = (np.clip(amostras, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        with wave.open(str(base.with_suffix(".wav")), "wb") as arquivo:
            arquivo.setnchannels(1)
            arquivo.setsampwidth(2)
            arquivo.setframerate(16000)
            arquivo.writeframes(pcm)
        base.with_suffix(".txt").write_text(texto.strip() + "\n", encoding="utf-8")


def _ler_tecla(modulo: Any) -> str:
    while not modulo.kbhit():
        time.sleep(0.05)
    return modulo.getwch()
