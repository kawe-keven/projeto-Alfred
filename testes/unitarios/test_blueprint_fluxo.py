import asyncio
from types import SimpleNamespace

from alfred.blueprint.detector import detectar_pedido
from alfred.blueprint import gerador
from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.nucleo.agente.agente import Agente
from alfred.nucleo.provedor_llm import Mensagem


class ProvedorQueNaoDeveSerConsultado:
    def conversar_com_ferramentas(self, *args, **kwargs):
        raise AssertionError("Pedido explícito deve executar o gerador, não gerar texto livre")


def test_pedido_explicito_de_drone_vai_para_blueprint_sem_recusa_generica():
    texto = "Alfred, monte um projeto de um novo drone militar"
    pedido = detectar_pedido(texto)
    assert pedido is not None
    assert pedido.tipo == "fisico"

    registro = RegistroDeFerramentas(provedor=object())
    chamadas = []

    def executar(nome, argumentos):
        chamadas.append((nome, argumentos))
        return "Blueprint criado: drone militar\nTipo: fisico | Risco: alto\nPasta: projetos/drone-militar"

    registro.executar = executar
    agente = Agente(
        ProvedorQueNaoDeveSerConsultado(), "prompt", registro=registro, modo_voz=True
    )

    async def coletar():
        return [parte async for parte in agente.responder(texto)]

    resposta = asyncio.run(coletar())
    assert len(chamadas) == 1
    assert chamadas[0][0] == "criar_projeto_blueprint"
    assert "Blueprint criado" in "".join(resposta)


def test_pedido_mostre_blueprint_recupera_projeto_do_historico(tmp_path, monkeypatch):
    monkeypatch.setattr(gerador, "RAIZ_PROJETO", tmp_path)

    class ProvedorFalso:
        def conversar(self, mensagens, *, sistema):
            yield "Seção gerada com premissas a confirmar."

    class RegistroFalso:
        def executar(self, nome, argumentos):
            assert nome == "criar_projeto_blueprint"
            return gerador.criar_projeto_blueprint(
                argumentos["descricao"],
                argumentos["tipo"],
                provedor=ProvedorFalso(),
                raiz=tmp_path,
            )

    from alfred.interfaces.cli.sessao import SessaoConversa

    sessao = SessaoConversa.__new__(SessaoConversa)
    sessao.ultimo_blueprint = None
    sessao.historico = [Mensagem("user", "Monte um projeto de aplicativo de tarefas")]
    sessao.registro_ferramentas = RegistroFalso()
    sessao.configuracao = SimpleNamespace(janela_mensagens=20)
    sessao.rag = None
    sessao.id_sessao = None

    resposta = "".join(sessao.responder("Me mostre o blueprint desse projeto"))
    assert resposta.count("# ") >= 9
    assert "Pasta: " not in resposta
    assert sessao.ultimo_blueprint is not None
    assert (sessao.ultimo_blueprint / "blueprint.json").is_file()
