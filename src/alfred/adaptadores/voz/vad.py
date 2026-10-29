"""Detecção local de início e fim de fala com Silero VAD."""

from __future__ import annotations

import re
from typing import Any


# O microfone pode captar fala baixa abaixo de -50 dBFS. O Silero continua
# decidindo se o quadro contém voz; este piso só evita inferência em silêncio
# quase digital.
_LIMIAR_RMS_SILENCIO = 0.001


class DetectorDeVoz:
    def __init__(self, limiar_inicio: float = 0.5, limiar_fim: float = 0.35,
                 silencio_fim: int = 14, silencio_fim_hesitacao: int = 30,
                 limiar_interrupcao: float = 0.85,
                 frames_minimos_interrupcao: int = 4) -> None:
        if not 0 < limiar_fim <= limiar_inicio <= 1:
            raise ValueError("Limiar VAD inválido")
        if silencio_fim < 1 or silencio_fim_hesitacao < silencio_fim:
            raise ValueError("Os tempos de silêncio devem ser positivos e crescentes")
        if not 0 < limiar_interrupcao <= 1 or frames_minimos_interrupcao < 1:
            raise ValueError("Parâmetros de interrupção inválidos")
        self.limiar_inicio, self.limiar_fim = limiar_inicio, limiar_fim
        self.limiar_interrupcao = limiar_interrupcao
        self.silencio_fim = silencio_fim
        self.silencio_fim_hesitacao = silencio_fim_hesitacao
        self.frames_minimos_interrupcao = frames_minimos_interrupcao
        self._model: Any = None
        self._em_fala = False
        self._silencio = 0
        self._interrupcao_frames = 0

    @property
    def silencio_frames(self) -> int:
        return self._silencio

    def carregar(self) -> None:
        try:
            from silero_vad import load_silero_vad
        except ImportError:
            raise RuntimeError("Silero VAD ausente; instale o extra alfred[voz]") from None
        self._model = load_silero_vad(onnx=True)

    def probabilidade(self, frame: Any) -> float:
        if self._model is None:
            self.carregar()
        import numpy as np
        # A captura trabalha em blocos de 20–30 ms. Silero aceita janelas de
        # 256 ou 512 amostras a 16 kHz; completar a janela não muda o áudio guardado.
        amostras_np = np.asarray(frame, dtype=np.float32).reshape(-1)
        # O modo contínuo recebe ~33 frames/s mesmo em silêncio. Evitar chamar
        # o modelo ONNX nesse caso reduz o trabalho permanente da CPU.
        if float(np.sqrt(np.mean(np.square(amostras_np)))) < _LIMIAR_RMS_SILENCIO:
            return 0.0
        import torch
        if amostras_np.size < 512:
            amostras_np = np.pad(amostras_np, (0, 512 - amostras_np.size))
        elif amostras_np.size > 512:
            amostras_np = amostras_np[:512]
        amostras = torch.from_numpy(amostras_np.copy())
        return float(self._model(amostras, 16000).item())

    def processar(self, frame: Any, *, durante_fala: bool = False,
                  texto_parcial: str = "") -> tuple[str, Any | None]:
        prob = self.probabilidade(frame)
        if durante_fala:
            if prob >= self.limiar_interrupcao:
                self._interrupcao_frames += 1
                if self._interrupcao_frames >= self.frames_minimos_interrupcao:
                    self._interrupcao_frames = 0
                    return "interromper", frame
            else:
                self._interrupcao_frames = 0
            return "continuar", None
        if not self._em_fala and prob >= self.limiar_inicio:
            self._em_fala, self._silencio = True, 0
            return "inicio", frame
        if self._em_fala:
            if prob >= self.limiar_fim:
                self._silencio = 0
            else:
                self._silencio += 1
            # Sem uma hipótese parcial, encerra pelo limite normal. Esperar o
            # limite longo quando o texto está vazio adicionava até 1,3 s a
            # toda fala no modo local.
            limite_silencio = (self.silencio_fim_hesitacao
                               if texto_parcial.strip() and _frase_incompleta(texto_parcial)
                               else self.silencio_fim)
            if self._silencio >= limite_silencio:
                self._em_fala, self._silencio = False, 0
                return "fim", frame
        return "continuar", None

    def resetar(self) -> None:
        self._em_fala, self._silencio = False, 0
        self._interrupcao_frames = 0
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()

    def registrar_interrupcao(self, frame: Any) -> None:
        """Inicia um turno a partir da fala que interrompeu o TTS."""
        self.resetar()
        # O VAD já confirmou fala sustentada em modo de interrupção. Atualiza
        # o estado recorrente com o frame atual e mantém o turno aberto.
        self.probabilidade(frame)
        self._em_fala = True
        self._silencio = 0


_FIM_INCOMPLETO = re.compile(
    r"(?:\b(?:é|tipo|então|e|mas|porque|pera(?:í)?|como|se|que)\s*|[.…]{2,})$",
    re.IGNORECASE,
)


def _frase_incompleta(texto: str) -> bool:
    return bool(_FIM_INCOMPLETO.search(texto.strip()))
