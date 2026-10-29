from __future__ import annotations

import ctypes
import math
import os
import statistics
import time
import tracemalloc
from pathlib import Path

import pytest

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.chaves.derivacao import derivar_subchave

from .conftest import DIMENSAO_CONTROLADA, MODELO_CONTROLADO


QUANTIDADE_EVENTOS = 50_000
TAMANHO_LOTE = 500
TAMANHO_AMOSTRA_BUSCA = 40


def _percentil_95(valores: list[float]) -> float:
    ordenados = sorted(valores)
    indice = max(0, math.ceil(len(ordenados) * 0.95) - 1)
    return ordenados[indice]


def _limite(nome: str) -> float | None:
    texto = os.environ.get(nome)
    if texto is None:
        return None
    valor = float(texto)
    if not math.isfinite(valor) or valor <= 0:
        raise ValueError(f"Limite sintético inválido: {nome}")
    return valor


def _memoria_rastreada_mb() -> float:
    """Retorna uso residente atual do processo no Windows, se disponível."""
    if os.name != "nt":
        return 0.0

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    contador = PROCESS_MEMORY_COUNTERS()
    contador.cb = ctypes.sizeof(contador)
    processo = ctypes.windll.kernel32.GetCurrentProcess()
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        processo, ctypes.byref(contador), contador.cb
    )
    if not ok:
        return 0.0
    return contador.WorkingSetSize / (1024 * 1024)


def _tamanho_diretorio(raiz: Path) -> int:
    return sum(arquivo.stat().st_size for arquivo in raiz.rglob("*") if arquivo.is_file())


@pytest.mark.lento
def test_escala_sintetica_50_mil_eventos_e_buscas(armazenamento_memoria, record_property) -> None:
    armazenamento = armazenamento_memoria
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    colecao = armazenamento.chroma._colecoes["conversas"]
    instante = armazenamento.relogio()
    tracemalloc.start()
    memoria_inicio = _memoria_rastreada_mb()
    amostras_ram_mb = [memoria_inicio]
    inicio_indexacao = time.perf_counter()

    with abrir_conexao(armazenamento.caminho_alfred, chave) as conexao:
        conexao.execute("BEGIN IMMEDIATE")
        for inicio in range(0, QUANTIDADE_EVENTOS, TAMANHO_LOTE):
            fim = min(inicio + TAMANHO_LOTE, QUANTIDADE_EVENTOS)
            linhas = [
                (
                    f"perf-{indice:06d}",
                    "conversa",
                    "usuario",
                    f"evento fictício sintético {indice}",
                    instante + indice,
                    "usuario",
                    f"hash-perf-{indice:06d}",
                )
                for indice in range(inicio, fim)
            ]
            conexao.executemany(
                "INSERT INTO eventos(id,tipo,papel,texto,criado_em,origem,hash_texto) "
                "VALUES(?,?,?,?,?,?,?)",
                linhas,
            )
            amostras_ram_mb.append(_memoria_rastreada_mb())
        conexao.commit()

    for inicio in range(0, QUANTIDADE_EVENTOS, TAMANHO_LOTE):
        ids = [f"perf-{indice:06d}" for indice in range(inicio, inicio + TAMANHO_LOTE)]
        vetores = [
            [1.0 if coluna == indice % DIMENSAO_CONTROLADA else 0.0
             for coluna in range(DIMENSAO_CONTROLADA)]
            for indice in range(inicio, inicio + TAMANHO_LOTE)
        ]
        metadados = [
            {
                "tipo": "conversa",
                "data": instante + indice,
                "importancia": 50,
                "estado": "ativa",
            }
            for indice in range(inicio, inicio + TAMANHO_LOTE)
        ]
        amostras_ram_mb.append(_memoria_rastreada_mb())
        colecao.add(ids=ids, embeddings=vetores, metadatas=metadados)
        amostras_ram_mb.append(_memoria_rastreada_mb())
    tempo_indexacao_s = time.perf_counter() - inicio_indexacao

    consulta = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    latencias_ms: list[float] = []
    for _ in range(TAMANHO_AMOSTRA_BUSCA):
        inicio_busca = time.perf_counter()
        resultado = armazenamento.chroma.buscar(
            "conversas",
            consulta,
            k=5,
            modelo_embeddings=MODELO_CONTROLADO,
        )
        latencias_ms.append((time.perf_counter() - inicio_busca) * 1000)
        assert len(resultado) == 5

    _, pico_python_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    amostras_ram_mb.append(_memoria_rastreada_mb())
    ram_delta_mb = max(0.0, max(amostras_ram_mb) - memoria_inicio)
    pico_python_mb = pico_python_bytes / (1024 * 1024)
    ram_estimado_mb = max(ram_delta_mb, pico_python_mb)
    tamanho_disco_mb = _tamanho_diretorio(armazenamento.raiz) / (1024 * 1024)
    mediana_ms = statistics.median(latencias_ms)
    p95_ms = _percentil_95(latencias_ms)

    print(
        "memoria_benchmark "
        f"eventos={QUANTIDADE_EVENTOS} vetores={armazenamento.chroma.contar('conversas')} "
        f"indexacao_s={tempo_indexacao_s:.3f} busca_mediana_ms={mediana_ms:.3f} "
        f"busca_p95_ms={p95_ms:.3f} ram_delta_amostrado_mb={ram_delta_mb:.3f} "
        f"ram_estimado_mb={ram_estimado_mb:.3f} "
        f"python_pico_mb={pico_python_mb:.3f} disco_mb={tamanho_disco_mb:.3f}"
    )
    record_property("eventos", QUANTIDADE_EVENTOS)
    record_property("tempo_indexacao_s", tempo_indexacao_s)
    record_property("busca_mediana_ms", mediana_ms)
    record_property("busca_p95_ms", p95_ms)
    record_property("ram_delta_mb", ram_delta_mb)
    record_property("ram_estimado_mb", ram_estimado_mb)
    record_property("python_pico_mb", pico_python_mb)
    record_property("disco_mb", tamanho_disco_mb)

    assert armazenamento.chroma.contar("conversas") == QUANTIDADE_EVENTOS
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        assert conexao.execute("SELECT count(*) FROM eventos").fetchone()[0] == QUANTIDADE_EVENTOS
    for nome, medicao in (
        ("ALFRED_MEMORIA_LENTO_MAX_INDEXACAO_S", tempo_indexacao_s),
        ("ALFRED_MEMORIA_LENTO_MAX_P95_MS", p95_ms),
        ("ALFRED_MEMORIA_LENTO_MAX_RAM_MB", ram_estimado_mb),
        ("ALFRED_MEMORIA_LENTO_MAX_DISCO_MB", tamanho_disco_mb),
    ):
        limite = _limite(nome)
        if limite is not None:
            assert medicao <= limite
