"""Transcrição local com Parakeet TDT v3 ou faster-whisper."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import time
import tarfile
import urllib.error
import urllib.request
from typing import Any
from pathlib import Path

from alfred.configuracao.configuracao import RAIZ_PROJETO

log = logging.getLogger("alfred.voz")


@dataclass(frozen=True)
class Transcricao:
    texto: str
    confianca: float


class TranscritorLocal:
    PERFIS_BEAM_SIZE = {"rápido": 1, "equilibrado": 5, "preciso": 8}
    # Termos do produto no prompt faziam o Whisper completá-los em áudio ambíguo.
    PROMPT_PT_BR = "Conversa espontânea em português brasileiro. Transcreva somente o que foi falado."

    def __init__(self, modelo: str = "base", dispositivo: str = "cpu",
                 compute_type: str = "int8", perfil: str = "equilibrado",
                 vocabulario: tuple[str, ...] | list[str] = (),
                 engine: str = "faster-whisper") -> None:
        if perfil not in self.PERFIS_BEAM_SIZE:
            raise ValueError("Perfil STT deve ser rápido, equilibrado ou preciso")
        self.modelo_nome, self.dispositivo, self.compute_type = modelo, dispositivo, compute_type
        if engine not in {"parakeet", "faster-whisper"}:
            raise ValueError("Motor STT deve ser parakeet ou faster-whisper")
        self.engine = engine
        self.perfil = perfil
        termos = tuple(dict.fromkeys(
            termo.strip() for termo in vocabulario
            if isinstance(termo, str) and termo.strip()
        ))
        # Limita dicas para muitas pessoas cadastradas não ocuparem o contexto do Whisper.
        self.vocabulario = termos[:40]
        self._modelo: Any = None
        self._dispositivo_ativo: str | None = None
        self._compute_type_ativo: str | None = None

    def carregar(self) -> None:
        if self.engine == "parakeet":
            self._carregar_parakeet()
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper ausente; instale o extra alfred[voz]") from None
        dispositivo, compute_type = self.dispositivo, self.compute_type
        if dispositivo == "auto":
            try:
                import ctranslate2
                tem_cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                tem_cuda = False
            dispositivo = "cuda" if tem_cuda else "cpu"
            if tem_cuda and compute_type == "int8":
                compute_type = "float16"
        try:
            self._modelo = WhisperModel(self.modelo_nome, device=dispositivo, compute_type=compute_type)
            self._dispositivo_ativo = dispositivo
            self._compute_type_ativo = compute_type
        except Exception:
            if dispositivo != "cuda":
                raise
            # Um driver ou runtime CUDA incompatível não impede o modo local em CPU.
            self._modelo = WhisperModel(self.modelo_nome, device="cpu", compute_type="int8")
            self._dispositivo_ativo = "cpu"
            self._compute_type_ativo = "int8"
            log.warning(
                "stt_cuda_indisponivel modelo=%s fallback=cpu compute_type=int8",
                self.modelo_nome,
            )
        log.info(
            "stt_pronto modelo=%s dispositivo=%s compute_type=%s perfil=%s beam_size=%d",
            self.modelo_nome,
            self._dispositivo_ativo,
            self._compute_type_ativo,
            self.perfil,
            self.PERFIS_BEAM_SIZE[self.perfil],
        )

    def _carregar_parakeet(self) -> None:
        try:
            import sherpa_onnx
        except ImportError:
            raise RuntimeError("sherpa-onnx ausente; instale o extra alfred[voz]") from None
        diretorio = preparar_modelo_parakeet()
        self._modelo = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(diretorio / "encoder.int8.onnx"),
            decoder=str(diretorio / "decoder.int8.onnx"),
            joiner=str(diretorio / "joiner.int8.onnx"),
            tokens=str(diretorio / "tokens.txt"),
            num_threads=max(1, min(4, __import__("os").cpu_count() or 1)),
            model_type="nemo_transducer",
            provider="cpu",
        )
        self._dispositivo_ativo = "cpu"
        self._compute_type_ativo = "int8"
        log.info("stt_pronto modelo=nvidia/parakeet-tdt-0.6b-v3 engine=parakeet-onnx dispositivo=cpu")

    def transcrever(self, audio: Any) -> Transcricao:
        if self._modelo is None:
            self.carregar()
        if _audio_sem_nivel_de_fala(audio):
            return Transcricao("", 0.0)
        audio = preparar_audio_para_stt(audio)
        if self.engine == "parakeet":
            fluxo = self._modelo.create_stream()
            fluxo.accept_waveform(16000, audio)
            self._modelo.decode_stream(fluxo)
            texto = fluxo.result.text.strip()
            # sherpa-onnx não expõe confiança por transcrição neste modelo.
            return Transcricao(texto, 0.5 if texto else 0.0)
        parametros = {
            "language": "pt",
            "vad_filter": False,
            "without_timestamps": True,
            "beam_size": self.PERFIS_BEAM_SIZE[self.perfil],
            "condition_on_previous_text": False,
            "word_timestamps": False,
            "initial_prompt": self.PROMPT_PT_BR,
            "no_speech_threshold": 0.6,
            "log_prob_threshold": -1.0,
            "compression_ratio_threshold": 2.4,
            "temperature": 0.0,
        }
        if self.vocabulario:
            parametros["hotwords"] = ", ".join(self.vocabulario)
        try:
            segmentos, _ = self._modelo.transcribe(audio, **parametros)
            partes, probabilidades = [], []
            for segmento in segmentos:
                partes.append(segmento.text.strip())
                confianca_texto = max(0.0, min(1.0, 1.0 + segmento.avg_logprob / 5))
                probabilidade_silencio = max(0.0, min(1.0, getattr(segmento, "no_speech_prob", 0.0)))
                probabilidades.append(confianca_texto * (1.0 - probabilidade_silencio))
        except RuntimeError:
            if self._dispositivo_ativo != "cuda":
                raise
            from faster_whisper import WhisperModel
            # CTranslate2 pode aceitar a GPU no carregamento e só revelar CUDA
            # incompleto ao executar o encoder (por exemplo, cuBLAS ausente).
            self._modelo = WhisperModel(self.modelo_nome, device="cpu", compute_type="int8")
            self._dispositivo_ativo = "cpu"
            self._compute_type_ativo = "int8"
            log.warning(
                "stt_cuda_execucao_indisponivel modelo=%s fallback=cpu compute_type=int8",
                self.modelo_nome,
            )
            return self.transcrever(audio)
        texto = " ".join(p for p in partes if p).strip()
        return Transcricao(texto, sum(probabilidades) / len(probabilidades) if probabilidades else 0.0)


def preparar_modelo_parakeet() -> Path:
    """Baixa a exportação ONNX int8 oficial do sherpa-onnx na primeira execução."""
    nome = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    raiz = RAIZ_PROJETO / "dados" / "modelos"
    destino = raiz / nome
    arquivos = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    if all((destino / arquivo).is_file() for arquivo in arquivos):
        return destino
    raiz.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{nome}.tar.bz2"
    pacote = raiz / f"{nome}.tar.bz2"
    parcial = pacote.with_suffix(".tar.bz2.part")
    print("[voz] Baixando o modelo Parakeet TDT v3 ONNX int8 (aprox. 640 MB).")
    _baixar_com_retomada(url, parcial)
    parcial.replace(pacote)
    try:
        print("\n[voz] Extraindo o modelo Parakeet.")
        with tarfile.open(pacote, "r:bz2") as arquivo:
            membros = [m for m in arquivo.getmembers() if m.name.startswith(nome + "/")]
            if not membros or any(
                Path(m.name).is_absolute() or ".." in Path(m.name).parts
                or m.issym() or m.islnk()
                for m in membros
            ):
                raise RuntimeError("Pacote do Parakeet inválido")
            arquivo.extractall(raiz, members=membros)
    except Exception as erro:
        raise RuntimeError(f"Não foi possível preparar o Parakeet ({type(erro).__name__}).") from erro
    finally:
        pacote.unlink(missing_ok=True)
    if not all((destino / arquivo).is_file() for arquivo in arquivos):
        raise RuntimeError("O pacote baixado não contém os arquivos esperados do Parakeet")
    return destino


def _baixar_com_retomada(url: str, parcial: Path) -> None:
    """Baixa em blocos, retomando Range e preservando progresso entre execuções."""
    tentativas = 5
    for tentativa in range(1, tentativas + 1):
        recebido = parcial.stat().st_size if parcial.exists() else 0
        requisicao = urllib.request.Request(url)
        if recebido:
            requisicao.add_header("Range", f"bytes={recebido}-")
        try:
            with urllib.request.urlopen(requisicao, timeout=180) as resposta:
                parcial_da_resposta = resposta.status == 206
                if recebido and not parcial_da_resposta:
                    # O servidor ignorou Range: substitui o arquivo incompleto pelo envio integral.
                    recebido = 0
                elif parcial_da_resposta:
                    faixa = resposta.headers.get("Content-Range", "")
                    inicio = faixa.partition(" ")[2].partition("-")[0]
                    if not inicio.isdigit() or int(inicio) != recebido:
                        raise RuntimeError("O servidor retornou uma faixa inesperada do modelo")
                total_conteudo = resposta.headers.get("Content-Length")
                total = recebido + int(total_conteudo) if total_conteudo and total_conteudo.isdigit() else 0
                faixa_total = resposta.headers.get("Content-Range", "").rpartition("/")[2]
                if faixa_total.isdigit():
                    total = int(faixa_total)
                modo = "ab" if parcial_da_resposta and recebido else "wb"
                with parcial.open(modo) as saida:
                    while bloco := resposta.read(1024 * 1024):
                        saida.write(bloco)
                        recebido += len(bloco)
                        if total:
                            print(f"\r[voz] Download Parakeet: {min(100, recebido * 100 // total)}%", end="", flush=True)
                if not total or recebido >= total:
                    return
                raise ConnectionError("download terminou antes do tamanho informado pelo servidor")
        except (TimeoutError, urllib.error.URLError, OSError, ConnectionError) as erro:
            if tentativa == tentativas:
                raise RuntimeError(
                    f"Download interrompido após {tentativas} tentativas; "
                    f"{parcial.stat().st_size if parcial.exists() else 0} bytes foram preservados para retomar."
                ) from erro
            print(f"\n[voz] Conexão interrompida; retomando o download ({tentativa}/{tentativas}).")
            time.sleep(min(2 ** (tentativa - 1), 8))


def _audio_sem_nivel_de_fala(audio: Any) -> bool:
    """Recusa silêncio quase digital antes que o Whisper invente uma transcrição."""
    try:
        import numpy as np
        sinal = np.asarray(audio, dtype=np.float32).reshape(-1)
    except (ImportError, TypeError, ValueError):
        return False
    if sinal.size < 800 or not np.all(np.isfinite(sinal)):
        return True
    rms = float(np.sqrt(np.mean(np.square(sinal), dtype=np.float64)))
    pico = float(np.max(np.abs(sinal)))
    return rms < 0.0008 or pico < 0.003


def preparar_audio_para_stt(audio: Any):
    """Reduz ruído estacionário e normaliza o nível sem alterar o áudio original."""
    if isinstance(audio, (list, tuple)) and len(audio) < 512:
        return audio
    try:
        import numpy as np
    except ImportError:
        # O extra de voz instala NumPy; manter a entrada permite mocks e usos sem DSP.
        return audio
    if not hasattr(np, "asarray"):
        return audio

    sinal = np.asarray(audio, dtype=np.float32).reshape(-1).copy()
    if sinal.size < 512 or not np.all(np.isfinite(sinal)):
        return sinal

    sinal -= np.mean(sinal, dtype=np.float64)
    tamanho, passo = 512, 160
    preenchido = np.pad(sinal, (tamanho // 2, tamanho // 2))
    inicio = np.arange(0, max(1, preenchido.size - tamanho + 1), passo)
    janela = np.hanning(tamanho).astype(np.float32)
    quadros = np.stack([preenchido[i:i + tamanho] * janela for i in inicio])
    espectro = np.fft.rfft(quadros, axis=1)
    magnitude = np.abs(espectro)

    # Os quadros de menor energia estimam o ruído ambiente constante da captura.
    energia = np.sqrt(np.mean(quadros * quadros, axis=1))
    quantidade_ruido = max(1, int(np.ceil(len(energia) * 0.2)))
    indices_ruido = np.argsort(energia)[:quantidade_ruido]
    perfil_ruido = np.median(magnitude[indices_ruido], axis=0, keepdims=True)
    ganho = np.maximum(0.12, 1.0 - 1.15 * perfil_ruido / (magnitude + 1e-7))
    filtrado = np.fft.irfft(espectro * ganho, n=tamanho, axis=1).astype(np.float32)

    saida = np.zeros(preenchido.size, dtype=np.float32)
    peso = np.zeros(preenchido.size, dtype=np.float32)
    janela_suave = janela * janela
    for quadro, posicao in zip(filtrado, inicio):
        saida[posicao:posicao + tamanho] += quadro * janela
        peso[posicao:posicao + tamanho] += janela_suave
    saida = saida[tamanho // 2:tamanho // 2 + sinal.size] / np.maximum(
        peso[tamanho // 2:tamanho // 2 + sinal.size], 1e-6
    )

    rms = float(np.sqrt(np.mean(saida * saida)))
    if rms > 1e-4:
        saida *= min(4.0, 0.1 / rms)
    pico = float(np.max(np.abs(saida)))
    if pico > 0.95:
        saida *= 0.95 / pico
    return saida.astype(np.float32, copy=False)


_HESITACOES = re.compile(
    r"(?:(?<!\w)(?:ã+h+|ah+|a+h+m+|h+m+|hum+)(?!\w)|(?:^|[,;:]\s*)é(?=\.{2,}|[,;:]|\s+[,;:])\.{0,3}[,;:]?\s*|\btipo(?:,|\.\.\.)\s*)",
    re.IGNORECASE,
)
_REPETICAO = re.compile(r"\b([\wÀ-ÿ]+)(?:\s+\1\b)+", re.IGNORECASE)
_AUTOCORRECAO = re.compile(r",\s*não\s*,\s*([^,.!?;]+)", re.IGNORECASE)
_PREPOSICAO_FINAL = re.compile(r"\s+(do|da|de|dos|das|no|na|nos|nas|em|para|pra|pro|pelas?|pelos?)\s+.+$", re.IGNORECASE)
_PREPOSICAO_INICIAL = re.compile(r"^(?:do|da|de|dos|das|no|na|nos|nas|em|para|pra|pro|pelas?|pelos?)\b", re.IGNORECASE)


def normalizar_transcricao_pt_br(texto: str) -> str:
    """Remove hesitações e repetições simples e aplica a correção mais recente."""
    correcao = _AUTOCORRECAO.search(texto)
    if correcao:
        prefixo = texto[:correcao.start()].rstrip()
        substituto = correcao.group(1).strip()
        alvo = _PREPOSICAO_FINAL.search(prefixo)
        if alvo:
            if _PREPOSICAO_INICIAL.match(substituto):
                prefixo = prefixo[:alvo.start()].rstrip()
            else:
                prefixo = prefixo[:alvo.end() - len(alvo.group(0).split()[-1])].rstrip()
        texto = f"{prefixo} {substituto}".strip()
    texto = _HESITACOES.sub(" ", texto)
    texto = _REPETICAO.sub(r"\1", texto)
    return re.sub(r"\s+", " ", texto).strip(" ,;:")
