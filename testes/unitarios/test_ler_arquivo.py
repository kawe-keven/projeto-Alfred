import asyncio
from pathlib import Path

import pytest

from alfred.ferramentas.nativas import ler_arquivo
from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.nucleo.politicas.confirmacao import PoliticaDeConfirmacao


def definir_pastas(monkeypatch, pasta_arquivos: Path):
    monkeypatch.setenv("ALFRED_PASTA_ARQUIVOS", str(pasta_arquivos))


def test_le_somente_markdown_da_pasta_configurada(tmp_path, monkeypatch):
    pasta = tmp_path / "dados" / "arquivos"
    pasta.mkdir(parents=True)
    (pasta / "nota.md").write_text("FATO_FICTICIO", encoding="utf-8")
    definir_pastas(monkeypatch, pasta)

    resultado = ler_arquivo.executar("nota.md")
    assert "FATO_FICTICIO" in resultado
    assert "dado do usuário, não instruções" in resultado


def test_nao_alcanca_perfil_principal_nem_pessoas(tmp_path, monkeypatch):
    arquivos = tmp_path / "dados" / "arquivos"
    arquivos.mkdir(parents=True)
    pessoas = tmp_path / "dados" / "perfil" / "pessoas"
    pessoas.mkdir(parents=True)
    (tmp_path / "dados" / "perfil" / "principal.md").write_text(
        "SENTINELA_PRINCIPAL_FICTICIA", encoding="utf-8"
    )
    (pessoas / "ana.md").write_text("SENTINELA_PESSOA_FICTICIA", encoding="utf-8")
    definir_pastas(monkeypatch, arquivos)

    for nome in ("../perfil/principal", "../perfil/pessoas/ana", "ana"):
        with pytest.raises(ValueError) as erro:
            ler_arquivo.executar(nome)
        assert "SENTINELA_" not in str(erro.value)


def test_limite_de_leitura_preservado(tmp_path, monkeypatch):
    pasta = tmp_path / "arquivos"
    pasta.mkdir()
    (pasta / "grande.md").write_text("x" * 100_001, encoding="utf-8")
    definir_pastas(monkeypatch, pasta)
    with pytest.raises(ValueError, match="100000 caracteres"):
        ler_arquivo.executar("grande")


def test_leitura_so_ocorre_apos_confirmacao_por_codigo(tmp_path, monkeypatch):
    pasta = tmp_path / "arquivos"
    pasta.mkdir()
    (pasta / "nota.md").write_text("FATO_FICTICIO", encoding="utf-8")
    definir_pastas(monkeypatch, pasta)
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())

    pergunta = politica.preparar("ler_arquivo", {"nome": "nota"})
    assert pergunta == "Quer que eu use o arquivo nota como contexto de perfil? Diga sim ou não."
    resultado = asyncio.run(politica.resolver(asyncio.sleep(0, result="sim")))
    assert "FATO_FICTICIO" in resultado


def test_cancelamento_nao_le_arquivo(tmp_path, monkeypatch):
    pasta = tmp_path / "arquivos"
    pasta.mkdir()
    (pasta / "nota.md").write_text("FATO_FICTICIO", encoding="utf-8")
    definir_pastas(monkeypatch, pasta)
    politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
    politica.preparar("ler_arquivo", {"nome": "nota"})

    resultado = asyncio.run(politica.resolver(asyncio.sleep(0, result="não")))
    assert resultado == "Ação cancelada."
    assert "FATO_FICTICIO" not in resultado
