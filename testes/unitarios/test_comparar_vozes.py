import pytest

from scripts.comparar_vozes import FRASES, MOTORES_PT_BR, percentil95, validar_url


def test_comparador_usa_apenas_frases_ficticias_e_lista_motores_conhecidos():
    assert len(FRASES) == 10
    assert "omnivoice" in MOTORES_PT_BR
    assert all("Dona Exemplo" not in frase for frase in FRASES)


def test_comparador_rejeita_hosts_fora_de_loopback():
    with pytest.raises(ValueError, match="loopback"):
        validar_url("http://192.168.1.12:3900/v1")


def test_percentil_95_de_dez_amostras():
    assert percentil95([float(i) for i in range(10)]) == 9.0
    assert percentil95([]) is None
