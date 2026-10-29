from alfred.blueprint.riscos import (
    LIMITES_FIXOS_BLUEPRINT,
    bloco_cuidados,
    classificar_risco,
    limite_aplicavel,
)


def test_drones_sao_alto_risco_com_cuidados():
    nivel, fatores = classificar_risco("Criar um drone de pesquisa")
    assert nivel == "alto"
    assert "drones e aeronaves não tripuladas" in fatores
    assert "Cuidados" in bloco_cuidados(nivel, fatores)
    assert limite_aplicavel("Montar projeto de drone militar") is None


def test_objetivos_bloqueados_tem_alternativa_e_limite_unico():
    assert limite_aplicavel("Projetar uma arma funcional") is not None
    assert limite_aplicavel("Criar malware") is not None
    assert LIMITES_FIXOS_BLUEPRINT


def test_mencao_de_seguranca_nao_bloqueia_projeto():
    assert limite_aplicavel("Criar um app de segurança para inventário de armas") is None
