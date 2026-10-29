"""Derivação de subchaves conforme HKDF-SHA256 (RFC 5869)."""

from __future__ import annotations

import hashlib
import hmac


ROTULOS_SUBCHAVE = frozenset(
    {"alfred.db", "auditoria.db", "metricas.db", "auditoria.hmac"}
)
TAMANHO_CHAVE = 32
SALT_PADRAO = b"alfred:hkdf-sha256:v1"


def hkdf_sha256(
    material: bytes,
    *,
    salt: bytes = b"",
    info: bytes = b"",
    tamanho: int = TAMANHO_CHAVE,
) -> bytes:
    """Deriva bytes pelo HKDF da RFC 5869, sem dependências externas."""

    if not isinstance(material, bytes) or not material:
        raise ValueError("O material de entrada deve conter bytes")
    if tamanho < 1 or tamanho > 255 * hashlib.sha256().digest_size:
        raise ValueError("O tamanho solicitado excede o limite do HKDF-SHA256")
    salt_efetivo = salt or bytes(hashlib.sha256().digest_size)
    prk = hmac.new(salt_efetivo, material, hashlib.sha256).digest()
    blocos: list[bytes] = []
    anterior = b""
    for contador in range(1, (tamanho + 31) // 32 + 1):
        anterior = hmac.new(
            prk, anterior + info + bytes((contador,)), hashlib.sha256
        ).digest()
        blocos.append(anterior)
    return b"".join(blocos)[:tamanho]


def derivar_subchave(chave_mestra: bytes, rotulo: str) -> bytes:
    """Deriva uma subchave de banco com rótulo permitido e domínio próprio."""

    if rotulo not in ROTULOS_SUBCHAVE:
        raise ValueError("Rótulo de subchave desconhecido")
    if len(chave_mestra) != TAMANHO_CHAVE:
        raise ValueError("A chave-mestra deve conter exatamente 32 bytes")
    return hkdf_sha256(
        chave_mestra,
        salt=SALT_PADRAO,
        info=f"alfred/subchave/{rotulo}".encode("ascii"),
    )
