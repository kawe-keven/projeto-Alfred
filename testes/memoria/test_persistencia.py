from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alfred.memoria.armazenamento.conexao import (
    ErroConexaoSQLCipher,
    abrir_conexao,
)
from alfred.memoria.armazenamento.embeddings import TipoTextoEmbedding
from alfred.memoria.armazenamento.reindexacao import reindexar_memorias
from alfred.memoria.armazenamento.vetorial_chroma import ErroRepositorioVetorial
from alfred.seguranca.chaves.derivacao import derivar_subchave

from .conftest import (
    DIMENSAO_CONTROLADA,
    MODELO_CONTROLADO,
    GeradorEmbeddingsControlados,
)


def _inserir_evento(armazenamento, id_evento: str, texto: str) -> str:
    return armazenamento.banco.inserir_evento(
        tipo="conversa",
        criado_em=armazenamento.relogio(),
        origem="usuario",
        hash_texto=f"hash-{id_evento}",
        papel="usuario",
        texto=texto,
        id_evento=id_evento,
    )


def test_estado_indexado_muda_somente_depois_de_gravar_vetor(
    armazenamento_memoria, embeddings_controlados
) -> None:
    armazenamento = armazenamento_memoria
    identificador = _inserir_evento(armazenamento, "evento-persistido", "cafe")
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        assert conexao.execute(
            "SELECT indexado FROM eventos WHERE id=?", (identificador,)
        ).fetchone()[0] == 0

    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "documento")[0]
    armazenamento.chroma.adicionar(
        "conversas",
        identificador,
        vetor,
        {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
        modelo_embeddings=MODELO_CONTROLADO,
    )
    armazenamento.banco.marcar_indexado(identificador)
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        assert conexao.execute(
            "SELECT indexado FROM eventos WHERE id=?", (identificador,)
        ).fetchone()[0] == 1
    assert armazenamento.chroma.existe("conversas", identificador)


def test_reiniciar_com_mesma_chave_preserva_sqlcipher_e_chroma(
    armazenamento_memoria, embeddings_controlados
) -> None:
    armazenamento = armazenamento_memoria
    identificador = _inserir_evento(armazenamento, "evento-reinicio", "cafe")
    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "documento")[0]
    armazenamento.chroma.adicionar(
        "conversas",
        identificador,
        vetor,
        {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
        modelo_embeddings=MODELO_CONTROLADO,
    )
    armazenamento.banco.marcar_indexado(identificador)
    armazenamento.fechar()

    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        linha = conexao.execute(
            "SELECT texto, indexado FROM eventos WHERE id=?", (identificador,)
        ).fetchone()
        assert tuple(linha) == ("cafe", 1)
    from alfred.memoria.armazenamento.vetorial_chroma import RepositorioVetorialChroma

    reaberto = RepositorioVetorialChroma(
        armazenamento.caminho_chroma,
        modelo_embeddings=MODELO_CONTROLADO,
        dimensao=DIMENSAO_CONTROLADA,
    )
    try:
        assert reaberto.existe("conversas", identificador)
        assert reaberto.contar("conversas") == 1
    finally:
        reaberto.close()


def test_chave_errada_falha_sem_expor_chave_ou_criar_sqlite_plano(
    armazenamento_memoria,
) -> None:
    caminho = armazenamento_memoria.caminho_alfred
    bytes_antes = caminho.read_bytes()
    chave_errada = b"x" * 32
    with pytest.raises(ErroConexaoSQLCipher) as erro:
        with abrir_conexao(caminho, derivar_subchave(chave_errada, "alfred.db")):
            pass
    assert "chave" in str(erro.value).casefold()
    assert chave_errada.hex() not in str(erro.value)
    assert caminho.read_bytes() == bytes_antes
    assert not bytes_antes.startswith(b"SQLite format 3\x00")


def test_reconciliacao_corrige_falhas_parciais_e_remove_vetor_orfao(
    armazenamento_memoria, embeddings_controlados
) -> None:
    armazenamento = armazenamento_memoria
    sem_vetor = _inserir_evento(armazenamento, "evento-sem-vetor", "cafe")
    vetor_existe = _inserir_evento(armazenamento, "evento-vetor-existe", "cha")
    removido_sqlite = "evento-apagado-do-sqlite"
    for identificador, texto in ((vetor_existe, "cha"), (removido_sqlite, "cafe")):
        vetor = embeddings_controlados.gerar_em_lote([texto], "documento")[0]
        armazenamento.chroma.adicionar(
            "conversas",
            identificador,
            vetor,
            {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
            modelo_embeddings=MODELO_CONTROLADO,
        )

    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        ids_sqlite = [linha[0] for linha in conexao.execute("SELECT id FROM eventos")]
        ids_indexados = [
            linha[0]
            for linha in conexao.execute("SELECT id FROM eventos WHERE indexado=1")
        ]
    atualizado: dict[str, bool] = {}
    resultado = armazenamento.chroma.reconciliar(
        "conversas",
        ids_sqlite,
        ids_indexados,
        lambda identificador, indexado: atualizado.__setitem__(identificador, indexado),
    )
    assert resultado.textos_sem_vetor == 1
    assert resultado.vetores_orfaos_removidos == 1
    assert atualizado == {vetor_existe: True}
    assert armazenamento.chroma.existe("conversas", sem_vetor) is False
    assert armazenamento.chroma.existe("conversas", vetor_existe)
    assert armazenamento.chroma.existe("conversas", removido_sqlite) is False


def test_metadados_vetoriais_nao_guardam_texto_pessoal(
    armazenamento_memoria, embeddings_controlados, tmp_path: Path
) -> None:
    armazenamento = armazenamento_memoria
    sentinela = "SENTINELA_CHROMA_5483"
    identificador = _inserir_evento(armazenamento, "evento-sem-texto-no-vetor", sentinela)
    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "documento")[0]
    armazenamento.chroma.adicionar(
        "conversas",
        identificador,
        vetor,
        {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
        modelo_embeddings=MODELO_CONTROLADO,
    )
    consulta = armazenamento.chroma._colecoes["conversas"].get(
        ids=[identificador], include=["metadatas", "embeddings"]
    )
    assert set(consulta["metadatas"][0]) == {"tipo", "data", "importancia", "estado"}
    assert sentinela.encode() not in b"".join(
        arquivo.read_bytes()
        for arquivo in armazenamento.caminho_chroma.rglob("*")
        if arquivo.is_file()
    )
    assert consulta["embeddings"] is not None


def test_modelo_e_dimensao_sao_registrados_e_incompativeis_sao_recusados(
    armazenamento_memoria, embeddings_controlados
) -> None:
    armazenamento = armazenamento_memoria
    meta = armazenamento.chroma._colecoes["conversas"].metadata
    assert meta["modelo_embeddings"] == MODELO_CONTROLADO
    assert meta["dimensao_embeddings"] == DIMENSAO_CONTROLADA
    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "documento")[0]
    with pytest.raises(ErroRepositorioVetorial, match="Modelo"):
        armazenamento.chroma.adicionar(
            "conversas",
            "evento-modelo-errado",
            vetor,
            {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
            modelo_embeddings="modelo-incompativel",
        )
    with pytest.raises(ErroRepositorioVetorial, match="Dimensão"):
        armazenamento.chroma.adicionar(
            "conversas",
            "evento-dimensao-errada",
            vetor[:-1],
            {"tipo": "conversa", "data": armazenamento.relogio(), "importancia": 50, "estado": "ativa"},
            modelo_embeddings=MODELO_CONTROLADO,
        )


@pytest.mark.integracao
def test_reindexacao_controlada_e_reconstrucao_nao_duplicam(
    armazenamento_memoria, embeddings_controlados, monkeypatch: pytest.MonkeyPatch
) -> None:
    armazenamento = armazenamento_memoria
    _inserir_evento(armazenamento, "evento-reindex-cafe", "cafe")
    _inserir_evento(armazenamento, "evento-reindex-cha", "cha")

    class GeradorFalsoReindexacao:
        def __init__(self, modelo: str) -> None:
            assert modelo == MODELO_CONTROLADO

        def gerar_em_lote(
            self, textos: list[str], tipo: TipoTextoEmbedding
        ) -> list[list[float]]:
            return embeddings_controlados.gerar_em_lote(textos, tipo)

    import alfred.memoria.armazenamento.reindexacao as reindexacao

    monkeypatch.setattr(reindexacao, "GeradorEmbeddingsOllama", GeradorFalsoReindexacao)
    monkeypatch.setenv("ALFRED_MODELO_EMBEDDINGS", MODELO_CONTROLADO)
    armazenamento.fechar()
    assert reindexar_memorias(armazenamento.raiz, armazenamento.chave_mestra) == 2
    assert reindexar_memorias(armazenamento.raiz, armazenamento.chave_mestra) == 2
    from alfred.memoria.armazenamento.vetorial_chroma import RepositorioVetorialChroma

    primeira = RepositorioVetorialChroma(
        armazenamento.caminho_chroma,
        modelo_embeddings=MODELO_CONTROLADO,
        dimensao=DIMENSAO_CONTROLADA,
    )
    try:
        antes = primeira.buscar(
            "conversas",
            embeddings_controlados.gerar_em_lote(["cha"], "consulta")[0],
            modelo_embeddings=MODELO_CONTROLADO,
        )
        assert primeira.contar("conversas") == 2
    finally:
        primeira.close()
    shutil.rmtree(armazenamento.caminho_chroma)

    assert reindexar_memorias(armazenamento.raiz, armazenamento.chave_mestra) == 2
    reconstruido = RepositorioVetorialChroma(
        armazenamento.caminho_chroma,
        modelo_embeddings=MODELO_CONTROLADO,
        dimensao=DIMENSAO_CONTROLADA,
    )
    try:
        depois = reconstruido.buscar(
            "conversas",
            embeddings_controlados.gerar_em_lote(["cha"], "consulta")[0],
            modelo_embeddings=MODELO_CONTROLADO,
        )
        assert depois == antes
        assert reconstruido.contar("conversas") == 2
    finally:
        reconstruido.close()


def test_gravacoes_concorrentes_nao_corrompem_o_banco(armazenamento_memoria) -> None:
    armazenamento = armazenamento_memoria

    def gravar(indice: int) -> str:
        return _inserir_evento(
            armazenamento,
            f"evento-concorrente-{indice:03d}",
            f"texto fictício {indice}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        resultados = list(executor.map(gravar, range(32)))
    assert len(set(resultados)) == 32
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        assert conexao.execute("SELECT count(*) FROM eventos").fetchone()[0] == 32
        assert conexao.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
