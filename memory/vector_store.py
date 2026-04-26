"""
memory/vector_store.py — Camada de memória de longo prazo com banco vetorial.

Utiliza ChromaDB (persistente, local) + Sentence-Transformers para gerar
embeddings sem custo de API externa.

Fluxo:
    1. `add_memory(text, metadata)` — converte texto em embedding e armazena.
    2. `search(query, top_k)` — recupera os `top_k` fragmentos mais similares.
    3. `add_interaction(session_id, user_msg, assistant_msg)` — atalho chamado
       pelo orquestrador ao final de cada interação /chat (persistência automática).

Modelo de embedding padrão: all-MiniLM-L6-v2 (~22 MB, roda 100% local).
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, cast

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "alfred_memory"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class VectorStore:
    """
    Gerencia o banco vetorial ChromaDB com embeddings locais.

    Args:
        persist_directory: Pasta onde o ChromaDB salva os dados em disco.
        collection_name:   Nome da coleção ChromaDB a ser usada.
        embedding_model:   Nome do modelo Sentence-Transformers.
    """

    def __init__(
        self,
        persist_directory: str = "memory/vector_db",
        collection_name: str = _DEFAULT_COLLECTION,
        embedding_model: str = _EMBEDDING_MODEL,
    ) -> None:
        self._persist_dir = persist_directory
        self._collection_name = collection_name

        # Garante que o diretório existe
        os.makedirs(self._persist_dir, exist_ok=True)

        # Carrega o modelo de embedding localmente (download automático na 1ª vez)
        logger.info("Carregando modelo de embedding: %s", embedding_model)
        self._encoder: SentenceTransformer = SentenceTransformer(embedding_model)

        # Cliente ChromaDB com persistência em disco
        self._client = chromadb.PersistentClient(
            path=self._persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Obtém ou cria a coleção (sem embedding_function — usamos os nossos próprios)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},  # distância coseno para semântica
        )
        logger.info(
            "VectorStore pronto | dir=%s | coleção=%s | documentos=%d",
            self._persist_dir,
            self._collection_name,
            self._collection.count(),
        )

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _embed(self, texts: List[str]) -> List[Sequence[float]]:
        """Gera embeddings em batch para uma lista de textos."""
        vectors = self._encoder.encode(texts, show_progress_bar=False)
        return cast(List[Sequence[float]], [v.tolist() for v in vectors])

    @staticmethod
    def _make_id(text: str, salt: str = "") -> str:
        """Gera um ID determinístico e único baseado no conteúdo."""
        payload = (text + salt).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def add_memory(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        """
        Adiciona um fragmento de texto à memória vetorial.

        Args:
            text:     Texto a ser armazenado e indexado.
            metadata: Dicionário livre de metadados (session_id, timestamp, etc.).
            doc_id:   ID único do documento. Gerado automaticamente se omitido.

        Returns:
            O ID do documento inserido.
        """
        if not text.strip():
            raise ValueError("Texto vazio não pode ser adicionado à memória vetorial.")

        final_id = doc_id or self._make_id(text, salt=str(datetime.now(tz=timezone.utc)))
        embeddings = self._embed([text])
        safe_metadata: Dict[str, Any] = metadata or {}

        # ChromaDB exige que metadados sejam str | int | float | bool
        sanitized: Dict[str, Any] = {
            k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
            for k, v in safe_metadata.items()
        }
        sanitized.setdefault(
            "timestamp", datetime.now(tz=timezone.utc).isoformat()
        )

        self._collection.upsert(
            ids=[final_id],
            embeddings=embeddings,  # type: ignore[arg-type]
            documents=[text],
            metadatas=[sanitized],
        )
        logger.debug("Memória adicionada | id=%s | preview=%.60s", final_id, text)
        return final_id

    def search(
        self,
        query: str,
        top_k: int = 3,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca os documentos mais semelhantes à query.

        Args:
            query: Texto de consulta.
            top_k: Número de resultados a retornar.
            where: Filtro opcional de metadados no formato ChromaDB.

        Returns:
            Lista de dicts com chaves: `id`, `document`, `metadata`, `distance`.
        """
        if self._collection.count() == 0:
            return []

        query_embedding = self._embed([query])

        kwargs: Dict[str, Any] = {
            "query_embeddings": query_embedding,
            "n_results": min(top_k, self._collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        ids = results["ids"]        # type: ignore[assignment]
        docs = results["documents"]   # type: ignore[assignment]
        metas = results["metadatas"]  # type: ignore[assignment]
        dists = results["distances"]  # type: ignore[assignment]
        if ids is None or docs is None or metas is None or dists is None:
            return []

        hits: List[Dict[str, Any]] = []
        for i, doc_id in enumerate(ids[0]):
            hits.append(
                {
                    "id": doc_id,
                    "document": docs[0][i],
                    "metadata": metas[0][i],
                    "distance": dists[0][i],
                }
            )

        logger.debug(
            "VectorStore search | query=%.50s | hits=%d", query, len(hits)
        )
        return hits

    def add_interaction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """
        Persiste automaticamente uma interação completa na memória vetorial.

        Armazena os dois lados da conversa como um único fragmento para
        manter a coerência semântica na recuperação.
        """
        text = (
            f"[Usuário]: {user_message}\n"
            f"[Alfred]: {assistant_message}"
        )
        self.add_memory(
            text=text,
            metadata={
                "session_id": session_id,
                "type": "interaction",
                "user_message": user_message[:200],
                "assistant_message": assistant_message[:200],
            },
        )

    def count(self) -> int:
        """Retorna o número total de documentos armazenados."""
        return self._collection.count()

    def delete_by_session(self, session_id: str) -> None:
        """
        Remove todos os documentos de uma sessão específica.
        Ignora se a sessão não tiver documentos.
        """
        try:
            # Verifica se existem documentos antes de tentar deletar
            results = self._collection.get(
                where={"session_id": session_id},
                limit=1,
            )
            if results and results.get("ids"):
                self._collection.delete(where={"session_id": session_id})
                logger.info("VectorStore | sessão removida: %s", session_id)
            else:
                logger.debug("VectorStore | sessão %s não possui documentos", session_id)
        except Exception as exc:
            logger.warning(
                "VectorStore | erro ao remover sessão %s: %s (ignorado)",
                session_id,
                exc,
            )
