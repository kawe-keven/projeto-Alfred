from pathlib import Path

import yaml


def test_cenarios_sao_ficticios_e_nao_usam_ferramentas_reais():
    caminho = Path(__file__).parents[1] / "cenarios" / "honestidade.yaml"
    cenarios = yaml.safe_load(caminho.read_text(encoding="utf-8"))["cenarios"]

    assert {c["id"] for c in cenarios} == {
        "memoria_pessoal_ausente", "acao_simulada", "criacao_com_falha"
    }
    assert all("fict" in c["prompt"].casefold() for c in cenarios)
    assert all(set(c["ferramentas"]) <= {"controlar_luz", "criar_arquivo"} for c in cenarios)
