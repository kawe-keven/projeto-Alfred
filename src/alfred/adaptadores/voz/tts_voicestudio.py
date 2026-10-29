"""Cliente local de TTS do VoiceStudio, sem SDK ou armazenamento de áudio."""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import math
import queue
import socket
import threading
import time
from typing import Any, Iterator
from urllib.parse import urlsplit

from alfred.adaptadores.voz.texto_voz import aplicar_pronuncias, normalizar_texto_para_voz

log = logging.getLogger("alfred.voz")
VERSAO_VOICESTUDIO_VALIDADA = "0.5.6"
_FRASES_CACHE = ("Entendido.",)


class ErroVoiceStudio(RuntimeError):
    """Falha local sanitizada, que nunca contém a resposta do servidor."""


class _ErroVoiceStudioTransitorio(ErroVoiceStudio):
    """Falha de transporte que pode ser repetida uma vez com conexão nova."""


class _ErroReproducaoParcial(ErroVoiceStudio):
    """O VoiceStudio falhou depois de o dispositivo já começar a tocar."""


class SintetizadorVoiceStudio:
    """TTS PCM local exclusivo do VoiceStudio, com uma voz fixa."""

    taxa_pcm = 24000

    def __init__(
        self,
        url: str = "http://127.0.0.1:3900/v1",
        motor: str = "omnivoice",
        voz: str = "alloy",
        *,
        formato: str = "pcm",
        taxa_amostragem: int = 24000,
        timeout_conexao_s: float = 3.0,
        timeout_leitura_s: float = 30.0,
        fallback: str = "texto",
        aquecer: bool = True,
        pronuncias: dict[str, str] | None = None,
        velocidade: float = 1.0,
        seed: int = 42,
        estilo: str = "",
        sintetizador_fallback: Any = None,
    ) -> None:
        self._partes_url = self._validar_url(url)
        if not motor.strip() or not voz.strip():
            raise ValueError("ALFRED_VOICESTUDIO_MOTOR e ALFRED_VOICESTUDIO_VOZ não podem ficar vazios")
        if formato.lower() != "pcm":
            raise ValueError("ALFRED_VOICESTUDIO_FORMAT aceita apenas pcm para saída em blocos")
        if taxa_amostragem != self.taxa_pcm:
            raise ValueError("O VoiceStudio entrega PCM mono a 24000 Hz; ajuste ALFRED_VOICESTUDIO_TAXA para 24000")
        if not math.isfinite(timeout_conexao_s) or timeout_conexao_s <= 0:
            raise ValueError("ALFRED_VOICESTUDIO_TIMEOUT_CONEXAO deve ser maior que zero")
        if not math.isfinite(timeout_leitura_s) or timeout_leitura_s <= 0:
            raise ValueError("ALFRED_VOICESTUDIO_TIMEOUT_LEITURA deve ser maior que zero")
        if fallback not in {"texto", "piper"}:
            raise ValueError("O fallback do VoiceStudio deve ser 'piper' ou 'texto'")
        if fallback == "piper" and sintetizador_fallback is None:
            raise ValueError("O fallback Piper requer um sintetizador configurado")

        self.url = url.rstrip("/")
        self.motor = motor.strip()
        self.voz = voz.strip()
        self.formato = formato.lower()
        self.taxa_amostragem = taxa_amostragem
        self.timeout_conexao_s = timeout_conexao_s
        self.timeout_leitura_s = timeout_leitura_s
        self.fallback = fallback
        self.sintetizador_fallback = sintetizador_fallback
        self.versao: str | None = None
        self.estado = "nao_verificado"
        self.fallback_ativo = False
        self.ultimo_primeiro_byte_s: float | None = None
        self._aquecer = aquecer
        self.pronuncias = pronuncias or {}
        if not math.isfinite(velocidade) or not 0.25 <= velocidade <= 4:
            raise ValueError("A velocidade do VoiceStudio deve ficar entre 0.25 e 4")
        if seed < 0:
            raise ValueError("A seed fixa do VoiceStudio não pode ser negativa")
        self.velocidade = velocidade
        self.seed = seed
        self.estilo = estilo.strip()
        log.info(
            "tts_config motor=%s voice_id=%s seed=%d",
            self.motor,
            self.voz,
            self.seed,
        )
        self._cache: dict[str, tuple[Any, int]] = {}
        self._local = threading.local()
        self._conexoes: set[http.client.HTTPConnection] = set()
        self._respostas: dict[http.client.HTTPConnection, http.client.HTTPResponse] = {}
        self._conexoes_lock = threading.Lock()
        self._sintese_lock = threading.Lock()
        self._fallback_lock = threading.Lock()
        self._saida: Any = None
        self._sd: Any = None
        self._aviso_pendente = False
        self._aviso_impresso = False
        self._aviso_versao_impresso = False
        self._preparado = False
        self.latencia_dispositivo_s: float | None = None

    @staticmethod
    def _validar_url(url: str):
        partes = urlsplit(url)
        if (
            partes.scheme not in {"http", "https"}
            or partes.hostname is None
            or partes.hostname.casefold() not in {"localhost", "127.0.0.1", "::1"}
            or partes.username is not None
            or partes.password is not None
            or partes.query
            or partes.fragment
        ):
            raise ValueError("ALFRED_VOICESTUDIO_URL deve usar somente localhost ou um endereço de loopback")
        try:
            porta = partes.port or (443 if partes.scheme == "https" else 80)
        except ValueError:
            raise ValueError("ALFRED_VOICESTUDIO_URL contém uma porta inválida") from None
        try:
            enderecos = socket.getaddrinfo(partes.hostname, porta, type=socket.SOCK_STREAM)
            if not enderecos or any(
                not ipaddress.ip_address(item[4][0]).is_loopback for item in enderecos
            ):
                raise ValueError
        except (OSError, ValueError):
            raise ValueError("ALFRED_VOICESTUDIO_URL deve resolver somente para loopback") from None
        return partes

    def _caminho(self, sufixo: str) -> str:
        base = self._partes_url.path.rstrip("/")
        return (base + "/" + sufixo.lstrip("/")) or "/"

    def _raiz_caminho(self, sufixo: str) -> str:
        base = self._partes_url.path.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return (base + "/" + sufixo.lstrip("/")) or "/"

    def _conexao(self) -> http.client.HTTPConnection:
        conexao = getattr(self._local, "conexao", None)
        classe = http.client.HTTPSConnection if self._partes_url.scheme == "https" else http.client.HTTPConnection
        porta = self._partes_url.port or (443 if self._partes_url.scheme == "https" else 80)
        if conexao is None:
            conexao = classe(self._partes_url.hostname, porta, timeout=self.timeout_conexao_s)
            self._local.conexao = conexao
            with self._conexoes_lock:
                self._conexoes.add(conexao)
        return conexao

    def _requisitar(self, metodo: str, caminho: str, corpo: bytes | None = None):
        conexao = self._conexao()
        try:
            if conexao.sock is None:
                conexao.connect()
            if conexao.sock is not None:
                conexao.sock.settimeout(self.timeout_leitura_s)
            cabecalhos = {"Accept": "application/json" if metodo == "GET" else "audio/pcm"}
            if corpo is not None:
                cabecalhos["Content-Type"] = "application/json"
            cabecalhos["Connection"] = "keep-alive"
            conexao.request(metodo, caminho, body=corpo, headers=cabecalhos)
            resposta = conexao.getresponse()
            with self._conexoes_lock:
                self._respostas[conexao] = resposta
            return conexao, resposta
        except (OSError, http.client.HTTPException, TimeoutError):
            self._descartar_conexao(conexao)
            raise _ErroVoiceStudioTransitorio("VoiceStudio indisponível ou tempo esgotado.") from None

    def _descartar_conexao(self, conexao: http.client.HTTPConnection) -> None:
        with self._conexoes_lock:
            resposta = self._respostas.pop(conexao, None)
        if resposta is not None:
            try:
                resposta.close()
            except OSError:
                pass
        try:
            conexao.close()
        finally:
            if getattr(self._local, "conexao", None) is conexao:
                self._local.conexao = None
            with self._conexoes_lock:
                self._conexoes.discard(conexao)

    def _finalizar_resposta(self, conexao: http.client.HTTPConnection) -> None:
        with self._conexoes_lock:
            self._respostas.pop(conexao, None)

    @staticmethod
    def _erro_status(status: int, codigo: str | None = None) -> ErroVoiceStudio:
        if status == 404:
            return ErroVoiceStudio("Rota do VoiceStudio ausente ou alterada.")
        if status in {301, 302, 303, 307, 308}:
            return ErroVoiceStudio("Redirecionamento do VoiceStudio recusado por segurança.")
        if status in {400, 422}:
            return ErroVoiceStudio("Motor ou voz do VoiceStudio inexistente ou incompatível.")
        if status == 401:
            return ErroVoiceStudio("A autenticação do VoiceStudio foi recusada.")
        if status == 403 and codigo == "model_licence_required":
            return ErroVoiceStudio(
                "A licença do modelo exigida pelo VoiceStudio ainda não foi aceita. "
                "Aceite-a no catálogo de modelos para usar essa voz."
            )
        if status == 403:
            return ErroVoiceStudio(
                "O VoiceStudio recusou o acesso local. Confira o endereço e as permissões da API."
            )
        return ErroVoiceStudio("VoiceStudio indisponível ou respondeu com erro.")

    @staticmethod
    def _codigo_erro_resposta(resposta: http.client.HTTPResponse) -> str | None:
        try:
            corpo = resposta.read(16_385)
            if len(corpo) > 16_384:
                return None
            dados = json.loads(corpo)
        except (OSError, http.client.HTTPException, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        detalhe = dados.get("detail") if isinstance(dados, dict) else None
        codigo = detalhe.get("code") if isinstance(detalhe, dict) else None
        return codigo if isinstance(codigo, str) else None

    def verificar_disponibilidade(self) -> bool:
        conexao, resposta = self._requisitar("GET", self._raiz_caminho("health"))
        try:
            status = resposta.status
            tipo = resposta.getheader("Content-Type", "").split(";", 1)[0].lower()
            corpo = resposta.read(16385)
        except (OSError, http.client.HTTPException, TimeoutError):
            self._descartar_conexao(conexao)
            raise ErroVoiceStudio("VoiceStudio indisponível ou tempo esgotado.") from None
        if status != 200:
            self._descartar_conexao(conexao)
            raise self._erro_status(status)
        if tipo != "application/json" or len(corpo) > 16384:
            self._descartar_conexao(conexao)
            raise ErroVoiceStudio("Resposta malformada do VoiceStudio.")
        self._finalizar_resposta(conexao)
        try:
            dados = json.loads(corpo)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._descartar_conexao(conexao)
            raise ErroVoiceStudio("Resposta malformada do VoiceStudio.") from None
        if not isinstance(dados, dict) or dados.get("status") != "ok":
            self._descartar_conexao(conexao)
            raise ErroVoiceStudio("VoiceStudio indisponível.")
        versao = dados.get("version")
        self.versao = versao if isinstance(versao, str) else None
        self.estado = "disponivel"
        if (
            self.versao
            and self.versao != VERSAO_VOICESTUDIO_VALIDADA
            and not self._aviso_versao_impresso
        ):
            print(f"Aviso: VoiceStudio {self.versao}; versão validada: {VERSAO_VOICESTUDIO_VALIDADA}.")
            self._aviso_versao_impresso = True
        return True

    def carregar(self) -> None:
        if self._preparado:
            return
        try:
            self.verificar_disponibilidade()
            import sounddevice as sd
            self._sd = sd
            self._abrir_saida()
            if self._aquecer:
                for frase in _FRASES_CACHE:
                    texto = normalizar_texto_para_voz(aplicar_pronuncias(frase, self.pronuncias))
                    self._cache[texto.casefold()] = self._sintetizar_voice(texto)
            self.estado = "disponivel"
        except Exception as erro:
            log.warning("tts_inicializacao_falhou categoria=%s", type(erro).__name__)
            self._ativar_fallback()
            if self.sintetizador_fallback is not None:
                try:
                    self.sintetizador_fallback.carregar()
                except Exception as erro_fallback:
                    log.warning(
                        "tts_fallback_inicializacao_falhou categoria=%s",
                        type(erro_fallback).__name__,
                    )
        self._preparado = True

    def _abrir_saida(self) -> None:
        """Abre o dispositivo de saída atual e atualiza a latência observada."""
        self._saida = self._sd.OutputStream(
            samplerate=self.taxa_amostragem, channels=1, dtype="float32",
            blocksize=0, latency="low",
        )
        self._saida.start()
        try:
            self.latencia_dispositivo_s = float(self._saida.latency)
        except (TypeError, ValueError):
            self.latencia_dispositivo_s = None

    def _reabrir_saida(self) -> None:
        anterior, self._saida = self._saida, None
        if anterior is not None:
            try:
                if anterior.active:
                    anterior.abort()
            except Exception:
                pass
            try:
                anterior.close()
            except Exception:
                pass
        self._abrir_saida()
        log.warning("tts_saida_reaberta")

    def _escrever_saida(self, audio: Any) -> None:
        """Recupera uma vez se o dispositivo Windows invalidar o stream aberto."""
        for tentativa in range(2):
            try:
                if self._saida is None:
                    raise ErroVoiceStudio("Saída de áudio indisponível.")
                if not self._saida.active:
                    self._saida.start()
                self._saida.write(audio)
                return
            except self._sd.PortAudioError:
                if tentativa:
                    raise
                log.warning("tts_saida_portaudio erro=stream_invalidado recuperacao=tentando")
                self._reabrir_saida()

    def _corpo_sintese(self, texto: str) -> bytes:
        return json.dumps({
            "model": self.motor,
            "input": texto,
            "voice": self.voz,
            "response_format": "pcm",
            "language": "pt",
            "speed": self.velocidade,
            "seed": self.seed,
            **({"instructions": self.estilo} if self.estilo else {}),
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _iterar_pcm(
        self, texto: str, *, cancelar: threading.Event | None = None
    ) -> Iterator[bytes]:
        inicio = time.perf_counter()
        self.ultimo_primeiro_byte_s = None
        corpo = self._corpo_sintese(texto)
        log.info(
            "tts_pedido motor=%s voice_id=%s seed=%d caracteres=%d",
            self.motor,
            self.voz,
            self.seed,
            len(texto),
        )
        for tentativa in range(2):
            if cancelar is not None and cancelar.is_set():
                return
            try:
                conexao, resposta = self._requisitar(
                    "POST", self._caminho("audio/speech"), corpo
                )
            except _ErroVoiceStudioTransitorio:
                if cancelar is not None and cancelar.is_set():
                    return
                if tentativa == 0:
                    time.sleep(0.25)
                    continue
                raise

            status = resposta.status
            tipo = resposta.getheader("Content-Type", "").split(";", 1)[0].lower()
            if status != 200:
                codigo = self._codigo_erro_resposta(resposta) if status == 403 else None
                self._descartar_conexao(conexao)
                if status >= 500 and tentativa == 0:
                    log.warning("tts_http_transitorio status=%d tentativa=1", status)
                    time.sleep(0.25)
                    continue
                raise self._erro_status(status, codigo)
            if tipo not in {"audio/pcm", "application/octet-stream"}:
                self._descartar_conexao(conexao)
                raise ErroVoiceStudio("Resposta malformada do VoiceStudio.")

            recebeu = False
            resposta_finalizada = False
            restante = b""
            try:
                while True:
                    if cancelar is not None and cancelar.is_set():
                        return
                    bloco = resposta.read1(4096)
                    if not bloco:
                        break
                    if not recebeu:
                        recebeu = True
                        self.ultimo_primeiro_byte_s = time.perf_counter() - inicio
                        log.info(
                            "tts_primeiro_byte motor=%s ms=%.0f",
                            self.motor,
                            self.ultimo_primeiro_byte_s * 1000,
                        )
                    bloco = restante + bloco
                    if len(bloco) % 2:
                        restante, bloco = bloco[-1:], bloco[:-1]
                    else:
                        restante = b""
                    if bloco:
                        yield bloco
                if restante or not recebeu:
                    raise ErroVoiceStudio("Resposta malformada do VoiceStudio.")
                self._finalizar_resposta(conexao)
                resposta_finalizada = True
                return
            except ErroVoiceStudio:
                self._descartar_conexao(conexao)
                raise
            except (OSError, http.client.HTTPException, TimeoutError):
                self._descartar_conexao(conexao)
                if cancelar is not None and cancelar.is_set():
                    return
                if not recebeu and tentativa == 0:
                    time.sleep(0.25)
                    continue
                raise _ErroVoiceStudioTransitorio(
                    "VoiceStudio indisponível ou tempo esgotado."
                ) from None
            finally:
                # Fechar o iterador durante barge-in também precisa soltar a
                # resposta HTTP e o socket, mesmo sem consumir o PCM restante.
                if not resposta_finalizada:
                    self._descartar_conexao(conexao)

    @staticmethod
    def _pcm_para_array(dados: bytes):
        import numpy as np
        if not dados or len(dados) % 2:
            raise ErroVoiceStudio("Resposta malformada do VoiceStudio.")
        return np.frombuffer(dados, dtype="<i2").astype(np.float32) / 32768.0

    def _sintetizar_voice(self, texto: str):
        inicio = time.perf_counter()
        partes = list(self._iterar_pcm(texto))
        dados = b"".join(partes)
        audio = self._pcm_para_array(dados)
        duracao = len(dados) / 2 / self.taxa_amostragem
        decorrido = time.perf_counter() - inicio
        if duracao:
            log.info(
                "tts_sintese motor=%s duracao_ms=%.0f total_ms=%.0f fator_tempo_real=%.3f",
                self.motor,
                duracao * 1000,
                decorrido * 1000,
                decorrido / duracao,
            )
        return audio, self.taxa_amostragem

    def sintetizar(
        self, texto: str, *, cancelar: threading.Event | None = None
    ):
        if cancelar is not None and cancelar.is_set():
            return None
        if not self._preparado:
            self.carregar()
        normalizado = normalizar_texto_para_voz(aplicar_pronuncias(texto, self.pronuncias))
        if not normalizado:
            raise ValueError("Não há texto para sintetizar.")
        chave = normalizado.casefold()
        with self._sintese_lock:
            if cancelar is not None and cancelar.is_set():
                return None
            # Depois de cair no fallback, mantenha a mesma voz até reiniciar
            # a sessão; alternar automaticamente na próxima frase é audível.
            if self.fallback_ativo:
                return self._sintetizar_fallback(texto)
            if chave in self._cache:
                return self._cache[chave]
            try:
                return self._sintetizar_voice(normalizado)
            except ErroVoiceStudio as erro:
                if cancelar is not None and cancelar.is_set():
                    return None
                log.warning("falha_voicestudio categoria=%s", str(erro).split(".", 1)[0])
                self._ativar_fallback()
                return self._sintetizar_fallback(texto)

    def reproduzir_texto_stream(
        self,
        texto: str,
        *,
        ao_inicio: Any = None,
        cancelar: threading.Event | None = None,
    ) -> None:
        """Toca o PCM durante a chegada, com pré-buffer curto e limitado."""
        if not self._preparado:
            self.carregar()
        normalizado = normalizar_texto_para_voz(aplicar_pronuncias(texto, self.pronuncias))
        with self._sintese_lock:
            if cancelar is not None and cancelar.is_set():
                return
            if self.fallback_ativo:
                self._reproduzir_fallback(texto, ao_inicio)
                return
            em_cache = self._cache.get(normalizado.casefold())
            if em_cache is not None:
                if cancelar is not None and cancelar.is_set():
                    return
                self.reproduzir(*em_cache, ao_inicio=ao_inicio)
                return
        try:
            self._reproduzir_voice_stream(
                normalizado, ao_inicio=ao_inicio, cancelar=cancelar
            )
        except _ErroReproducaoParcial:
            log.warning("falha_voicestudio categoria=stream_parcial")
            self._ativar_fallback()
            # Reproduz a frase inteira no fallback para não perder o resto
            # da resposta; o início já tocado pode ser ouvido novamente.
            self._reproduzir_fallback(texto, ao_inicio)
        except ErroVoiceStudio as erro:
            if cancelar is not None and cancelar.is_set():
                return
            log.warning("falha_voicestudio categoria=%s", str(erro).split(".", 1)[0])
            self._ativar_fallback()
            self._reproduzir_fallback(texto, ao_inicio)

    def _reproduzir_voice_stream(
        self,
        texto: str,
        *,
        ao_inicio: Any = None,
        cancelar: threading.Event | None = None,
    ) -> None:
        """Produz PCM em streaming, com fila limitada e reprodução concorrente."""
        prebuffer = bytearray()
        bloco_saida = bytearray()
        inicio_reproducao = threading.Event()
        amostras_recebidas = 0
        inicio = time.perf_counter()
        fim_geracao: float | None = None
        limite_prebuffer = 8192  # cerca de 171 ms a 24 kHz, mono, PCM16
        tamanho_bloco_saida = 4096  # cerca de 85 ms
        fila_saida: queue.Queue[Any] = queue.Queue(maxsize=16)
        sentinela = object()
        cancelar_local = cancelar or threading.Event()
        falha_saida = threading.Event()
        erros_saida: list[BaseException] = []
        consumidor: threading.Thread | None = None
        erro_stream: ErroVoiceStudio | None = None

        def consumir_audio() -> None:
            primeiro_bloco = True
            while not cancelar_local.is_set():
                try:
                    audio = fila_saida.get(timeout=0.05)
                except queue.Empty:
                    continue
                if audio is sentinela:
                    return
                try:
                    if cancelar_local.is_set():
                        return
                    if primeiro_bloco and ao_inicio is not None:
                        ao_inicio(self.latencia_dispositivo_s or 0.0)
                    self._escrever_saida(audio)
                    primeiro_bloco = False
                    inicio_reproducao.set()
                except BaseException as erro:
                    erros_saida.append(erro)
                    falha_saida.set()
                    return
                finally:
                    fila_saida.task_done()

        def iniciar_consumidor() -> None:
            nonlocal consumidor
            if consumidor is None:
                consumidor = threading.Thread(
                    target=consumir_audio,
                    name="alfred-tts-reproducao",
                    daemon=True,
                )
                consumidor.start()

        def enfileirar(dados: bytes | bytearray) -> bool:
            audio = self._pcm_para_array(bytes(dados))
            while not cancelar_local.is_set() and not falha_saida.is_set():
                try:
                    fila_saida.put(audio, timeout=0.05)
                    return True
                except queue.Full:
                    continue
            return False

        def finalizar_consumidor() -> None:
            if consumidor is None:
                return
            if consumidor.is_alive() and not cancelar_local.is_set() and not falha_saida.is_set():
                while consumidor.is_alive():
                    try:
                        fila_saida.put(sentinela, timeout=0.05)
                        break
                    except queue.Full:
                        continue
            consumidor.join()

        iterador = self._iterar_pcm(texto, cancelar=cancelar_local)
        try:
            with self._sintese_lock:
                try:
                    for bloco in iterador:
                        if cancelar_local.is_set() or falha_saida.is_set():
                            break
                        amostras_recebidas += len(bloco) // 2
                        if not inicio_reproducao.is_set() and consumidor is None:
                            prebuffer.extend(bloco)
                            if len(prebuffer) < limite_prebuffer:
                                continue
                            iniciar_consumidor()
                            enfileirar(prebuffer)
                            prebuffer.clear()
                            continue

                        bloco_saida.extend(bloco)
                        if len(bloco_saida) >= tamanho_bloco_saida:
                            tamanho_par = len(bloco_saida) - len(bloco_saida) % 2
                            if not enfileirar(bloco_saida[:tamanho_par]):
                                break
                            del bloco_saida[:tamanho_par]

                    fim_geracao = time.perf_counter()
                    if not cancelar_local.is_set() and not falha_saida.is_set():
                        if prebuffer:
                            iniciar_consumidor()
                            enfileirar(prebuffer)
                        if bloco_saida:
                            enfileirar(bloco_saida)
                except ErroVoiceStudio as erro:
                    if cancelar_local.is_set():
                        return
                    erro_stream = erro
                    # Publique o fallback antes de liberar o lock: a próxima
                    # frase já pode estar aguardando para ser pré-sintetizada.
                    self._ativar_fallback(abortar_saida=False)
                finally:
                    iterador.close()
        finally:
            finalizar_consumidor()

        if cancelar_local.is_set():
            return
        if falha_saida.is_set():
            raise erros_saida[0]
        if erro_stream is not None:
            if inicio_reproducao.is_set():
                raise _ErroReproducaoParcial(
                    "VoiceStudio falhou durante a reprodução da frase."
                ) from None
            raise erro_stream

        duracao = amostras_recebidas / self.taxa_amostragem
        decorrido = time.perf_counter() - inicio
        duracao_geracao = (fim_geracao or decorrido) - inicio
        if duracao:
            log.info(
                "tts_stream_reproducao motor=%s duracao_ms=%.0f geracao_ms=%.0f total_ms=%.0f fator_tempo_real=%.3f",
                self.motor,
                duracao * 1000,
                duracao_geracao * 1000,
                decorrido * 1000,
                duracao_geracao / duracao,
            )
    def _reproduzir_fallback(self, texto: str, ao_inicio: Any = None) -> None:
        audio, taxa = self._sintetizar_fallback(texto)
        self.sintetizador_fallback.reproduzir(audio, taxa, ao_inicio=ao_inicio)

    def _ativar_fallback(self, *, abortar_saida: bool = True) -> None:
        self.fallback_ativo = True
        self.estado = "piper" if self.sintetizador_fallback is not None else "texto"
        self.ultimo_primeiro_byte_s = None
        # Descarta PCM parcial do VoiceStudio antes de tocar a frase completa no Piper.
        if abortar_saida and self._saida is not None and self._saida.active:
            self._saida.abort()
        if not self._aviso_pendente and not self._aviso_impresso:
            self._aviso_pendente = True
            log.warning("tts_fallback=ativado motor=%s", self.motor)

    def _sintetizar_fallback(self, texto: str):
        with self._fallback_lock:
            if self.sintetizador_fallback is not None:
                log.warning("tts_fallback=ativado motor=piper")
                return self.sintetizador_fallback.sintetizar(texto)
            if not self._aviso_impresso:
                print("VoiceStudio indisponível; não foi possível falar a resposta.")
                self._aviso_impresso = True
                self._aviso_pendente = False
            raise ErroVoiceStudio("Nenhum sintetizador local está disponível.")

    def reproduzir(self, audio: Any, taxa: int, *, ao_inicio: Any = None) -> None:
        if self.fallback_ativo:
            if self.sintetizador_fallback is not None:
                self.sintetizador_fallback.reproduzir(audio, taxa, ao_inicio=ao_inicio)
                return
            raise ErroVoiceStudio("VoiceStudio indisponível; áudio não reproduzido.")
        if taxa != self.taxa_amostragem or self._saida is None:
            raise ValueError("A taxa ou saída de áudio não corresponde ao stream aberto")
        if ao_inicio is not None:
            ao_inicio(self.latencia_dispositivo_s or 0.0)
        self._escrever_saida(audio)

    def parar(self) -> None:
        with self._conexoes_lock:
            conexoes = tuple(self._conexoes)
        for conexao in conexoes:
            self._descartar_conexao(conexao)
        if self._saida is not None and self._saida.active:
            self._saida.abort()
        if self.sintetizador_fallback is not None:
            self.sintetizador_fallback.parar()

    def fechar(self) -> None:
        self.parar()
        if self._saida is not None:
            self._saida.close()
            self._saida = None
        self._cache.clear()
        if self.sintetizador_fallback is not None:
            self.sintetizador_fallback.fechar()
