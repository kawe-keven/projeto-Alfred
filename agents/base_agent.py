"""
agents/base_agent.py — Contrato base para todos os agentes do Alfred.

Todo novo agente deve:
  1. Herdar de BaseAgent.
  2. Implementar o método `process`.
  3. Passar um `name` único ao construtor pai.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAgent(ABC):
    """Interface abstrata que todos os agentes do Alfred devem implementar."""

    def __init__(self, name: str) -> None:
        self.name: str = name

    @abstractmethod
    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
    ) -> str:
        """
        Processa a mensagem do usuário e retorna a resposta.

        Args:
            message:      Mensagem atual do usuário.
            history:      Histórico da conversa (lista de dicts role/content).
            session_id:   Identificador da sessão corrente.
            rag_contexts: Contextos recuperados da memória vetorial (RAG).

        Returns:
            Texto de resposta do agente.
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
