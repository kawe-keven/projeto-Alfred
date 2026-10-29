import pytest

from alfred.interfaces.web.lugares import (
    LugaresMemoria,
    LugaresSQLCipher,
    validar_categoria,
    validar_coordenadas,
    validar_nome,
)


def test_validacoes_rejeitam_payloads_invalidos():
    assert validar_nome("  Casa   da família ") == "Casa da família"
    for nome in ("", "x" * 81, "\u0000"):
        with pytest.raises(ValueError): validar_nome(nome)
    for lat, lon in ((float("nan"), 0), (91, 0), (0, 181), (True, 0)):
        with pytest.raises(ValueError): validar_coordenadas(lat, lon)
    with pytest.raises(ValueError): validar_categoria("__import__")


def test_memoria_nao_cria_arquivo_e_contadores_sao_por_categoria():
    repo = LugaresMemoria()
    primeiro = repo.criar("Casa", "CAS", -23.5, -46.6)
    segundo = repo.criar("Trabalho", "TRB", -23.6, -46.7)
    terceiro = repo.criar("Outra casa", "CAS", -23.4, -46.5)
    assert [primeiro["codigo"], segundo["codigo"], terceiro["codigo"]] == ["CAS-001", "TRB-001", "CAS-002"]
    assert repo.atualizar(primeiro["id"], {"nome": "Nova casa"})["nome"] == "Nova casa"
    assert repo.remover(segundo["id"])
    assert len(repo.listar()) == 2


def test_sqlcipher_guarda_conteudo_cifrado_e_migra(tmp_path):
    from alfred.memoria.armazenamento.conexao import abrir_conexao
    from alfred.seguranca.chaves.derivacao import derivar_subchave

    caminho = tmp_path / "alfred.db"
    chave = bytes(range(32))
    repo = LugaresSQLCipher(caminho, chave)
    repo.criar("NOME_FICTICIO_SECRETO", "CAS", -23.5, -46.6)
    with abrir_conexao(caminho, derivar_subchave(chave, "alfred.db"), escritor=False) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT nome FROM lugares").fetchone()[0] == "NOME_FICTICIO_SECRETO"
    assert b"NOME_FICTICIO_SECRETO" not in caminho.read_bytes()
