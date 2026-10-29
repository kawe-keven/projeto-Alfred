"""Compatibilidade pontual para a introspecção assíncrona do ChromaDB."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from types import SimpleNamespace


def preparar_chromadb() -> None:
    """Usa a API vigente de inspect no decorador de telemetria do ChromaDB.

    O ChromaDB 1.5.9 ainda consulta ``asyncio.iscoroutinefunction``, removida
    no Python 3.16. A substituição fica restrita ao módulo de telemetria dele;
    o módulo global ``asyncio`` do Alfred permanece intacto.
    """
    original = asyncio.iscoroutinefunction
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction
    try:
        telemetria = importlib.import_module("chromadb.telemetry.opentelemetry")
    finally:
        asyncio.iscoroutinefunction = original
    telemetria.asyncio = SimpleNamespace(
        iscoroutinefunction=inspect.iscoroutinefunction
    )
