from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.auditoria import ErroAuditoria, RegistroDeAuditoria
from alfred.seguranca.chaves.derivacao import derivar_subchave


CHAVE_TESTE = bytes(range(32))


def criar_registro(tmp_path: Path) -> RegistroDeAuditoria:
    return RegistroDeAuditoria(
        tmp_path / "auditoria.db",
        tmp_path / "registros" / "ancora.json",
        CHAVE_TESTE,
        relogio_ms=lambda: 1_700_000_000_123,
    )


def test_cadeia_hmac_e_ancora_validas(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    assert registro.registrar(
        "banco", "criar", "ok", "sistema", quantidade=2, confirmado=True
    ) == 1
    assert registro.registrar(
        "banco", "backup", "ok", "usuario", tamanho_bytes=1024
    ) == 2
    resultado = registro.verificar_cadeia()
    assert resultado.valida
    assert resultado.codigo == "valida"
    assert resultado.seq_inconsistente is None


def test_triggers_impedem_update_e_delete(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    registro.registrar("banco", "criar", "ok", "sistema")
    chave = derivar_subchave(CHAVE_TESTE, "auditoria.db")
    with pytest.raises(sqlcipher.DatabaseError):
        with abrir_conexao(tmp_path / "auditoria.db", chave) as conexao:
            conexao.execute("UPDATE auditoria SET acao=? WHERE seq=?", ("alterar", 1))
    with pytest.raises(sqlcipher.DatabaseError):
        with abrir_conexao(tmp_path / "auditoria.db", chave) as conexao:
            conexao.execute("DELETE FROM auditoria WHERE seq=?", (1,))


def test_adulteracao_e_detectada_na_sequencia_correta(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    registro.registrar("banco", "criar", "ok", "sistema")
    registro.registrar("banco", "backup", "ok", "sistema")
    chave = derivar_subchave(CHAVE_TESTE, "auditoria.db")
    with abrir_conexao(tmp_path / "auditoria.db", chave) as conexao:
        conexao.execute("DROP TRIGGER auditoria_sem_update")
        conexao.execute("UPDATE auditoria SET acao=? WHERE seq=?", ("alterado", 2))
        conexao.commit()
    resultado = registro.verificar_cadeia()
    assert not resultado.valida
    assert resultado.seq_inconsistente == 2
    assert resultado.codigo == "hash_invalido"


def test_truncamento_e_detectado_pela_ancora(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    registro.registrar("banco", "criar", "ok", "sistema")
    registro.registrar("banco", "backup", "ok", "sistema")
    chave = derivar_subchave(CHAVE_TESTE, "auditoria.db")
    with abrir_conexao(tmp_path / "auditoria.db", chave) as conexao:
        conexao.execute("DROP TRIGGER auditoria_sem_delete")
        conexao.execute("DELETE FROM auditoria WHERE seq=?", (2,))
        conexao.commit()
    resultado = registro.verificar_cadeia()
    assert not resultado.valida
    assert resultado.seq_inconsistente == 2
    assert resultado.codigo == "truncada"


def test_metadados_rejeitam_conteudo_e_chaves_nao_permitidas(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    sentinela = "SENTINELA_CONTEUDO_FICTICIO"
    with pytest.raises(ErroAuditoria) as erro:
        registro.registrar("banco", "consulta", "ok", "sistema", texto=sentinela)
    assert sentinela not in str(erro.value)
    with pytest.raises(ErroAuditoria):
        registro.registrar("banco", "consulta", "ok", "sistema", codigo=sentinela)
    with pytest.raises(ErroAuditoria):
        registro.registrar("banco", "consulta", "ok", "sistema", hash="curto")
    assert not (tmp_path / "auditoria.db").exists()


def test_metadados_canonicos_nao_contam_sentintela(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    sentinela = "SENTINELA_FICTICIA_NAO_REGISTRAR"
    with pytest.raises(ErroAuditoria):
        registro.registrar("banco", "criar", "ok", "sistema", contexto=sentinela)
    assert not (tmp_path / "auditoria.db").exists()
    assert not (tmp_path / "registros" / "ancora.json").exists()


def test_escritas_concorrentes_preservam_cadeia(tmp_path: Path) -> None:
    registro = criar_registro(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        sequencias = list(
            executor.map(
                lambda numero: registro.registrar(
                    "banco", "operacao", "ok", "sistema", quantidade=numero
                ),
                range(32),
            )
        )
    assert sorted(sequencias) == list(range(1, 33))
    assert registro.verificar_cadeia().valida
