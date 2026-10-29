"""Contrato dos provedores de modelos de linguagem."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class Mensagem:
    papel: Literal["user", "assistant", "tool"]
    conteudo: str
    nome_ferramenta: str | None = None
    chamadas_ferramenta: tuple["ChamadaFerramenta", ...] = ()


@dataclass(frozen=True)
class ChamadaFerramenta:
    nome: str
    argumentos: object


@dataclass(frozen=True)
class EventoLLM:
    texto: str = ""
    chamadas: tuple[ChamadaFerramenta, ...] = ()


@runtime_checkable
class ProvedorLLM(Protocol):
    """Interface mínima para enviar uma mensagem e receber uma resposta."""

    def conversar(self, mensagens: Sequence[Mensagem], *, sistema: str) -> Iterator[str]:
        """Gera trechos de texto para o histórico e o prompt fornecidos."""
        ...


@runtime_checkable
class ProvedorLLMComFerramentas(Protocol):
    """Contrato estendido para streaming e chamadas tipadas de ferramentas."""

    def conversar_com_ferramentas(
        self,
        mensagens: Sequence[Mensagem],
        *,
        sistema: str,
        ferramentas: list[dict],
    ) -> Iterator[EventoLLM]:
        ...


class ErroProvedorLLM(RuntimeError):
    """Falha de comunicação ou resposta inválida de um provedor LLM."""


class ErroConexaoOllama(ErroProvedorLLM):
    """O servidor Ollama não está acessível."""


class ModeloOllamaNaoInstalado(ErroProvedorLLM):
    """O modelo solicitado não está instalado no Ollama local."""


class RespostaOllamaMalformada(ErroProvedorLLM):
    """O Ollama retornou dados que não seguem o protocolo esperado."""


class TempoEsgotadoOllama(ErroProvedorLLM):
    """A chamada ao Ollama excedeu o tempo limite configurado."""
