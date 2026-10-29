from pathlib import Path

import pytest

from alfred.ferramentas.nativas import criar_arquivo


def configurar(pasta: Path, monkeypatch, *, arquivos=200, bytes_total=20 * 1024 * 1024, bytes_arquivo=1_000_000):
    monkeypatch.setenv("ALFRED_PASTA_ARQUIVOS", str(pasta))
    monkeypatch.setenv("ALFRED_ARQUIVOS_LIMITE_ARQUIVOS", str(arquivos))
    monkeypatch.setenv("ALFRED_ARQUIVOS_LIMITE_BYTES", str(bytes_total))
    monkeypatch.setenv("ALFRED_ARQUIVO_LIMITE_BYTES", str(bytes_arquivo))


def test_cria_md_e_txt_sem_sobrescrever(tmp_path, monkeypatch):
    configurar(tmp_path / "arquivos", monkeypatch)

    assert criar_arquivo.executar("nota", "texto fictício") == "Criei o arquivo nota.md."
    assert criar_arquivo.executar("lista.txt", "item") == "Criei o arquivo lista.txt."
    with pytest.raises(ValueError, match="já existe"):
        criar_arquivo.executar("NOTA.MD", "conteúdo novo")
    assert (tmp_path / "arquivos" / "nota.md").read_text(encoding="utf-8") == "texto fictício"


def test_recusa_extensao_nao_permitida(tmp_path, monkeypatch):
    configurar(tmp_path / "arquivos", monkeypatch)
    with pytest.raises(ValueError, match=".md ou .txt"):
        criar_arquivo.executar("nota.exe", "texto")


def test_limite_de_arquivos(tmp_path, monkeypatch):
    configurar(tmp_path / "arquivos", monkeypatch, arquivos=1)
    criar_arquivo.executar("primeiro", "a")
    with pytest.raises(ValueError, match="limite de 1 arquivos"):
        criar_arquivo.executar("segundo", "b")


def test_limite_de_bytes_totais_conta_utf8(tmp_path, monkeypatch):
    configurar(tmp_path / "arquivos", monkeypatch, bytes_total=2)
    criar_arquivo.executar("primeiro", "á")
    with pytest.raises(ValueError, match="limite total de 2 bytes"):
        criar_arquivo.executar("segundo", "a")


def test_limite_de_bytes_por_arquivo(tmp_path, monkeypatch):
    configurar(tmp_path / "arquivos", monkeypatch, bytes_arquivo=1)
    with pytest.raises(ValueError, match="ultrapassa o limite de 1 bytes"):
        criar_arquivo.executar("nota", "á")


def test_falha_na_gravacao_atomica_nao_deixa_arquivo_parcial_ou_temporario(
    tmp_path, monkeypatch
):
    pasta = tmp_path / "arquivos"
    configurar(pasta, monkeypatch)

    def falhar_link(*_args, **_kwargs):
        raise OSError("erro fictício")

    monkeypatch.setattr(criar_arquivo.os, "link", falhar_link)
    with pytest.raises(ValueError, match="atomicamente"):
        criar_arquivo.executar("falha", "conteúdo fictício")
    assert list(pasta.iterdir()) == []
