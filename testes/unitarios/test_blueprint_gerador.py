import json

from alfred.blueprint.gerador import criar_projeto_blueprint


class ProvedorFalso:
    def __init__(self):
        self.prompts = []

    def conversar(self, mensagens, *, sistema):
        self.prompts.append(mensagens[0].conteudo)
        yield "Conteúdo de exemplo com premissas explícitas e validação pendente."


def test_gera_pacote_completo_e_nao_sobrescreve(tmp_path):
    primeira = criar_projeto_blueprint(
        "Criar aplicativo para organizar tarefas", provedor=ProvedorFalso(), raiz=tmp_path
    )
    assert "Blueprint criado" in primeira
    pasta = tmp_path / "projetos" / "aplicativo-para-organizar-tarefas"
    assert (pasta / "blueprint.json").is_file()
    metadados = json.loads((pasta / "blueprint.json").read_text(encoding="utf-8"))
    assert metadados["tipo"] == "digital"
    assert len(metadados["arquivos"]) == 9
    assert all((pasta / nome).is_file() for nome in metadados["arquivos"])
    assert "```mermaid" in (pasta / "02-arquitetura.md").read_text(encoding="utf-8")

    segunda = criar_projeto_blueprint(
        "Criar aplicativo para organizar tarefas", provedor=ProvedorFalso(), raiz=tmp_path
    )
    assert (tmp_path / "projetos" / "aplicativo-para-organizar-tarefas-2").is_dir()
    assert "projeto-2" not in segunda


def test_bloqueio_nao_cria_pasta(tmp_path):
    resposta = criar_projeto_blueprint(
        "Projetar uma arma funcional", provedor=ProvedorFalso(), raiz=tmp_path
    )
    assert "Não posso criar" in resposta
    assert not (tmp_path / "projetos").exists()


def test_drone_militar_nao_armado_e_gerado_com_risco_alto(tmp_path):
    provedor = ProvedorFalso()
    resposta = criar_projeto_blueprint(
        "Monte um projeto de um novo drone militar",
        tipo="fisico",
        provedor=provedor,
        raiz=tmp_path,
    )
    assert "Blueprint criado" in resposta
    assert "Risco: alto" in resposta
    pastas = list((tmp_path / "projetos").iterdir())
    assert len(pastas) == 1
    riscos = (pastas[0] / "05-riscos-e-seguranca.md").read_text(encoding="utf-8")
    assert "Cuidados — risco alto" in riscos
    assert "plataforma não armada" in provedor.prompts[0]
