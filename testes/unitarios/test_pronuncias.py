from alfred.adaptadores.voz.texto_voz import (
    aplicar_pronuncias,
    carregar_dicionario_pronuncia,
    normalizar_texto_para_voz,
)


def test_carrega_pronuncias_genericas_e_pessoais_em_ordem(tmp_path):
    publico = tmp_path / "pronuncias.toml"
    pessoal = tmp_path / "pronuncias_pessoais.toml"
    publico.write_text('[termos]\nOllama = "Olama"\nSQLite = "Siqueláite"\n', encoding="utf-8")
    pessoal.write_text('[termos]\n"Dona Exemplo" = "dona Egzemplo"\n', encoding="utf-8")

    dicionario = carregar_dicionario_pronuncia(publico, pessoal)

    assert dicionario == {
        "Ollama": "Olama",
        "SQLite": "Siqueláite",
        "Dona Exemplo": "dona Egzemplo",
    }


def test_respelling_case_insensitive_antes_da_normalizacao():
    preparado = aplicar_pronuncias("Ollama, CHROMA e 10:30", {
        "Ollama": "Olama",
        "Chroma": "Crôma",
    })

    assert normalizar_texto_para_voz(preparado) == (
        "Olama, Crôma e dez horas e trinta minutos"
    )
