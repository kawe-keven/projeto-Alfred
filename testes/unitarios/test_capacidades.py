from alfred.ferramentas.registro import Ferramenta, RegistroDeFerramentas
from alfred.nucleo.politicas.capacidades import montar_manifesto_capacidades


def test_manifesto_retrata_apenas_ferramentas_registradas_e_marca_simulacao():
    simulada = Ferramenta(
        "acao_teste", "Ação fictícia", {"type": "object", "properties": {}, "required": []},
        False, True, lambda: "ok", True,
    )
    real = Ferramenta(
        "consulta_teste", "Consulta fictícia", {"type": "object", "properties": {}, "required": []},
        False, True, lambda: "ok", False,
    )
    registro = RegistroDeFerramentas((simulada, real))

    manifesto = montar_manifesto_capacidades(
        registro, modelo="modelo-ficticio", url_base="http://localhost:11434"
    )

    assert "modelo-ficticio" in manifesto
    assert "endereço local" in manifesto
    assert "acao_teste (simulação)" in manifesto
    assert "consulta_teste (execução local)" in manifesto
    assert "controlar_luz" not in manifesto


def test_manifesto_nao_confunde_endpoint_externo_com_acesso_a_internet():
    registro = RegistroDeFerramentas(())
    manifesto = montar_manifesto_capacidades(registro, url_base="https://llm.example.test")

    assert "não confirma acesso à internet" in manifesto
    assert "Nenhuma ferramenta está disponível" in manifesto
