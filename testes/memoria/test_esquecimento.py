from __future__ import annotations

import pytest

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.chaves.derivacao import derivar_subchave
from .conftest import MODELO_CONTROLADO


def test_busca_de_esquecimento_por_assunto_ignora_acentos_e_termos_do_pedido(
    armazenamento_memoria,
) -> None:
    banco = armazenamento_memoria.banco
    alvo = banco.inserir_evento(
        tipo="memoria", criado_em=1, origem="usuario", hash_texto="game-house",
        texto="Planejamento da Game House em Laranjeiras", id_evento="game-house",
    )
    banco.inserir_evento(
        tipo="memoria", criado_em=2, origem="usuario", hash_texto="barbearia",
        texto="Agendamento para barbearias", id_evento="barbearia",
    )

    encontrados = banco.buscar_eventos_por_assunto("Apague os dados sobre a Game House")

    assert [linha["id"] for linha in encontrados] == [alvo]


def test_primitiva_muda_estado_de_evento_no_sqlite(armazenamento_memoria) -> None:
    armazenamento = armazenamento_memoria
    identificador = armazenamento.banco.inserir_evento(
        tipo="memoria",
        criado_em=armazenamento.relogio(),
        origem="usuario",
        hash_texto="hash-estado-ficticio",
        texto="estado de memória fictícia",
        id_evento="memoria-estado-ficticia",
    )
    assert armazenamento.banco.atualizar_estado_evento(identificador, "resumida")
    assert armazenamento.banco.atualizar_estado_evento(identificador, "arquivada")
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        linha = conexao.execute(
            "SELECT estado FROM eventos WHERE id=?", (identificador,)
        ).fetchone()
    assert linha[0] == "arquivada"


def test_exclusao_relacional_remove_registro_de_arquivo_em_cascata(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    identificador = armazenamento.banco.inserir_evento(
        tipo="memoria",
        criado_em=armazenamento.relogio(),
        origem="usuario",
        hash_texto="hash-arquivo-ficticio",
        texto=None,
        estado="arquivada",
        id_evento="memoria-arquivada-ficticia",
    )
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(armazenamento.caminho_alfred, chave) as conexao:
        conexao.execute(
            "INSERT INTO arquivo(id_evento, blob, algoritmo, tamanho_original, arquivado_em) "
            "VALUES(?, ?, ?, ?, ?)",
            (identificador, b"conteudo ficticio comprimido", "teste", 25, armazenamento.relogio()),
        )
        conexao.commit()

    assert armazenamento.banco.apagar_eventos([identificador]) == 1
    with abrir_conexao(armazenamento.caminho_alfred, chave, escritor=False) as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM eventos WHERE id=?", (identificador,)
        ).fetchone()[0] == 0
        assert conexao.execute(
            "SELECT count(*) FROM arquivo WHERE id_evento=?", (identificador,)
        ).fetchone()[0] == 0


def test_ciclo_ativa_resumida_arquivada_apagada_elegivel(armazenamento_memoria) -> None:
    from alfred.memoria.armazenamento.ciclo import CicloMemoria
    a = armazenamento_memoria
    antigo = a.relogio() - 10_000
    ident = a.banco.inserir_evento(tipo="memoria", criado_em=antigo, origem="usuario", hash_texto="old", texto="memória antiga fictícia", id_evento="antiga")
    fixado = a.banco.inserir_evento(tipo="memoria", criado_em=antigo, origem="usuario", hash_texto="fixed", texto="memória fixada fictícia", fixada=True, id_evento="fixada")
    from alfred.memoria.armazenamento.conexao import abrir_conexao
    chave = derivar_subchave(a.chave_mestra, "alfred.db")
    with abrir_conexao(a.caminho_alfred, chave) as db:
        db.execute("INSERT INTO resumos(id,nivel,periodo_inicio,periodo_fim,texto,gerado_em) VALUES('r-old','dia',1,2,'Resumo fictício',?)", (a.relogio(),))
        db.execute("INSERT INTO resumo_itens VALUES('r-old','evento',?)", (ident,)); db.commit()
    ciclo = CicloMemoria(a.banco, a.relogio)
    assert ciclo.ciclo_vida(idade_resumida_ms=1_000, idade_arquivada_ms=20_000)["arquivadas"] == 0
    assert a.banco.buscar_eventos_por_ids([ident])[0]["estado"] == "resumida"
    assert ciclo.ciclo_vida(idade_resumida_ms=1_000, idade_arquivada_ms=5_000)["arquivadas"] == 1
    estados = {r["id"]: r for r in a.banco.buscar_eventos_por_ids([ident, fixado])}
    assert estados[ident]["estado"] == "arquivada" and estados[ident]["texto"] is None
    assert estados[fixado]["estado"] == "ativa" and estados[fixado]["fixada"] == 1
    assert ciclo.ciclo_vida(idade_resumida_ms=1_000, idade_arquivada_ms=5_000, idade_exclusao_ms=5_000)["apagadas"] == 1
    assert a.banco.buscar_eventos_por_ids([ident]) == []


def test_ciclo_arquiva_copia_texto_e_remove_vetores_de_todas_as_colecoes(
    armazenamento_memoria,
) -> None:
    from types import SimpleNamespace
    import zlib

    from alfred.memoria.armazenamento.ciclo import CicloMemoria

    a = armazenamento_memoria
    antigos = a.relogio() - 10_000
    registros = (
        ("conversa", "conversas", "evento-conversa"),
        ("conhecimento", "conhecimento", "evento-conhecimento"),
        ("memoria", "memorias", "evento-memoria"),
    )
    vetor = [1.0, *([0.0] * 7)]
    for tipo, colecao, ident in registros:
        a.banco.inserir_evento(
            tipo=tipo, criado_em=antigos, origem="usuario",
            papel="usuario" if tipo == "conversa" else None,
            hash_texto=ident, texto=f"texto arquivado de {tipo}", estado="resumida",
            id_evento=ident,
        )
        a.chroma.adicionar(
            colecao, ident, vetor,
            {"tipo": tipo, "data": antigos, "importancia": 50, "estado": "resumida"},
            modelo_embeddings=MODELO_CONTROLADO,
        )

    ciclo = CicloMemoria(
        a.banco, a.relogio,
        rag=SimpleNamespace(repositorio=a.chroma, auditoria=a.auditoria),
    )
    resultado = ciclo.ciclo_vida(idade_resumida_ms=1, idade_arquivada_ms=5_000)

    assert resultado["arquivadas"] == 3
    with abrir_conexao(
        a.caminho_alfred, derivar_subchave(a.chave_mestra, "alfred.db"), escritor=False
    ) as db:
        for tipo, colecao, ident in registros:
            evento = db.execute("SELECT estado,texto FROM eventos WHERE id=?", (ident,)).fetchone()
            arquivo = db.execute(
                "SELECT blob,algoritmo,tamanho_original FROM arquivo WHERE id_evento=?", (ident,)
            ).fetchone()
            assert tuple(evento) == ("arquivada", None)
            texto = zlib.decompress(arquivo["blob"]).decode("utf-8")
            assert texto == f"texto arquivado de {tipo}"
            assert arquivo["algoritmo"] == "zlib"
            assert arquivo["tamanho_original"] == len(texto.encode("utf-8"))
            assert not a.chroma.existe(colecao, ident)


def test_esquecer_confirma_e_remove_todas_as_referencias(armazenamento_memoria, embeddings_controlados) -> None:
    from types import SimpleNamespace
    from alfred.interfaces.cli.app import SessaoConversa
    a = armazenamento_memoria
    ident = a.banco.inserir_evento(tipo="memoria", criado_em=a.relogio(), origem="usuario", hash_texto="forget-hash", texto="fato removível", id_evento="forget-me")
    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "documento")[0]
    a.chroma.adicionar("memorias", ident, vetor, {"tipo":"memoria","data":a.relogio(),"importancia":50,"estado":"ativa"}, modelo_embeddings=MODELO_CONTROLADO)
    rag = SimpleNamespace(repositorio=a.chroma)
    rag.banco = a.banco
    rag.auditoria = a.auditoria
    sessao = object.__new__(SessaoConversa)
    sessao.rag = rag
    sessao.confirmar = lambda _: "não"
    assert "confirmação" in sessao.executar_comando(f"/esquecer {ident}")
    assert a.chroma.existe("memorias", ident)
    sessao.confirmar = lambda _: "sim"
    assert "Memória apagada" in sessao.executar_comando(f"/esquecer {ident}")
    assert a.banco.buscar_eventos_por_ids([ident]) == []
    assert not a.chroma.existe("memorias", ident)
    assert a.auditoria.verificar_cadeia().valida


def test_esquecer_funciona_quando_indice_vetorial_esta_indisponivel(armazenamento_memoria) -> None:
    from types import SimpleNamespace
    from alfred.memoria.armazenamento.ciclo import CicloMemoria

    a = armazenamento_memoria
    identificador = a.banco.inserir_evento(
        tipo="memoria",
        criado_em=a.relogio(),
        origem="usuario",
        hash_texto="sem-indice",
        texto="Fato fictício para remoção",
        id_evento="memoria-sem-indice",
    )
    ciclo = CicloMemoria(
        a.banco,
        lambda: a.relogio(),
        rag=SimpleNamespace(repositorio=None, auditoria=a.auditoria),
    )

    assert ciclo.esquecer(identificador, confirmar=True)
    assert a.banco.buscar_eventos_por_ids([identificador]) == []


def test_esquecimento_remove_origem_e_regenera_resumos(armazenamento_memoria) -> None:
    from alfred.memoria.armazenamento.ciclo import CicloMemoria
    from alfred.memoria.armazenamento.conexao import abrir_conexao
    a = armazenamento_memoria
    apagado = a.banco.inserir_evento(tipo="conversa", criado_em=10, origem="usuario", papel="usuario", hash_texto="gone", texto="sentinela fictícia removida", id_evento="gone")
    restante = a.banco.inserir_evento(tipo="conversa", criado_em=11, origem="usuario", papel="usuario", hash_texto="keep", texto="informação preservada", id_evento="keep")
    chave = derivar_subchave(a.chave_mestra, "alfred.db")
    with abrir_conexao(a.caminho_alfred, chave) as db:
        db.execute("INSERT INTO resumos(id,nivel,periodo_inicio,periodo_fim,texto,gerado_em) VALUES('resumo-cascata','dia',1,20,'resumo com sentinela',?)", (a.relogio(),))
        db.executemany("INSERT INTO resumo_itens VALUES('resumo-cascata','evento',?)", [(apagado,), (restante,)]); db.commit()
    ciclo = CicloMemoria(a.banco, a.relogio)
    assert ciclo.esquecer(apagado, confirmar=True)
    with abrir_conexao(a.caminho_alfred, chave, escritor=False) as db:
        texto = db.execute("SELECT texto FROM resumos WHERE id='resumo-cascata'").fetchone()[0]
        fontes = db.execute("SELECT id_origem FROM resumo_itens WHERE id_resumo='resumo-cascata'").fetchall()
    assert texto == "informação preservada"
    assert [r[0] for r in fontes] == [restante]


def test_sentinela_esquecida_nao_permanece_nos_arquivos_temporarios(armazenamento_memoria) -> None:
    a = armazenamento_memoria
    sentinela = "SENTINELA_APAGADA_FICTICIA_42D91"
    ident = a.banco.inserir_evento(tipo="memoria", criado_em=a.relogio(), origem="usuario", hash_texto="sentinel", texto=sentinela, id_evento="sentinel")
    from alfred.memoria.armazenamento.ciclo import CicloMemoria
    assert CicloMemoria(a.banco, a.relogio).esquecer(ident, confirmar=True)
    for arquivo in a.raiz.rglob("*"):
        if arquivo.is_file():
            assert sentinela.encode() not in arquivo.read_bytes()


@pytest.mark.integracao
def test_fluxo_integrado_todos_armazenamentos_e_esquecimento(
    armazenamento_memoria, embeddings_controlados, llm_falso
) -> None:
    from types import SimpleNamespace
    from alfred.memoria.armazenamento.ciclo import CicloMemoria
    from alfred.memoria.armazenamento.rag import ServicoRAG
    from alfred.memoria.armazenamento.conexao import abrir_conexao

    a = armazenamento_memoria
    texto = "Preferência fictícia de respostas sobre o projeto Atlas"
    resumo_texto = "Resumo fictício: preferência do Atlas"
    vetor = [1.0] + [0.0] * 7
    embeddings_controlados.mapear(texto, vetor)
    embeddings_controlados.mapear(resumo_texto, vetor)
    embeddings_controlados.mapear("projeto Atlas", vetor)
    llm_falso.resposta = resumo_texto

    rag = object.__new__(ServicoRAG)
    rag.raiz = a.raiz
    rag.caminho_db = a.caminho_alfred
    rag._chave_db = derivar_subchave(a.chave_mestra, "alfred.db")
    rag.banco = a.banco
    rag.modelo = MODELO_CONTROLADO
    rag.max_itens = 5
    rag.limite_caracteres = 5000
    rag.gerador = embeddings_controlados
    rag.repositorio = a.chroma
    rag.metricas = a.metricas
    rag.auditoria = a.auditoria
    rag.interface = "cli"
    rag.ultima_fontes = []
    rag.ultima_busca_disponivel = True

    ciclo = CicloMemoria(a.banco, a.relogio, rag=rag, llm=llm_falso)
    ident = rag.lembrar(texto)
    evento = a.banco.buscar_eventos_por_ids([ident])[0]
    assert evento["indexado"] == 1 and a.chroma.existe("memorias", ident)

    resumo_id = ciclo.resumir_periodo("dia", evento["criado_em"] - 1, evento["criado_em"] + 1)
    assert resumo_id and a.chroma.existe("resumos", resumo_id)
    contexto = rag.recuperar("projeto Atlas")
    assert texto in contexto and resumo_texto in contexto
    assert len(rag.ultima_fontes) >= 2

    with abrir_conexao(a.caminho_metricas, derivar_subchave(a.chave_mestra, "metricas.db"), finalidade="metricas", escritor=False) as db:
        assert db.execute("SELECT count(*) FROM recuperacao_contexto").fetchone()[0] == 1
    assert a.auditoria.verificar_cadeia().valida

    assert ciclo.esquecer(ident, confirmar=True)
    assert a.banco.buscar_eventos_por_ids([ident]) == []
    assert not a.chroma.existe("memorias", ident)
    assert not a.chroma.existe("resumos", resumo_id)
    with abrir_conexao(a.caminho_alfred, rag._chave_db, escritor=False) as db:
        assert db.execute("SELECT count(*) FROM eventos").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM resumos").fetchone()[0] == 0
    assert a.auditoria.verificar_cadeia().valida
    chave_auditoria = derivar_subchave(a.chave_mestra, "auditoria.db")
    with abrir_conexao(a.caminho_auditoria, chave_auditoria, finalidade="auditoria", escritor=False) as db:
        acoes = {str(r[0]) for r in db.execute("SELECT acao FROM auditoria")}
    assert {"lembrar", "recuperar", "esquecer"} <= acoes
    assert all(texto.encode() not in arquivo.read_bytes() for arquivo in a.raiz.rglob("*") if arquivo.is_file())
