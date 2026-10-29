"""Geração local de embeddings pelo Ollama e alternativa determinística de teste."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


TipoTextoEmbedding = Literal["consulta", "documento"]


class GeradorDeEmbeddings(Protocol):
    """Contrato para criar vetores de consultas e documentos."""

    def gerar_em_lote(
        self, textos: Sequence[str], tipo: TipoTextoEmbedding
    ) -> list[list[float]]:
        ...


class ErroGeracaoEmbeddings(RuntimeError):
    """Erro seguro ao solicitar embeddings, sem incluir o conteúdo enviado."""


class GeradorEmbeddingsOllama:
    """Usa a API local de embeddings do Ollama em lotes limitados."""

    def __init__(
        self,
        modelo: str = "qwen3-embedding:0.6b",
        url_base: str = "http://localhost:11434",
        tempo_limite_s: float = 120.0,
        tamanho_lote: int = 32,
        num_gpu: int = 0,
        num_thread: int = 4,
        keep_alive: str = "1m",
    ) -> None:
        if not modelo.strip():
            raise ValueError("O modelo de embeddings não pode ficar vazio")
        endereco = urlparse(url_base)
        if endereco.scheme != "http" or endereco.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("O Ollama de embeddings deve usar localhost")
        if tempo_limite_s <= 0 or not math.isfinite(tempo_limite_s):
            raise ValueError("O tempo limite deve ser maior que zero")
        if tamanho_lote < 1:
            raise ValueError("O tamanho do lote deve ser maior que zero")
        if num_gpu < 0:
            raise ValueError("O número de camadas na GPU não pode ser negativo")
        if num_thread < 1:
            raise ValueError("O número de threads deve ser maior que zero")
        if not keep_alive.strip():
            raise ValueError("O tempo de retenção do modelo não pode ficar vazio")
        self.modelo = modelo
        self.url_base = url_base.rstrip("/")
        self.tempo_limite_s = tempo_limite_s
        self.tamanho_lote = tamanho_lote
        self.num_gpu = num_gpu
        self.num_thread = num_thread
        self.keep_alive = keep_alive
        self._dimensao: int | None = None

    def gerar_em_lote(
        self, textos: Sequence[str], tipo: TipoTextoEmbedding
    ) -> list[list[float]]:
        if tipo not in {"consulta", "documento"}:
            raise ValueError("O tipo deve ser 'consulta' ou 'documento'")
        if any(not isinstance(texto, str) for texto in textos):
            raise TypeError("Todos os itens devem ser textos")
        if not textos:
            return []

        vetores: list[list[float]] = []
        for inicio in range(0, len(textos), self.tamanho_lote):
            lote = list(textos[inicio : inicio + self.tamanho_lote])
            vetores.extend(self._gerar_lote(lote))
        return vetores

    def _gerar_lote(self, textos: list[str]) -> list[list[float]]:
        corpo = json.dumps(
            {
                "model": self.modelo,
                "input": textos,
                "options": {
                    "num_gpu": self.num_gpu,
                    "num_thread": self.num_thread,
                },
                "keep_alive": self.keep_alive,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        requisicao = Request(
            f"{self.url_base}/api/embed",
            data=corpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(requisicao, timeout=self.tempo_limite_s) as resposta:
                dados = json.loads(resposta.read().decode("utf-8"))
        except HTTPError as erro:
            raise ErroGeracaoEmbeddings(
                f"O Ollama de embeddings respondeu com HTTP {erro.code}"
            ) from None
        except (TimeoutError, URLError, OSError):
            raise ErroGeracaoEmbeddings(
                "Não foi possível obter embeddings do Ollama local"
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErroGeracaoEmbeddings(
                "O Ollama retornou embeddings em formato inválido"
            ) from None

        vetores = dados.get("embeddings") if isinstance(dados, dict) else None
        if not isinstance(vetores, list) or len(vetores) != len(textos):
            raise ErroGeracaoEmbeddings(
                "O Ollama retornou uma quantidade inválida de embeddings"
            )
        resultado: list[list[float]] = []
        for vetor in vetores:
            if not isinstance(vetor, list) or not vetor:
                raise ErroGeracaoEmbeddings("O Ollama retornou um vetor inválido")
            if any(
                isinstance(valor, bool)
                or not isinstance(valor, (int, float))
                or not math.isfinite(valor)
                for valor in vetor
            ):
                raise ErroGeracaoEmbeddings("O Ollama retornou um vetor inválido")
            if self._dimensao is None:
                self._dimensao = len(vetor)
            if len(vetor) != self._dimensao:
                raise ErroGeracaoEmbeddings(
                    "O modelo de embeddings retornou dimensão inconsistente"
                )
            resultado.append([float(valor) for valor in vetor])
        return resultado


class GeradorFalso:
    """Gera vetores determinísticos a partir de textos fictícios de teste."""

    def __init__(self, dimensao: int = 32) -> None:
        if dimensao < 1:
            raise ValueError("A dimensão deve ser maior que zero")
        self.dimensao = dimensao

    def gerar_em_lote(
        self, textos: Sequence[str], tipo: TipoTextoEmbedding
    ) -> list[list[float]]:
        if tipo not in {"consulta", "documento"}:
            raise ValueError("O tipo deve ser 'consulta' ou 'documento'")
        vetores = []
        for texto in textos:
            if not isinstance(texto, str):
                raise TypeError("Todos os itens devem ser textos")
            vetor = []
            for indice in range(self.dimensao):
                digest = hashlib.blake2b(
                    f"{indice}:{texto}".encode("utf-8"), digest_size=8
                ).digest()
                valor = int.from_bytes(digest, "big") / (2**64 - 1)
                vetor.append(valor * 2 - 1)
            norma = math.sqrt(sum(valor * valor for valor in vetor))
            vetores.append([valor / norma for valor in vetor])
        return vetores
