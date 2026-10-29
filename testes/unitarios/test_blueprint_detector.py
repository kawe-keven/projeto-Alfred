from alfred.blueprint.detector import classificar_tipo, detectar_pedido


def test_detecta_pedido_de_projeto_e_classifica_hibrido():
    pedido = detectar_pedido("Monte um projeto de drone com aplicativo de controle")
    assert pedido is not None
    assert pedido.tipo == "hibrido"


def test_distingue_digital_e_fisico():
    assert classificar_tipo("aplicativo de agenda") == "digital"
    assert classificar_tipo("móvel de madeira") == "fisico"


def test_conversa_sem_intencao_nao_vira_blueprint():
    assert detectar_pedido("Como funciona um aplicativo?") is None
