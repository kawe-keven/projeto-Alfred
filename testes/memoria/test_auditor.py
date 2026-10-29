from __future__ import annotations

import socket

from scripts.auditar_memoria import SENTINELA_AUDITOR, main


def test_auditor_padrao_usa_dados_descartaveis_e_nao_tenta_rede(
    monkeypatch, capsys
) -> None:
    def bloquear(*_args, **_kwargs):
        raise AssertionError("o modo padrão do auditor tentou usar a rede")

    monkeypatch.setattr(socket.socket, "connect", bloquear)
    monkeypatch.setattr(socket, "create_connection", bloquear)
    assert main([]) == 0
    saida = capsys.readouterr().out
    assert "ambiente=temporario chave=aleatoria dados=ficticios" in saida
    assert "consultas=40" in saida
    assert "qualidade_semantica=nao_avaliada" in saida
    assert "rag_integrado_ao_cli_voz=sim" in saida
    assert "lacunas_fluxo_automatico=f,g,i" in saida
    assert SENTINELA_AUDITOR not in saida

