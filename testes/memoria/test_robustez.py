from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.migracao import ErroMigracao, aplicar_migracoes
from alfred.memoria.armazenamento.vetorial_chroma import (
    ErroRepositorioVetorial,
    RepositorioVetorialChroma,
)
from alfred.seguranca.chaves.derivacao import derivar_subchave

from .conftest import DIMENSAO_CONTROLADA, MODELO_CONTROLADO


def test_banco_de_versao_futura_e_recusado_sem_rebaixar_esquema(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    caminho = armazenamento.caminho_alfred
    chave = derivar_subchave(armazenamento.chave_mestra, "alfred.db")
    with abrir_conexao(caminho, chave) as conexao:
        conexao.execute("PRAGMA user_version=99")
        conexao.commit()
    with pytest.raises(ErroMigracao, match="mais nova"):
        aplicar_migracoes(
            caminho,
            chave,
            pasta_migracoes=(
                Path(__file__).parents[2]
                / "src" / "alfred" / "memoria" / "armazenamento" / "migracoes"
            ),
        )
    with abrir_conexao(caminho, chave, escritor=False) as conexao:
        assert conexao.execute("PRAGMA user_version").fetchone()[0] == 99
        assert conexao.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_chroma_corrompido_recusa_abertura_com_erro_seguro(tmp_path) -> None:
    caminho = tmp_path / "chroma-corrompido"
    inicial = RepositorioVetorialChroma(
        caminho,
        modelo_embeddings=MODELO_CONTROLADO,
        dimensao=DIMENSAO_CONTROLADA,
    )
    inicial.close()
    (caminho / "chroma.sqlite3").write_bytes(b"conteudo binario invalido")
    with pytest.raises(ErroRepositorioVetorial, match="armazenamento vetorial local"):
        RepositorioVetorialChroma(
            caminho,
            modelo_embeddings=MODELO_CONTROLADO,
            dimensao=DIMENSAO_CONTROLADA,
        )


def test_morte_de_processo_durante_transacao_preserva_integridade(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    chave = armazenamento.chave_mestra
    ambiente = os.environ.copy()
    ambiente["ALFRED_TESTE_CHAVE_DESCARTAVEL"] = chave.hex()
    codigo = """
import os, sys
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.chaves.derivacao import derivar_subchave
caminho = sys.argv[1]
chave = bytes.fromhex(os.environ['ALFRED_TESTE_CHAVE_DESCARTAVEL'])
with abrir_conexao(caminho, derivar_subchave(chave, 'alfred.db')) as conexao:
    conexao.execute('BEGIN IMMEDIATE')
    conexao.execute(
        'INSERT INTO eventos(id,tipo,papel,texto,criado_em,origem,hash_texto) '
        'VALUES(?,?,?,?,?,?,?)',
        ('evento-parcial', 'conversa', 'usuario', 'texto ficticio', 123, 'usuario', 'hash-parcial')
    )
    os._exit(23)
"""
    resultado = subprocess.run(
        [sys.executable, "-c", codigo, str(armazenamento.caminho_alfred)],
        cwd=Path(__file__).parents[2],
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 23
    chave_db = derivar_subchave(chave, "alfred.db")
    with abrir_conexao(
        armazenamento.caminho_alfred, chave_db, escritor=False
    ) as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM eventos WHERE id='evento-parcial'"
        ).fetchone()[0] == 0
        assert conexao.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

