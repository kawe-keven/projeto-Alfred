"""
memory/memory_manager.py — Gerenciamento de memória conversacional via SQLite.

Schema:
    conversations(id, session_id, role, content, timestamp, metadata)

Para migrar para um backend diferente (Redis, Postgres, etc.),
basta criar uma nova classe que implemente a mesma interface pública.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS conversations (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT    NOT NULL,
        role       TEXT    NOT NULL,
        content    TEXT    NOT NULL,
        timestamp  TEXT    NOT NULL,
        metadata   TEXT    NOT NULL DEFAULT '{}'
    );
"""

_CREATE_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_session_id
    ON conversations (session_id);
"""


class MemoryManager:
    """
    Persiste e recupera histórico de conversas usando SQLite.

    Args:
        db_path: Caminho para o arquivo .db.
                 O diretório é criado automaticamente se não existir.
    """

    def __init__(self, db_path: str = "memory/alfred_memory.db") -> None:
        self._db_path = db_path
        self._ensure_directory()
        self._init_db()

    # ------------------------------------------------------------------
    # Setup interno
    # ------------------------------------------------------------------

    def _ensure_directory(self) -> None:
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()
        logger.debug("MemoryManager initialized | db=%s", self._db_path)

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persiste uma mensagem no histórico da sessão."""
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (session_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, timestamp, metadata_json),
            )
            conn.commit()

    def get_history(
        self, session_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Retorna as últimas `limit` mensagens da sessão em ordem cronológica.

        Returns:
            Lista de dicts com chaves: id, session_id, role, content,
            timestamp, metadata (já deserializado).
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, role, content, timestamp, metadata
                FROM conversations
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()

        history = []
        for row in reversed(rows):
            entry = dict(row)
            entry["metadata"] = json.loads(entry["metadata"])
            history.append(entry)

        return history

    def clear_session(self, session_id: str) -> None:
        """
        Remove todo o histórico de uma sessão específica.
        Retorna silenciosamente se a sessão não existir.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM conversations WHERE session_id = ?",
                    (session_id,),
                )
                deleted_count = cursor.rowcount
                conn.commit()
                if deleted_count > 0:
                    logger.info(
                        "MemoryManager | sessão %s limpa (%d mensagens removidas)",
                        session_id,
                        deleted_count,
                    )
                else:
                    logger.debug("MemoryManager | sessão %s não possui histórico", session_id)
        except Exception as exc:
            logger.error("MemoryManager | erro ao limpar sessão %s: %s", session_id, exc)
            raise

    def list_sessions(self) -> List[str]:
        """Retorna todos os session_ids únicos armazenados."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT session_id FROM conversations ORDER BY id ASC"
            )
            return [row["session_id"] for row in cursor.fetchall()]
