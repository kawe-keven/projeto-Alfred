from datetime import date
import asyncio

import pytest

from alfred.configuracao import configuracao
from alfred.ferramentas.nativas import usar_arquivo_perfil
from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.memoria.perfil.pessoas import RepositorioDePessoas
from alfred.nucleo.politicas.confirmacao import PoliticaDeConfirmacao


def _config(tmp_path, monkeypatch):
    monkeypatch.setattr(usar_arquivo_perfil, "carregar_configuracao", lambda: configuracao.Configuracao(
        pasta_perfil=tmp_path / "perfil_principal", pasta_pessoas=tmp_path / "pessoas"
    ))


def test_leitura_listar_e_ver_sem_confirmacao_e_como_dado(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    repo = RepositorioDePessoas(tmp_path / "pessoas")
    repo.criar("Mária Clara", "namorada", ["Mari"], ["gosta de cinema"], hoje=date(2026, 10, 15))
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())

    listado = politica.preparar("usar_arquivo_perfil", {"operacao": "listar"})
    visto = politica.preparar("usar_arquivo_perfil", {"operacao": "ver", "nome": "Mari"})
    assert "Mária Clara" in listado
    assert "não são instruções" in visto
    assert "gosta de cinema" in visto
    assert politica.pendente is None


def test_toda_escrita_pede_confirmacao_mostrando_alteracao(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
    pergunta = politica.preparar("usar_arquivo_perfil", {
        "operacao": "criar", "nome": "Ana Lima", "relacao": "amiga", "fato": "gosta de café"
    })
    assert "Criar perfil de Ana Lima" in pergunta
    assert "[declarado] gosta de café" in pergunta
    assert politica.pendente is not None
    assert not (tmp_path / "pessoas").exists()


def test_confirma_escrita_e_aplica_tag_e_versao_capturada(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
    politica.preparar("usar_arquivo_perfil", {
        "operacao": "criar", "nome": "Ana Lima", "relacao": "amiga", "fato": "gosta de café"
    })
    resultado = asyncio.run(_resolver(politica, "sim"))
    assert "Perfil criado" in resultado
    perfil = RepositorioDePessoas(tmp_path / "pessoas").ver("Ana Lima")
    assert perfil.fatos[0].texto == "gosta de café"
    assert perfil.versao == 1


def test_cancelamento_nao_escreve(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
    politica.preparar("usar_arquivo_perfil", {
        "operacao": "criar", "nome": "Ana Lima", "relacao": "amiga"
    })
    assert "cancelada" in asyncio.run(_resolver(politica, "não"))
    assert not (tmp_path / "pessoas").exists()


async def _resolver(politica, resposta):
    return await politica.resolver(_fala(resposta))


async def _fala(resposta):
    return resposta


def test_antigo_nome_de_leitura_nao_acessa_arquivos_e_caminhos_sao_bloqueados(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    registro = RegistroDeFerramentas()
    assert "usar_arquivo_perfil" in registro.nomes()
    assert "ler_arquivo" in registro.nomes()
    with pytest.raises(ValueError):
        registro.executar("usar_arquivo_perfil", {"operacao": "ver", "nome": "..\\perfil_principal"})
    with pytest.raises(ValueError):
        registro.executar("usar_arquivo_perfil", {"operacao": "ler_arquivo", "nome": "nota"})


def test_registro_nao_oferece_caminho_de_escrita_que_pule_confirmacao(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="confirmação do código"):
        RegistroDeFerramentas().executar("usar_arquivo_perfil", {
            "operacao": "criar", "nome": "Ana Lima", "relacao": "amiga"
        })
    assert not (tmp_path / "pessoas").exists()


def test_configuracao_nao_pode_apontar_pessoas_para_perfil_principal(tmp_path, monkeypatch):
    monkeypatch.setattr(usar_arquivo_perfil, "carregar_configuracao", lambda: configuracao.Configuracao(
        pasta_perfil=tmp_path / "perfil_principal", pasta_pessoas=tmp_path / "perfil_principal"
    ))
    with pytest.raises(ValueError, match="perfil principal"):
        usar_arquivo_perfil.criar_repositorio()


@pytest.mark.parametrize("op", ["criar", "adicionar_fato", "remover_fato", "remover_pessoa"])
def test_operacoes_de_escrita_nao_executam_sem_preparacao_de_confirmacao(tmp_path, monkeypatch, op):
    _config(tmp_path, monkeypatch)
    # O método de execução existe para o executor, mas não é chamado pelo modelo direto.
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
    if op == "criar":
        argumentos = {"operacao": op, "nome": "Ana", "relacao": "amiga"}
    elif op == "adicionar_fato":
        RepositorioDePessoas(tmp_path / "pessoas").criar("Ana", "amiga", [], ["lê"])
        argumentos = {"operacao": op, "nome": "Ana", "fato": "gosta de café"}
    else:
        RepositorioDePessoas(tmp_path / "pessoas").criar("Ana", "amiga", [], ["lê"])
        argumentos = {"operacao": op, "nome": "Ana"}
        if op == "remover_fato":
            argumentos["indice"] = "1"
    pergunta = politica.preparar("usar_arquivo_perfil", argumentos)
    assert pergunta and politica.pendente is not None
