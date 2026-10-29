from __future__ import annotations

import base64
from pathlib import Path

import pytest

from alfred.interfaces.cli.armazenamento import _restaurar_chave, main
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.embeddings import GeradorEmbeddingsOllama
from alfred.seguranca.chaves.derivacao import derivar_subchave
from alfred.seguranca.chaves.provedores import (
    ChaveMestraAusente,
    CredencialKeyringAusente,
)
from alfred.memoria.armazenamento.vetorial_chroma import RepositorioVetorialChroma


CHAVE = bytes(range(32))
CHAVE_B64 = base64.b64encode(CHAVE).decode("ascii")


def test_status_sem_bancos_nao_cria_diretorio_ou_pede_chave(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("ALFRED_SQLCIPHER_CHAVE", raising=False)
    raiz = tmp_path / "bancos"
    assert main(["--diretorio", str(raiz), "status"]) == 0
    assert not raiz.exists()
    assert "principal: ausente" in capsys.readouterr().out


def test_criar_verificar_status_e_backup_somente_em_tmp_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "origem"
    destino = tmp_path / "backup"

    assert main(["--diretorio", str(raiz), "criar"]) == 0
    assert main(["--diretorio", str(raiz), "verificar"]) == 0
    assert "válida" in capsys.readouterr().out
    assert main(["--diretorio", str(raiz), "status"]) == 0
    assert "registros: 0" in capsys.readouterr().out
    assert main(["--diretorio", str(raiz), "backup", str(destino)]) == 0
    assert capsys.readouterr().out.endswith("bancos: 3\n")

    for nome, rotulo, finalidade in (
        ("alfred.db", "alfred.db", "dados"),
        ("auditoria.db", "auditoria.db", "auditoria"),
        ("metricas.db", "metricas.db", "metricas"),
    ):
        with abrir_conexao(
            destino / nome,
            derivar_subchave(CHAVE, rotulo),
            finalidade=finalidade,
            escritor=False,
        ) as conexao:
            assert conexao.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_nao_pode_ser_criado_dentro_da_origem(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "origem"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    assert main(["--diretorio", str(raiz), "backup", str(raiz / "backup")]) == 1


def test_gerar_chave_emite_base64_de_32_bytes(capsys) -> None:
    assert main(["gerar-chave"]) == 0
    assert len(base64.b64decode(capsys.readouterr().out.strip(), validate=True)) == 32


def test_configurar_chave_guarda_no_cofre_sem_exibir_e_e_idempotente(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    class CofreFalso:
        chave = None

        def obter_chave_mestra(self):
            if self.chave is None:
                raise CredencialKeyringAusente("sem credencial")
            return self.chave

        def guardar_chave_mestra(self, chave):
            self.chave = chave

    cofre = CofreFalso()
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.ProvedorDeKeyring", lambda: cofre
    )
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.secrets.token_bytes",
        lambda tamanho: b"k" * tamanho,
    )
    raiz = tmp_path / "bancos"

    assert main(["--diretorio", str(raiz), "configurar-chave"]) == 0
    saida = capsys.readouterr()
    assert "cofre do Windows" in saida.out
    assert base64.b64encode(b"k" * 32).decode() not in saida.out
    assert (raiz / "alfred.db").is_file()

    assert main(["--diretorio", str(raiz), "configurar-chave"]) == 0
    assert "validada no cofre" in capsys.readouterr().out
    assert cofre.chave == b"k" * 32


def test_restaurar_chave_valida_banco_antes_de_guardar_no_cofre(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "bancos"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    monkeypatch.delenv("ALFRED_SQLCIPHER_CHAVE")

    class CofreFalso:
        chave = None

        def guardar_chave_mestra(self, chave):
            self.chave = chave

    cofre = CofreFalso()
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.ProvedorInterativo",
        lambda: type("LeitorFalso", (), {"obter_chave_mestra": lambda _self: CHAVE})(),
    )
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.ProvedorDeKeyring", lambda: cofre
    )

    resultado = _restaurar_chave(raiz)

    assert "validada" in resultado
    assert cofre.chave == CHAVE


def test_restaurar_chave_incorreta_nao_altera_cofre(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "bancos"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    monkeypatch.delenv("ALFRED_SQLCIPHER_CHAVE")

    class CofreFalso:
        chamada = False

        def guardar_chave_mestra(self, _chave):
            self.chamada = True

    cofre = CofreFalso()
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.ProvedorInterativo",
        lambda: type(
            "LeitorFalso", (), {"obter_chave_mestra": lambda _self: b"x" * 32}
        )(),
    )
    monkeypatch.setattr(
        "alfred.interfaces.cli.armazenamento.ProvedorDeKeyring", lambda: cofre
    )

    with pytest.raises(ChaveMestraAusente, match="cofre não foi alterado"):
        _restaurar_chave(raiz)
    assert not cofre.chamada


def test_reindexar_banco_vazio_nao_inicia_ollama_nem_cria_indice(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "origem"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    assert main(["--diretorio", str(raiz), "reindexar"]) == 0
    assert "itens processados: 0" in capsys.readouterr().out
    assert not (raiz / "chroma").exists()


def test_limpar_metricas_relata_apenas_contagem(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    raiz = tmp_path / "origem"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    assert main(["--diretorio", str(raiz), "limpar-metricas"]) == 0
    assert "linhas: 0" in capsys.readouterr().out


def test_reindexar_troca_modelo_preserva_indice_anterior(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", CHAVE_B64)
    monkeypatch.setenv("ALFRED_MODELO_EMBEDDINGS", "modelo-falso-novo")
    monkeypatch.setattr(
        GeradorEmbeddingsOllama,
        "gerar_em_lote",
        lambda self, textos, tipo: [[0.0, 1.0, 0.0] for _ in textos],
    )
    raiz = tmp_path / "origem"
    assert main(["--diretorio", str(raiz), "criar"]) == 0
    banco = BancoRelacional(raiz / "alfred.db", CHAVE)
    banco.inserir_evento(
        tipo="memoria",
        criado_em=1_800_000_000_000,
        origem="usuario",
        hash_texto="a" * 64,
        texto="conteudo ficticio apenas para teste",
        id_evento="id-ficticio-reindex",
    )
    with abrir_conexao(
        raiz / "alfred.db", derivar_subchave(CHAVE, "alfred.db")
    ) as conexao:
        conexao.execute("UPDATE meta SET valor='modelo-falso-antigo' WHERE chave='modelo_embeddings'")
        conexao.execute("UPDATE meta SET valor='2' WHERE chave='dimensao_embeddings'")
        conexao.commit()
    antigo = RepositorioVetorialChroma(
        raiz / "chroma", modelo_embeddings="modelo-falso-antigo", dimensao=2
    )
    try:
        antigo.adicionar(
            "memorias",
            "id-ficticio-reindex",
            [1.0, 0.0],
            {"tipo": "memoria", "data": 1_800_000_000_000, "importancia": 50, "estado": "ativa"},
            modelo_embeddings="modelo-falso-antigo",
        )
    finally:
        antigo.close()

    assert main(["--diretorio", str(raiz), "reindexar"]) == 0
    assert "itens processados: 1" in capsys.readouterr().out
    assert (raiz / "chroma.anterior").is_dir()
    atual = RepositorioVetorialChroma(
        raiz / "chroma", modelo_embeddings="modelo-falso-novo", dimensao=3
    )
    try:
        assert atual.existe("memorias", "id-ficticio-reindex")
    finally:
        atual.close()
