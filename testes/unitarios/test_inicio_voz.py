import time

import pytest

from alfred.interfaces.ciclo_de_voz.app import _executar_com_progresso
from alfred.interfaces.ciclo_de_voz.app import montar_contexto_memoria


def test_etapa_longa_mostra_status_e_duracao_sem_expor_conteudo(capsys):
    _executar_com_progresso("modelo fictício", lambda: time.sleep(0.025), intervalo_s=0.005)

    saida = capsys.readouterr().out
    assert "Iniciando: modelo fictício" in saida
    assert "Ainda carregando modelo fictício" in saida
    assert "Pronto: modelo fictício" in saida
    assert "s" in saida


def test_etapa_com_falha_informa_estado_e_propaga_erro(capsys):
    def falhar():
        raise RuntimeError("erro fictício")

    with pytest.raises(RuntimeError):
        _executar_com_progresso("componente fictício", falhar)

    saida = capsys.readouterr().out
    assert "Falha ao carregar componente fictício" in saida
    assert "erro fictício" not in saida


def test_voz_busca_historico_compartilhado_com_a_cli():
    class RAGFalso:
        def recuperar_conversas_recentes(self, consulta):
            assert consulta == "O que conversamos antes sobre o projeto?"
            return "HISTÓRICO COMPARTILHADO"

        def recuperar(self, _consulta):
            raise AssertionError("Perguntas sobre histórico devem usar a busca compartilhada")

    contexto = montar_contexto_memoria(
        RAGFalso(), "O que conversamos antes sobre o projeto?"
    )

    assert "HISTÓRICO COMPARTILHADO" in contexto
