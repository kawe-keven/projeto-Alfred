"""Síntese local com Piper e reprodução por sounddevice."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from alfred.adaptadores.voz.texto_voz import aplicar_pronuncias, normalizar_texto_para_voz

log = logging.getLogger("alfred.voz")


class SintetizadorDeVoz(Protocol):
    def carregar(self) -> None: ...
    def sintetizar(self, texto: str) -> tuple[Any, int]: ...
    def reproduzir(self, audio: Any, taxa: int, *, ao_inicio: Any = None) -> None: ...
    def parar(self) -> None: ...
    def fechar(self) -> None: ...


class SintetizadorPiper:
    def __init__(
        self,
        modelo: str = "dados/modelos/pt_BR-faber-medium.onnx",
        *,
        length_scale: float = 1.25,
        pronuncias: dict[str, str] | None = None,
    ) -> None:
        self.modelo_nome = modelo
        self.length_scale = length_scale
        self.pronuncias = pronuncias or {}
        self._voz: Any = None
        self._config_sintese: Any = None
        self._sd: Any = None
        self._stream: Any = None
        self._taxa: int | None = None
        self._cache: dict[str, tuple[Any, int]] = {}
        self.latencia_dispositivo_s: float | None = None

    def carregar(self) -> None:
        try:
            import sounddevice as sd
            from piper import PiperVoice, SynthesisConfig
        except ImportError:
            raise RuntimeError("Piper/sounddevice ausentes; instale o extra alfred[voz]") from None
        arquivo = Path(self.modelo_nome)
        if not arquivo.exists():
            raise RuntimeError(
                f"Modelo de voz Piper não encontrado: {self.modelo_nome}. "
                "Execute: python -m piper.download_voices --data-dir dados/modelos pt_BR-faber-medium"
            )
        self._voz = PiperVoice.load(str(arquivo))
        self._config_sintese = SynthesisConfig(length_scale=self.length_scale)
        self._sd = sd
        self._taxa = int(self._voz.config.sample_rate)
        self._stream = sd.OutputStream(
            samplerate=self._taxa, channels=1, dtype="float32",
            blocksize=0, latency="low",
        )
        self._stream.start()
        try:
            self.latencia_dispositivo_s = float(self._stream.latency)
        except (TypeError, ValueError):
            self.latencia_dispositivo_s = None
        latencia_ms = (
            self.latencia_dispositivo_s * 1000
            if self.latencia_dispositivo_s is not None else -1
        )
        log.info("saida_audio taxa_hz=%d bloco=%d latencia_ms=%.0f",
                 self._taxa, self._stream.blocksize, latencia_ms)
        for frase in ("Entendido.",):
            normalizada = normalizar_texto_para_voz(aplicar_pronuncias(frase, self.pronuncias))
            self._cache[normalizada.casefold()] = self._sintetizar_sem_cache(normalizada)

    def sintetizar(self, texto: str) -> tuple[Any, int]:
        if self._voz is None:
            self.carregar()
        normalizado = normalizar_texto_para_voz(aplicar_pronuncias(texto, self.pronuncias))
        em_cache = self._cache.get(normalizado.casefold())
        if em_cache is not None:
            return em_cache
        return self._sintetizar_sem_cache(normalizado)

    def _sintetizar_sem_cache(self, texto: str) -> tuple[Any, int]:
        import numpy as np
        audio = np.concatenate([np.asarray(bloco.audio_float_array, dtype=np.float32)
                                for bloco in self._voz.synthesize(
                                    texto, syn_config=self._config_sintese
                                )])
        return audio, self._taxa

    def reproduzir(self, audio: Any, taxa: int, *, ao_inicio: Any = None) -> None:
        if self._voz is None:
            self.carregar()
        if taxa != self._taxa:
            raise ValueError("A taxa de áudio não corresponde ao stream aberto")
        if self._stream is None:
            raise RuntimeError("Stream de saída indisponível")
        if not self._stream.active:
            self._stream.start()
        if ao_inicio is not None:
            ao_inicio(self.latencia_dispositivo_s or 0.0)
        self._stream.write(audio)

    def parar(self) -> None:
        if self._stream is not None and self._stream.active:
            self._stream.abort()

    def fechar(self) -> None:
        self.parar()
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._voz = None
        self._cache.clear()
