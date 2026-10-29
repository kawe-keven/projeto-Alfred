from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import (
    ErroConexaoSQLCipher,
    abrir_conexao,
)
from alfred.memoria.armazenamento.migracao import ErroMigracao, aplicar_migracoes
from alfred.seguranca.chaves.derivacao import derivar_subchave


CHAVE_TESTE = bytes(range(32))
MIGRACOES = Path(__file__).parents[2] / "src/alfred/memoria/armazenamento/migracoes"


def migrar(caminho: Path) -> None:
    aplicar_migracoes(caminho, derivar_subchave(CHAVE_TESTE, "alfred.db"))


def test_sqlcipher_cifra_wal_e_recusa_chave_errada(tmp_path: Path) -> None:
    caminho = tmp_path / "teste.db"
    sentinela = "SENTINELA_FICTICIA_9c127"
    with abrir_conexao(caminho, b"k" * 32) as conexao:
        conexao.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conexao.execute("CREATE TABLE teste(valor TEXT)")
        conexao.execute("INSERT INTO teste VALUES(?)", (sentinela,))
        conexao.commit()
        assert conexao.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conexao.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conexao.execute("PRAGMA secure_delete").fetchone()[0] == 1
        assert conexao.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    conteudo = caminho.read_bytes()
    assert not conteudo.startswith(b"SQLite format 3\x00")
    assert sentinela.encode() not in conteudo
    with pytest.raises(ErroConexaoSQLCipher, match="chave"):
        with abrir_conexao(caminho, b"w" * 32):
            pass


def test_migracoes_idempotentes_e_esquema(tmp_path: Path) -> None:
    caminho = tmp_path / "alfred.db"
    chave = derivar_subchave(CHAVE_TESTE, "alfred.db")
    assert aplicar_migracoes(caminho, chave) == 5
    assert aplicar_migracoes(caminho, chave) == 5
    with abrir_conexao(caminho, chave, escritor=False) as conexao:
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conexao.execute(
            "SELECT valor FROM meta WHERE chave=?", ("schema_version",)
        ).fetchone()[0] == "5"
        assert conexao.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
        assert conexao.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not caminho.with_name(f"{caminho.name}.migracao.bak").exists()


def test_migracao_recusa_banco_de_versao_mais_nova(tmp_path: Path) -> None:
    caminho = tmp_path / "futuro.db"
    chave = derivar_subchave(CHAVE_TESTE, "alfred.db")
    migrar(caminho)
    with abrir_conexao(caminho, chave) as conexao:
        conexao.execute("PRAGMA user_version=6")
        conexao.commit()
    with pytest.raises(ErroMigracao, match="mais nova"):
        aplicar_migracoes(caminho, chave)


def test_falha_de_migracao_restaura_copia_cifrada(tmp_path: Path) -> None:
    caminho = tmp_path / "rollback.db"
    chave = derivar_subchave(CHAVE_TESTE, "alfred.db")
    migrar(caminho)
    pasta = tmp_path / "migracoes"
    shutil.copytree(MIGRACOES, pasta)
    (pasta / "0006_falha.sql").write_text(
        "UPDATE meta SET valor='6' WHERE chave='schema_version';\n"
        "SELECT * FROM tabela_que_nao_existe;\n",
        encoding="utf-8",
    )
    with pytest.raises(ErroMigracao, match="restaurada"):
        aplicar_migracoes(caminho, chave, pasta_migracoes=pasta)
    with abrir_conexao(caminho, chave, escritor=False) as conexao:
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 5
        assert conexao.execute(
            "SELECT valor FROM meta WHERE chave=?", ("schema_version",)
        ).fetchone()[0] == "5"
    assert not caminho.with_name(f"{caminho.name}.migracao.bak").exists()


def test_restricoes_chaves_estrangeiras_e_cascata(tmp_path: Path) -> None:
    caminho = tmp_path / "restricoes.db"
    migrar(caminho)
    banco = BancoRelacional(caminho, CHAVE_TESTE)
    sessao = banco.criar_sessao("cli", 1000, id_sessao="sessao-ficticia")
    evento = banco.inserir_evento(
        tipo="nota",
        criado_em=1001,
        origem="usuario",
        hash_texto="hash-nota",
        texto="conteudo ficticio",
        sessao_id=sessao,
        id_evento="evento-ficticio",
    )
    with abrir_conexao(caminho, derivar_subchave(CHAVE_TESTE, "alfred.db")) as conexao:
        with pytest.raises(sqlcipher.IntegrityError):
            conexao.execute(
                "INSERT INTO eventos(id, tipo, criado_em, origem, hash_texto) "
                "VALUES(?, ?, ?, ?, ?)",
                ("ruim", "nota; DROP TABLE eventos", 1002, "usuario", "x"),
            )
        with pytest.raises(sqlcipher.IntegrityError):
            conexao.execute(
                "INSERT INTO eventos(id, tipo, criado_em, origem, hash_texto, sessao_id, texto) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                ("fk-ruim", "nota", 1002, "usuario", "x", "inexistente", "texto"),
            )
        conexao.commit()
    assert banco.apagar_eventos([evento]) == 1
    assert banco.encerrar_sessao(sessao, 1003)


def test_arquivado_aceita_texto_nulo_e_hash_conhecimento_e_unico(tmp_path: Path) -> None:
    caminho = tmp_path / "checks.db"
    migrar(caminho)
    banco = BancoRelacional(caminho, CHAVE_TESTE)
    banco.inserir_evento(
        tipo="nota",
        criado_em=1,
        origem="usuario",
        hash_texto="arquivo-1",
        texto=None,
        estado="arquivada",
        id_evento="arquivado",
    )
    banco.inserir_evento(
        tipo="conhecimento",
        criado_em=2,
        origem="importacao",
        hash_texto="hash-repetido",
        texto="ficticio",
        id_evento="conhecimento-1",
    )
    with pytest.raises(sqlcipher.IntegrityError):
        banco.inserir_evento(
            tipo="conhecimento",
            criado_em=3,
            origem="importacao",
            hash_texto="hash-repetido",
            texto="outro ficticio",
            id_evento="conhecimento-2",
        )


def test_consulta_maliciosa_e_parametrizada(tmp_path: Path) -> None:
    caminho = tmp_path / "parametros.db"
    migrar(caminho)
    banco = BancoRelacional(caminho, CHAVE_TESTE)
    ataque = "x'); DROP TABLE eventos; --"
    banco.inserir_evento(
        tipo="nota",
        criado_em=10,
        origem="usuario",
        hash_texto="hash-param",
        texto=ataque,
        id_evento=ataque,
    )
    resultado = banco.buscar_eventos_por_ids([ataque])
    assert resultado[0]["texto"] == ataque
    assert banco.contagens()["eventos"] == 1


def test_conversas_recentes_incluem_todas_as_sessoes(tmp_path: Path) -> None:
    caminho = tmp_path / "recentes.db"
    migrar(caminho)
    banco = BancoRelacional(caminho, CHAVE_TESTE)
    sessao_antiga = banco.criar_sessao("cli", 100, id_sessao="sessao-antiga")
    sessao_recente = banco.criar_sessao("cli", 200, id_sessao="sessao-recente")
    banco.inserir_evento(
        tipo="conversa", criado_em=101, origem="usuario", papel="usuario",
        hash_texto="hash-conversa-antiga", texto="decisão anterior",
        sessao_id=sessao_antiga,
    )
    banco.inserir_evento(
        tipo="conversa", criado_em=201, origem="usuario", papel="usuario",
        hash_texto="hash-conversa-recente", texto="decisão recente",
        sessao_id=sessao_recente,
    )

    falas = banco.buscar_conversas_recentes(limite=2)

    assert [fala["texto"] for fala in falas] == ["decisão anterior", "decisão recente"]


def test_busca_generica_por_ultimas_conversas_nao_vira_busca_por_palavra_resumo(
    tmp_path: Path,
) -> None:
    caminho = tmp_path / "busca-generica.db"
    migrar(caminho)
    banco = BancoRelacional(caminho, CHAVE_TESTE)
    sessao = banco.criar_sessao("cli", 100, id_sessao="sessao-generica")
    banco.inserir_evento(
        tipo="conversa", criado_em=101, origem="usuario", papel="usuario",
        hash_texto="hash-pedido-resumo", texto="Pedi um resumo das últimas conversas",
        sessao_id=sessao,
    )

    assert banco.buscar_conversas_historico("Me dê um resumo das últimas conversas") == []
