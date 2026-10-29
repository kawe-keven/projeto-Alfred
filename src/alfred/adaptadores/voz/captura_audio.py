"""Captura mono em memória; callback apenas encaminha frames para asyncio."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

log = logging.getLogger("alfred.voz")


class CapturaAudio:
    def __init__(self, fila: asyncio.Queue, taxa: int = 16000, bloco: int = 480) -> None:
        self.fila, self.taxa, self.bloco = fila, taxa, bloco
        self._stream: Any = None
        self._max_frames_pendentes = max(1, fila.maxsize or 16)
        self._frames_pendentes: deque[Any] = deque()
        self._trava_frames = threading.Lock()
        self._despacho_agendado = False
        self._frames_descartados = 0

    async def iniciar(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            raise RuntimeError("Dependência de áudio ausente; instale o extra alfred[voz]") from None
        loop = asyncio.get_running_loop()
        def callback(indata, frames, time_info, status):
            dados = indata[:, 0].copy()
            self._receber_frame(loop, dados)
        self._stream = sd.InputStream(samplerate=self.taxa, channels=1, dtype="float32",
                                      blocksize=self.bloco, callback=callback)
        try:
            await asyncio.to_thread(self._stream.start)
        except Exception:
            self._stream = None
            raise RuntimeError("Microfone indisponível") from None

    async def frames(self) -> AsyncIterator[Any]:
        while True:
            yield await self.fila.get()

    async def fechar(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            await asyncio.to_thread(stream.stop)
            await asyncio.to_thread(stream.close)
        if self._frames_descartados:
            log.warning("captura_frames_descartados quantidade=%d", self._frames_descartados)

    def _receber_frame(self, loop: asyncio.AbstractEventLoop, frame: Any) -> None:
        """Mantém um buffer limitado e no máximo um callback de drenagem pendente."""
        with self._trava_frames:
            if len(self._frames_pendentes) >= self._max_frames_pendentes:
                self._frames_pendentes.popleft()
                self._frames_descartados += 1
            self._frames_pendentes.append(frame)
            if self._despacho_agendado:
                return
            self._despacho_agendado = True
        try:
            loop.call_soon_threadsafe(self._despachar_frames)
        except RuntimeError:
            with self._trava_frames:
                self._despacho_agendado = False
                self._frames_pendentes.clear()

    def _despachar_frames(self) -> None:
        while True:
            with self._trava_frames:
                if not self._frames_pendentes:
                    self._despacho_agendado = False
                    return
                frame = self._frames_pendentes.popleft()
            if _inserir_frame(self.fila, frame):
                with self._trava_frames:
                    self._frames_descartados += 1


def _inserir_frame(fila: asyncio.Queue, frame: Any) -> bool:
    # Descarta o frame mais antigo em sobrecarga para manter a escuta próxima
    # do tempo real e impedir crescimento ilimitado de memória/latência.
    descartou = False
    if fila.full():
        try:
            fila.get_nowait()
            descartou = True
        except asyncio.QueueEmpty:
            pass
    fila.put_nowait(frame)
    return descartou
