"""Utilitários puros para dividir fala e adaptar iteradores síncronos ao asyncio."""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any


class DivisorDeFrases:
    """Retém trechos incompletos e evita abreviações e decimais comuns."""

    ABREVIACOES = ("Sr.", "Sra.", "Dr.", "Dra.", "etc.", "p.ex.", "ex.", " min.")

    def __init__(self, *, limite_sem_pontuacao: int | None = None) -> None:
        self._buffer = ""
        self.limite_sem_pontuacao = limite_sem_pontuacao

    def adicionar(self, trecho: str) -> list[str]:
        self._buffer += trecho
        frases: list[str] = []
        while True:
            limite = self._fim_de_frase(self._buffer)
            if limite is None and self.limite_sem_pontuacao is not None:
                limite = self._limite_por_tamanho(self._buffer)
            if limite is None:
                break

            frase = self._buffer[:limite].strip()
            self._buffer = self._buffer[limite:].lstrip()
            if frase:
                frases.append(frase)
        return frases

    def finalizar(self) -> str | None:
        frase, self._buffer = self._buffer.strip(), ""
        return frase or None

    def _limite_por_tamanho(self, texto: str) -> int | None:
        limite = self.limite_sem_pontuacao
        if limite is None or len(texto) < limite:
            return None
        corte = texto.rfind(" ", 0, limite + 1)
        return corte + 1 if corte > 0 else None

    @classmethod
    def _fim_de_frase(cls, texto: str) -> int | None:
        for indice, caractere in enumerate(texto):
            if caractere == "\n":
                return indice + 1
            if caractere == "," and len(texto[:indice]) >= 80:
                return indice + 1
            if caractere not in ".!?…":
                continue
            if cls._ponto_nao_final(texto, indice, caractere):
                continue
            if indice + 1 < len(texto) and texto[indice + 1].isspace():
                return indice + 1
        return None

    @classmethod
    def _ponto_nao_final(cls, texto: str, indice: int, caractere: str) -> bool:
        if caractere != ".":
            return False
        decimal = (
            indice > 0
            and indice + 1 < len(texto)
            and texto[indice - 1].isdigit()
            and texto[indice + 1].isdigit()
        )
        abreviacao = any(
            texto[max(0, indice - len(abreviacao) + 1) : indice + 1].endswith(abreviacao)
            for abreviacao in cls.ABREVIACOES
        )
        return decimal or abreviacao


async def obter_confirmacao(callback: Callable[[], Any]) -> Any:
    """Executa callbacks síncronos ou assíncronos de confirmação."""
    resultado = callback()
    if asyncio.iscoroutine(resultado):
        resultado = await resultado
    return resultado


async def em_thread(iterador: Iterable[Any]) -> AsyncIterator[Any]:
    """Faz ponte limitada de iterador síncrono para asyncio sem bloquear o loop.

    A fila pequena aplica contrapressão ao produtor: se o consumidor estiver
    aguardando o TTS, os eventos do Ollama deixam de se acumular em memória.
    """
    loop = asyncio.get_running_loop()
    fila: asyncio.Queue[tuple[bool, Any]] = asyncio.Queue(maxsize=4)
    sentinela = object()
    parar = threading.Event()
    futuros_pendentes: set[concurrent.futures.Future[Any]] = set()
    trava_futuros = threading.Lock()

    def enviar(item: tuple[bool, Any]) -> bool:
        futuro = asyncio.run_coroutine_threadsafe(fila.put(item), loop)
        with trava_futuros:
            futuros_pendentes.add(futuro)
        try:
            while not parar.is_set():
                try:
                    futuro.result(timeout=0.1)
                    return True
                except concurrent.futures.TimeoutError:
                    continue
                except concurrent.futures.CancelledError:
                    return False
            futuro.cancel()
            return False
        finally:
            with trava_futuros:
                futuros_pendentes.discard(futuro)

    def produzir() -> None:
        try:
            for item in iterador:
                if parar.is_set() or not enviar((True, item)):
                    return
        except BaseException as erro:
            if not parar.is_set():
                enviar((False, erro))
        finally:
            if not parar.is_set():
                enviar((True, sentinela))

    tarefa = asyncio.create_task(asyncio.to_thread(produzir))
    try:
        while True:
            sucesso, item = await fila.get()
            if item is sentinela:
                break
            if not sucesso:
                raise item
            yield item
        await tarefa
    finally:
        parar.set()
        with trava_futuros:
            pendentes = tuple(futuros_pendentes)
        for futuro in pendentes:
            futuro.cancel()
        if not tarefa.done():
            tarefa.cancel()
