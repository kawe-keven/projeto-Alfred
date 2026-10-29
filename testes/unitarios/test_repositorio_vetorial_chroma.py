from __future__ import annotations

import socket
import asyncio
import inspect
import warnings
from pathlib import Path

import pytest

from alfred.memoria.armazenamento.vetorial_chroma import (
    ErroRepositorioVetorial,
    RepositorioVetorialChroma,
)


MODELO = "teste-falso-multilingue"
METADADOS = {
    "tipo": "memoria",
    "data": 1_800_000_000_000,
    "importancia": 50,
    "estado": "ativa",
}


def test_compatibilidade_usa_inspect_sem_aviso_depreciacao(tmp_path: Path) -> None:
    referencia_asyncio = asyncio.iscoroutinefunction
    with warnings.catch_warnings(record=True) as capturados:
        warnings.simplefilter("always", DeprecationWarning)
        repositorio = RepositorioVetorialChroma(
            tmp_path / "chroma-compat", modelo_embeddings=MODELO, dimensao=3
        )
        repositorio.close()
    modulo = __import__("chromadb.telemetry.opentelemetry", fromlist=["asyncio"])

    async def coroutine():
        return None

    assert modulo.asyncio.iscoroutinefunction is inspect.iscoroutinefunction
    assert modulo.asyncio.iscoroutinefunction(coroutine)
    assert not modulo.asyncio.iscoroutinefunction(lambda: None)
    assert asyncio.iscoroutinefunction is referencia_asyncio
    assert not any(
        "asyncio.iscoroutinefunction" in str(aviso.message)
        for aviso in capturados
    )


@pytest.fixture
def rede_desativada(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    tentativas: list[str] = []

    def bloquear(*args: object, **kwargs: object) -> None:
        tentativas.append("socket")
        raise AssertionError("tentativa de rede durante teste local")

    monkeypatch.setattr(socket.socket, "connect", bloquear)
    monkeypatch.setattr(socket, "create_connection", bloquear)
    return tentativas


def test_persistente_cria_e_consulta_sem_rede_ou_texto(
    tmp_path: Path, rede_desativada: list[str]
) -> None:
    pasta = tmp_path / "chroma"
    repositorio = RepositorioVetorialChroma(
        pasta, modelo_embeddings=MODELO, dimensao=3
    )
    try:
        repositorio.adicionar(
            "memorias",
            "id-ficticio-1",
            [1.0, 0.0, 0.0],
            METADADOS,  # type: ignore[arg-type]
            modelo_embeddings=MODELO,
        )
        assert repositorio.buscar(
            "memorias", [1.0, 0.0, 0.0], modelo_embeddings=MODELO
        ) == ["id-ficticio-1"]
        assert repositorio.existe("memorias", "id-ficticio-1")
        assert repositorio.contar("memorias") == 1
        assert repositorio.listar_ids("memorias") == ["id-ficticio-1"]
        assert repositorio.buscar(
            "memorias",
            [1.0, 0.0, 0.0],
            filtros={"estado": "ativa", "importancia": 50},
            modelo_embeddings=MODELO,
        ) == ["id-ficticio-1"]
        assert all(
            repositorio.contar(nome) == (1 if nome == "memorias" else 0)
            for nome in ("memorias", "conversas", "conhecimento", "resumos")
        )
        metadados_colecao = repositorio._colecoes["memorias"].metadata
        assert metadados_colecao["modelo_embeddings"] == MODELO
        assert metadados_colecao["dimensao_embeddings"] == 3
        assert rede_desativada == []
    finally:
        repositorio.close()

    reaberto = RepositorioVetorialChroma(
        pasta, modelo_embeddings=MODELO, dimensao=3
    )
    try:
        assert reaberto.existe("memorias", "id-ficticio-1")
    finally:
        reaberto.close()

    sentinela = b"TEXTO_PESSOAL_FICTICIO_NAO_ENVIADO"
    assert all(sentinela not in arquivo.read_bytes() for arquivo in pasta.rglob("*") if arquivo.is_file())


def test_recusa_outro_modelo_ou_dimensao(tmp_path: Path) -> None:
    repositorio = RepositorioVetorialChroma(
        tmp_path / "chroma", modelo_embeddings=MODELO, dimensao=3
    )
    try:
        with pytest.raises(ErroRepositorioVetorial, match="Modelo"):
            repositorio.adicionar(
                "memorias",
                "id-ficticio-1",
                [1.0, 0.0, 0.0],
                METADADOS,  # type: ignore[arg-type]
                modelo_embeddings="outro-modelo",
            )
        with pytest.raises(ErroRepositorioVetorial, match="Dimensão"):
            repositorio.adicionar(
                "memorias",
                "id-ficticio-1",
                [1.0, 0.0],
                METADADOS,  # type: ignore[arg-type]
                modelo_embeddings=MODELO,
            )
        with pytest.raises(ErroRepositorioVetorial):
            repositorio.adicionar(
                "memorias",
                "id-ficticio-1",
                [1.0, 0.0, 0.0],
                {**METADADOS, "texto": "conteudo"},  # type: ignore[arg-type]
                modelo_embeddings=MODELO,
            )
    finally:
        repositorio.close()


def test_recusa_colecao_persistida_com_outro_modelo(tmp_path: Path) -> None:
    caminho = tmp_path / "chroma"
    primeiro = RepositorioVetorialChroma(
        caminho, modelo_embeddings=MODELO, dimensao=3
    )
    primeiro.close()
    with pytest.raises(ErroRepositorioVetorial, match="reindexar"):
        RepositorioVetorialChroma(
            caminho, modelo_embeddings="outro-modelo", dimensao=3
        )


def test_reconciliacao_remove_orfaos_e_corrige_indexado(tmp_path: Path) -> None:
    repositorio = RepositorioVetorialChroma(
        tmp_path / "chroma", modelo_embeddings=MODELO, dimensao=3
    )
    corrigidos: dict[str, bool] = {}
    try:
        for identificador in ("id-presente", "id-orfo"):
            repositorio.adicionar(
                "memorias",
                identificador,
                [1.0, 0.0, 0.0],
                METADADOS,  # type: ignore[arg-type]
                modelo_embeddings=MODELO,
            )
        resultado = repositorio.reconciliar(
            "memorias",
            ids_sqlite=["id-presente", "id-sem-vetor"],
            ids_indexados=["id-sem-vetor"],
            atualizar_indexado=lambda identificador, indexado: corrigidos.__setitem__(
                identificador, indexado
            ),
        )
        assert resultado.textos_sem_vetor == 1
        assert resultado.vetores_orfaos_removidos == 1
        assert resultado.indexado_corrigidos == 2
        assert corrigidos == {"id-sem-vetor": False, "id-presente": True}
        assert repositorio.listar_ids("memorias") == ["id-presente"]
    finally:
        repositorio.close()
