"""Identificadores locais baseados em UUID versão 7."""

from __future__ import annotations

import secrets
import time
import uuid


def gerar_uuid7() -> str:
    """Gera UUIDv7 sem depender de uuid.uuid7 (indisponível antes do 3.14)."""

    timestamp_ms = time.time_ns() // 1_000_000
    if not 0 <= timestamp_ms < 2**48:
        raise RuntimeError("Relógio fora do intervalo válido para UUIDv7")
    aleatorio = int.from_bytes(secrets.token_bytes(10), "big")
    rand_a = (aleatorio >> 62) & 0xFFF
    rand_b = aleatorio & ((1 << 62) - 1)
    valor = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=valor))
