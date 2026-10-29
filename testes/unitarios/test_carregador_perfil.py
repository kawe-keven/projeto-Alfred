from pathlib import Path

import pytest

from alfred.memoria.perfil.carregador import ARQUIVOS, ErroDePerfil, carregar_perfil


NOMES = ("fatores_estaveis", "conhecimento_abrangente", "preferencias")


def escrever_perfil(pasta: Path, nome: str, corpo: str = "conteudo ficticio") -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / ARQUIVOS[nome]
    caminho.write_text(
        f"---\nnome: {nome}\nversao: 1\natualizado: 2026-10-15\n---\n{corpo}\n",
        encoding="utf-8",
    )
    return caminho


def criar_perfil_valido(pasta: Path) -> Path:
    for nome in NOMES:
        escrever_perfil(pasta, nome)
    return pasta


def test_carrega_perfil_valido_com_hash_estavel(tmp_path):
    pasta = criar_perfil_valido(tmp_path / "perfil")

    primeiro = carregar_perfil(pasta)
    segundo = carregar_perfil(pasta)

    assert primeiro == segundo
    assert len(primeiro.preferencias.sha256) == 64
    assert primeiro.preferencias.atualizado.isoformat() == "2026-10-15"


def test_arquivo_ausente_gera_erro_claro(tmp_path):
    escrever_perfil(tmp_path, "fatores_estaveis")

    with pytest.raises(ErroDePerfil, match="arquivo não encontrado"):
        carregar_perfil(tmp_path)


def test_cabecalho_sem_fechamento_gera_erro(tmp_path):
    pasta = criar_perfil_valido(tmp_path)
    (pasta / ARQUIVOS["preferencias"]).write_text(
        "---\nnome: preferencias\nversao: 1\natualizado: 2026-10-15\n",
        encoding="utf-8",
    )

    with pytest.raises(ErroDePerfil, match="não foi fechado"):
        carregar_perfil(pasta)


def test_yaml_quebrado_gera_erro_sem_repetir_conteudo(tmp_path):
    pasta = criar_perfil_valido(tmp_path)
    (pasta / ARQUIVOS["preferencias"]).write_text(
        "---\nnome: preferencias\ncampo: [DADO_SENTINELA\n---\ncorpo",
        encoding="utf-8",
    )

    with pytest.raises(ErroDePerfil, match="YAML inválido") as erro:
        carregar_perfil(pasta)
    assert "DADO_SENTINELA" not in str(erro.value)


def test_campo_obrigatorio_ausente_gera_erro(tmp_path):
    pasta = criar_perfil_valido(tmp_path)
    (pasta / ARQUIVOS["preferencias"]).write_text(
        "---\nnome: preferencias\nversao: 1\n---\ncorpo", encoding="utf-8"
    )

    with pytest.raises(ErroDePerfil, match="campos obrigatórios ausentes"):
        carregar_perfil(pasta)


def test_nome_do_cabecalho_deve_corresponder_ao_arquivo(tmp_path):
    pasta = criar_perfil_valido(tmp_path)
    (pasta / ARQUIVOS["preferencias"]).write_text(
        "---\nnome: outro\nversao: 1\natualizado: 2026-10-15\n---\ncorpo",
        encoding="utf-8",
    )

    with pytest.raises(ErroDePerfil, match="nome.*igual ao nome do arquivo"):
        carregar_perfil(pasta)


def test_arquivo_fora_de_utf8_gera_erro(tmp_path):
    pasta = criar_perfil_valido(tmp_path)
    (pasta / ARQUIVOS["preferencias"]).write_bytes(b"\xff\xfe\xfd")

    with pytest.raises(ErroDePerfil, match="não está em UTF-8"):
        carregar_perfil(pasta)


def test_link_simbolico_e_recusado(tmp_path):
    pasta = criar_perfil_valido(tmp_path / "perfil")
    original = pasta / ARQUIVOS["fatores_estaveis"]
    destino = tmp_path / "alvo.md"
    destino.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    original.unlink()
    try:
        original.symlink_to(destino)
    except (OSError, NotImplementedError):
        pytest.skip("Criação de link simbólico indisponível neste Windows")

    with pytest.raises(ErroDePerfil, match="links simbólicos não são permitidos"):
        carregar_perfil(pasta)
