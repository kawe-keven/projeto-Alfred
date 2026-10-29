"""Infraestrutura isolada para os testes de memória do Alfred.

Tudo que escreve usa exclusivamente o diretório temporário do próprio teste.
"""

from __future__ import annotations

import secrets
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

import pytest

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.embeddings import TipoTextoEmbedding
from alfred.memoria.armazenamento.metricas import ArmazenamentoDeMetricas
from alfred.memoria.armazenamento.migracao import aplicar_migracoes
from alfred.memoria.armazenamento.vetorial_chroma import RepositorioVetorialChroma
from alfred.seguranca.auditoria.registro import RegistroDeAuditoria
from alfred.seguranca.chaves.derivacao import derivar_subchave

from .dados_ficticios import criar_eventos_ficticios


RAIZ_PROJETO = Path(__file__).parents[2]
MIGRACOES = RAIZ_PROJETO / "src" / "alfred" / "memoria" / "armazenamento" / "migracoes"
MIGRACOES_METRICAS = (
    RAIZ_PROJETO / "src" / "alfred" / "memoria" / "armazenamento" / "migracoes_metricas"
)
MODELO_CONTROLADO = "vetores-controlados-v1"
DIMENSAO_CONTROLADA = 8


class RelogioFalso:
    """Relógio determinístico que avança apenas quando o teste o solicita."""

    def __init__(self, instante_ms: int = 1_800_000_000_000) -> None:
        self.instante_ms = instante_ms

    def __call__(self) -> int:
        return self.instante_ms

    def avancar(self, milissegundos: int) -> int:
        self.instante_ms += milissegundos
        return self.instante_ms

    def datetime_utc(self) -> datetime:
        return datetime.fromtimestamp(self.instante_ms / 1000, tz=timezone.utc)


class LLMFalso:
    """LLM determinístico que registra o sistema e as mensagens recebidas."""

    def __init__(self, resposta: str = "Resposta fictícia.") -> None:
        self.resposta = resposta
        self.prompts: list[str] = []
        self.mensagens: list[tuple[object, ...]] = []

    def conversar(self, mensagens: Sequence[object], *, sistema: str) -> Iterator[str]:
        self.prompts.append(sistema)
        self.mensagens.append(tuple(mensagens))
        yield self.resposta


class GeradorEmbeddingsControlados:
    """Mapeia textos explicitamente cadastrados para vetores definidos no teste.

    Os vetores servem para verificar ranking e filtros. Não medem qualidade
    semântica e não substituem uma avaliação com um modelo real.
    """

    def __init__(self, dimensao: int = DIMENSAO_CONTROLADA) -> None:
        if dimensao < 1:
            raise ValueError("A dimensão deve ser positiva")
        self.dimensao = dimensao
        self._vetores: dict[str, list[float]] = {}

    def mapear(self, texto: str, vetor: Sequence[float]) -> None:
        if len(vetor) != self.dimensao:
            raise ValueError("Dimensão controlada incompatível")
        self._vetores[self._normalizar(texto)] = [float(valor) for valor in vetor]

    def gerar_em_lote(
        self, textos: Sequence[str], tipo: TipoTextoEmbedding
    ) -> list[list[float]]:
        if tipo not in {"consulta", "documento"}:
            raise ValueError("Tipo de texto incompatível")
        try:
            return [self._vetores[self._normalizar(texto)].copy() for texto in textos]
        except KeyError:
            raise ValueError("Texto sem vetor controlado cadastrado") from None

    @staticmethod
    def _normalizar(texto: str) -> str:
        return " ".join(texto.casefold().split())


@dataclass
class ArmazenamentoTemporario:
    raiz: Path
    chave_mestra: bytes
    relogio: RelogioFalso
    banco: BancoRelacional
    auditoria: RegistroDeAuditoria
    metricas: ArmazenamentoDeMetricas
    chroma: RepositorioVetorialChroma
    stack: ExitStack

    @property
    def caminho_alfred(self) -> Path:
        return self.raiz / "alfred.db"

    @property
    def caminho_auditoria(self) -> Path:
        return self.raiz / "auditoria.db"

    @property
    def caminho_metricas(self) -> Path:
        return self.raiz / "metricas.db"

    @property
    def caminho_chroma(self) -> Path:
        return self.raiz / "chroma"

    @contextmanager
    def conexao(self, caminho: Path, chave: bytes, *, finalidade: str = "dados"):
        """Abre conexão SQLCipher gerenciada até `fechar()` no teardown."""
        yield self.stack.enter_context(abrir_conexao(caminho, chave, finalidade=finalidade))

    def fechar(self) -> None:
        """Fecha primeiro os clientes persistentes, depois conexões SQL abertas."""
        self.chroma.close()
        self.stack.close()


@pytest.fixture
def armazenamento_memoria(tmp_path: Path) -> Iterator[ArmazenamentoTemporario]:
    """Cria três bancos SQLCipher e Chroma sob o tmp_path isolado do teste."""
    chave = secrets.token_bytes(32)
    raiz = tmp_path / "armazenamento-ficticio"
    raiz.mkdir()
    caminho_db = raiz / "alfred.db"
    caminho_auditoria = raiz / "auditoria.db"
    caminho_metricas = raiz / "metricas.db"
    aplicar_migracoes(
        caminho_db,
        derivar_subchave(chave, "alfred.db"),
        pasta_migracoes=MIGRACOES,
    )
    aplicar_migracoes(
        caminho_metricas,
        derivar_subchave(chave, "metricas.db"),
        pasta_migracoes=MIGRACOES_METRICAS,
        finalidade="metricas",
    )

    relogio = RelogioFalso()
    stack = ExitStack()
    repositorio = RepositorioVetorialChroma(
        raiz / "chroma",
        modelo_embeddings=MODELO_CONTROLADO,
        dimensao=DIMENSAO_CONTROLADA,
    )
    contexto = ArmazenamentoTemporario(
        raiz=raiz,
        chave_mestra=chave,
        relogio=relogio,
        banco=BancoRelacional(caminho_db, chave),
        auditoria=RegistroDeAuditoria(
            caminho_auditoria,
            raiz / "auditoria.ancora",
            chave,
            relogio_ms=relogio,
        ),
        metricas=ArmazenamentoDeMetricas(
            caminho_metricas,
            chave,
            relogio_ms=relogio,
        ),
        chroma=repositorio,
        stack=stack,
    )
    contexto.auditoria.verificar_cadeia()
    try:
        yield contexto
    finally:
        contexto.fechar()


@pytest.fixture
def llm_falso() -> LLMFalso:
    return LLMFalso()


@pytest.fixture
def relogio_falso() -> RelogioFalso:
    return RelogioFalso()


@pytest.fixture
def embeddings_controlados() -> GeradorEmbeddingsControlados:
    gerador = GeradorEmbeddingsControlados()
    # Grupos artificiais com similaridade conhecida para testes de ranking.
    gerador.mapear("cafe", (1, 0, 0, 0, 0, 0, 0, 0))
    gerador.mapear("cafe coado", (0.99, 0.1, 0, 0, 0, 0, 0, 0))
    gerador.mapear("cha", (0, 1, 0, 0, 0, 0, 0, 0))
    gerador.mapear("corrida", (0, 0, 1, 0, 0, 0, 0, 0))
    return gerador


@pytest.fixture
def eventos_ficticios():
    return criar_eventos_ficticios()
