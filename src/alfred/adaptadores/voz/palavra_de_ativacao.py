"""Interface substituível para palavra de ativação; inclui push-to-talk."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DetectorDePalavraDeAtivacao(Protocol):
    def detectar(self, frame: Any) -> bool: ...


class DetectorOpenWakeWord:
    def __init__(self, modelo: str = "hey_jarvis", limiar: float = 0.5, palavra_desejada: str = "Alfred") -> None:
        self.modelo_nome, self.limiar, self._modelo = modelo, limiar, None
        self.palavra_desejada = palavra_desejada
        self._buffer = None

    def carregar(self) -> None:
        try:
            from openwakeword.model import Model
        except ImportError:
            raise RuntimeError("openWakeWord ausente; instale o extra alfred[voz]") from None
        arquivo = Path(self.modelo_nome)
        modelo = str(arquivo) if arquivo.is_file() else self.modelo_nome
        self._modelo = Model(wakeword_models=[modelo], inference_framework="onnx")

    def detectar(self, frame: Any) -> bool:
        if self._modelo is None:
            self.carregar()
        import numpy as np
        dados = (np.asarray(frame, dtype=np.float32) * 32767).astype(np.int16)
        if self._buffer is None:
            self._buffer = np.empty(0, dtype=np.int16)
        self._buffer = np.concatenate((self._buffer, dados))
        detectada = False
        while self._buffer.size >= 1280:
            janela, self._buffer = self._buffer[:1280], self._buffer[1280:]
            resultados = self._modelo.predict(janela)
            detectada = detectada or any(float(p) >= self.limiar for p in resultados.values())
        return detectada


class AtivacaoManual:
    """Detector simples para injeção de sinal pelo teclado/testes."""
    def __init__(self) -> None:
        self.ativado = False

    def ativar(self) -> None:
        self.ativado = True

    def detectar(self, frame: Any) -> bool:
        ativado, self.ativado = self.ativado, False
        return ativado
