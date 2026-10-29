from pathlib import Path

import pytest

from alfred.ferramentas.nativas._caminhos import (
    normalizar_identificador,
    resolver_arquivo_confinado,
    resolver_pasta_confinada,
    validar_identificador,
    validar_nome_simples,
)


@pytest.mark.parametrize(
    "nome",
    ["..", "../fora", "C:\\fora", "\\\\servidor\\share", "a:b", "fim.", "fim ", "CON", "nul.txt", "x" * 101],
)
def test_nome_simples_recusa_caminhos_e_nomes_invalidos(nome):
    with pytest.raises(ValueError):
        validar_nome_simples(nome)


def test_identificador_de_pessoa_normaliza_acentos_e_espacos():
    assert normalizar_identificador("MáRia Clara") == "maria_clara"


@pytest.mark.parametrize("identificador", ["Maria", "../ana", "con", "a" * 41, "ana-clara"])
def test_identificador_restrito_a_formato_ascii(identificador):
    with pytest.raises(ValueError):
        validar_identificador(identificador)


def test_resolve_subpastas_e_arquivo_dentro_da_raiz(tmp_path: Path):
    pasta = resolver_pasta_confinada(tmp_path, "arquivos", criar=True)
    destino = resolver_arquivo_confinado(pasta, "nota.md")
    assert pasta == tmp_path / "arquivos"
    assert destino == pasta / "nota.md"


def test_recusa_link_simbolico_na_pasta(tmp_path: Path):
    fora = tmp_path / "fora"
    fora.mkdir()
    link = tmp_path / "arquivos"
    try:
        link.symlink_to(fora, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("O sistema não permite criar links simbólicos neste ambiente")
    with pytest.raises(ValueError, match="Links simbólicos"):
        resolver_pasta_confinada(tmp_path, "arquivos")
