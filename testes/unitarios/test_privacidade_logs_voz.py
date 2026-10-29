from __future__ import annotations

import logging

from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz


def test_log_de_voz_nao_registra_texto_da_conversa(caplog) -> None:
    marcador = "SEGREDO-PRIVADO-NAO-REGISTRAR-987654"

    with caplog.at_level(logging.INFO, logger="alfred.voz"):
        OrquestradorDeVoz._registrar_conversa("escutado", marcador, "transcrito")
        OrquestradorDeVoz._registrar_conversa("dito", marcador, "reproducao_concluida")

    assert marcador not in caplog.text
    assert "evento=escutado" in caplog.text
    assert "resultado=transcrito" in caplog.text
