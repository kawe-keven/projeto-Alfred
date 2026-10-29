from alfred.nucleo.politicas.atualidade import marcador_de_atualidade


def test_pedido_instavel_sem_pesquisa_e_marcado_como_nao_verificavel():
    marcador = marcador_de_atualidade("Qual o preço atual deste produto?", ("consultar_hora",))

    assert 'status="sem_fonte_atual"' in marcador
    assert "Não há ferramenta de pesquisa externa" in marcador
    assert "não verificam notícias, preços, leis" in marcador


def test_pergunta_estavel_nao_recebe_alerta_de_atualidade():
    assert marcador_de_atualidade("Explique fotossíntese", ()) == ""


def test_ferramenta_de_pesquisa_disponivel_muda_a_instrução():
    marcador = marcador_de_atualidade("Quais as notícias de hoje?", ("pesquisar_web",))

    assert 'status="ferramenta_disponivel"' in marcador
    assert "informe a fonte" in marcador
