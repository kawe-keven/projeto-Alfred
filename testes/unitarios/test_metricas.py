from __future__ import annotations

from pathlib import Path

import pytest
from sqlcipher3 import dbapi2 as sqlcipher

from alfred.memoria.armazenamento.metricas import (
    ArmazenamentoDeMetricas,
    ErroMetrica,
)
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.migracao import aplicar_migracoes
from alfred.seguranca.chaves.derivacao import derivar_subchave


CHAVE_TESTE = bytes(range(32))
MIGRACOES_METRICAS = (
    Path(__file__).parents[2]
    / "src/alfred/memoria/armazenamento/migracoes_metricas"
)
AGORA_MS = 2_000_000_000_000


def criar_armazenamento(tmp_path: Path) -> ArmazenamentoDeMetricas:
    caminho = tmp_path / "metricas.db"
    aplicar_migracoes(
        caminho,
        derivar_subchave(CHAVE_TESTE, "metricas.db"),
        pasta_migracoes=MIGRACOES_METRICAS,
        finalidade="metricas",
    )
    return ArmazenamentoDeMetricas(
        caminho, CHAVE_TESTE, retencao_dias=2, relogio_ms=lambda: AGORA_MS
    )


def test_grava_apenas_campos_de_configuracao_e_numeros(tmp_path: Path) -> None:
    metricas = criar_armazenamento(tmp_path)
    identificador = metricas.inserir_latencia_turno(
        ts_ms=AGORA_MS,
        interface="voz",
        perfil_desempenho="balanceado",
        motor_tts="piper",
        modelo_stt="whisper_small",
        modelo_llm="local_model_1",
        ms_fim_fala_transcricao=120,
        ms_primeiro_token=340,
        ms_primeira_frase=500,
        ms_primeiro_audio=680,
        ms_total=2200,
        barge_in=True,
        id_metrica="metrica-teste",
    )
    metricas.inserir_uso_recursos(
        ts_ms=AGORA_MS, componente="llm", vram_mb=1024.5, ram_mb=2048
    )
    recuperacao_id = metricas.inserir_recuperacao_contexto(
        ts_ms=AGORA_MS,
        interface="cli",
        latencia_ms=45,
        itens=3,
        tokens_estimados=210,
    )
    from alfred.memoria.armazenamento.conexao import abrir_conexao

    chave = derivar_subchave(CHAVE_TESTE, "metricas.db")
    with abrir_conexao(tmp_path / "metricas.db", chave, finalidade="metricas", escritor=False) as conexao:
        linha = conexao.execute(
            "SELECT interface, perfil_desempenho, ms_total, barge_in FROM latencia_turnos WHERE id=?",
            (identificador,),
        ).fetchone()
        assert tuple(linha) == ("voz", "balanceado", 2200, 1)
        assert conexao.execute("SELECT count(*) FROM uso_recursos").fetchone()[0] == 1
        contexto = conexao.execute(
            "SELECT interface, latencia_ms, itens, tokens_estimados "
            "FROM recuperacao_contexto WHERE id=?", (recuperacao_id,)
        ).fetchone()
        assert tuple(contexto) == ("cli", 45, 3, 210)


def test_retencao_padrao_de_90_dias_e_configuravel(tmp_path: Path) -> None:
    caminho = tmp_path / "metricas.db"
    aplicar_migracoes(
        caminho,
        derivar_subchave(CHAVE_TESTE, "metricas.db"),
        pasta_migracoes=MIGRACOES_METRICAS,
        finalidade="metricas",
    )
    padrao = ArmazenamentoDeMetricas(caminho, CHAVE_TESTE)
    assert padrao.retencao_dias == 90
    metricas = ArmazenamentoDeMetricas(
        caminho, CHAVE_TESTE, retencao_dias=2, relogio_ms=lambda: AGORA_MS
    )
    for data in (AGORA_MS - 3 * 86_400_000, AGORA_MS - 2 * 86_400_000, AGORA_MS):
        metricas.inserir_uso_recursos(
            ts_ms=data, componente="stt", vram_mb=0, ram_mb=100
        )
    resultado = metricas.limpar_expiradas()
    assert resultado == {
        "latencia_turnos": 0,
        "uso_recursos": 1,
        "recuperacao_contexto": 0,
    }


def test_metricas_rejeitam_rotulo_com_conteudo_ou_valor_negativo(tmp_path: Path) -> None:
    metricas = criar_armazenamento(tmp_path)
    sentinela = "NOME PESSOAL FICTICIO"
    with pytest.raises(ErroMetrica) as erro:
        metricas.inserir_uso_recursos(
            ts_ms=AGORA_MS, componente=sentinela, vram_mb=0, ram_mb=0
        )
    assert sentinela not in str(erro.value)
    with pytest.raises(ErroMetrica):
        metricas.inserir_uso_recursos(
            ts_ms=AGORA_MS, componente="llm", vram_mb=-1, ram_mb=0
        )


def test_banco_de_metricas_rejeita_check_invalido(tmp_path: Path) -> None:
    metricas = criar_armazenamento(tmp_path)
    with pytest.raises(ErroMetrica):
        metricas.inserir_latencia_turno(
            ts_ms=AGORA_MS,
            interface="cli",
            perfil_desempenho="balanceado",
            barge_in=False,
            ms_total=-1,
        )
    chave = derivar_subchave(CHAVE_TESTE, "metricas.db")
    with pytest.raises(sqlcipher.IntegrityError):
        with abrir_conexao(
            tmp_path / "metricas.db", chave, finalidade="metricas"
        ) as conexao:
            conexao.execute(
                "INSERT INTO latencia_turnos(id, ts_ms, interface, perfil_desempenho, "
                "ms_total, barge_in) VALUES(?, ?, ?, ?, ?, ?)",
                ("invalid", AGORA_MS, "cli", "balanceado", -1, 0),
            )
