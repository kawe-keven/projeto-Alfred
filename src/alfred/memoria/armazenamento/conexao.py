"""Conexões SQLCipher configuradas e fechadas explicitamente."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as erro:  # pragma: no cover - depende da instalação do projeto
    raise RuntimeError("sqlcipher3 é obrigatório; SQLite sem cifra não é suportado") from erro


T = TypeVar("T")
_travas_escrita: dict[str, threading.RLock] = {}
_travas_escrita_guarda = threading.Lock()


class ErroConexaoSQLCipher(RuntimeError):
    """Falha segura ao abrir ou configurar uma base cifrada."""


def _trava_para(caminho: Path) -> threading.RLock:
    identificador = str(caminho.resolve()).casefold()
    with _travas_escrita_guarda:
        trava = _travas_escrita.get(identificador)
        if trava is None:
            trava = threading.RLock()
            _travas_escrita[identificador] = trava
        return trava


@contextmanager
def abrir_conexao(
    caminho: str | Path,
    chave: bytes,
    *,
    finalidade: str = "dados",
    busy_timeout_ms: int = 5000,
    escritor: bool = True,
) -> Iterator[sqlcipher.Connection]:
    """Abre SQLCipher, aplica PRAGMAs e sempre faz checkpoint e fecha."""

    if not isinstance(chave, bytes) or len(chave) != 32:
        raise ErroConexaoSQLCipher("A chave SQLCipher deve conter 32 bytes")
    if finalidade not in {"dados", "auditoria", "metricas"}:
        raise ValueError("Finalidade de banco inválida")
    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms não pode ser negativo")
    arquivo = Path(caminho)
    trava = _trava_para(arquivo) if escritor else None
    if trava is not None:
        trava.acquire()
    conexao = None
    try:
        era_vazio = not arquivo.exists() or arquivo.stat().st_size == 0
        conexao = sqlcipher.connect(str(arquivo), timeout=busy_timeout_ms / 1000)
        # A interpolação contém somente o hexadecimal de bytes validados acima.
        hexadecimal = chave.hex()
        conexao.execute(f'PRAGMA key = "x\'{hexadecimal}\'"')
        versao_cifra = conexao.execute("PRAGMA cipher_version").fetchone()
        if not versao_cifra or not versao_cifra[0]:
            raise ErroConexaoSQLCipher("A conexão não carregou SQLCipher")
        # Consultar o esquema comprova a chave antes de qualquer criação.
        conexao.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conexao.execute("PRAGMA foreign_keys=ON")
        conexao.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        modo_sync = "FULL" if finalidade == "auditoria" else "NORMAL"
        conexao.execute(f"PRAGMA synchronous={modo_sync}")
        conexao.execute("PRAGMA secure_delete=ON")
        conexao.execute("PRAGMA cipher_memory_security=ON")
        if era_vazio:
            conexao.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.row_factory = sqlcipher.Row
    except ErroConexaoSQLCipher:
        if conexao is not None:
            conexao.close()
        if trava is not None:
            trava.release()
        raise
    except Exception:
        if conexao is not None:
            conexao.close()
        if trava is not None:
            trava.release()
        # Não propaga mensagens do driver, que podem incluir estado do banco.
        raise ErroConexaoSQLCipher(
            "Não foi possível abrir o banco cifrado; confira a chave e a disponibilidade do arquivo"
        ) from None
    try:
        yield conexao
    finally:
        try:
            conexao.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except Exception:
            # O fechamento continua obrigatório mesmo se outro leitor impedir o checkpoint.
            pass
        finally:
            conexao.close()
        if trava is not None:
            trava.release()


async def executar_em_thread(funcao: Callable[..., T], /, *args: object, **kwargs: object) -> T:
    """Executa uma operação síncrona de armazenamento fora do laço de voz."""

    return await asyncio.to_thread(funcao, *args, **kwargs)


async def usar_conexao_async(
    funcao: Callable[..., T],
    caminho: str | Path,
    chave: bytes,
    /,
    *args: object,
    finalidade: str = "dados",
    escritor: bool = True,
    **kwargs: object,
) -> T:
    """Executa callback com conexão criada e fechada na mesma thread."""

    def executar() -> T:
        with abrir_conexao(
            caminho, chave, finalidade=finalidade, escritor=escritor
        ) as conexao:
            return funcao(conexao, *args, **kwargs)

    return await asyncio.to_thread(executar)
