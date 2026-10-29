import asyncio

from alfred.ferramentas.resultado import ResultadoFerramenta
from alfred.nucleo.agente.agente import Agente
from alfred.nucleo.politicas.verificador_alegacoes import (
    alegacao_confirmada,
    e_alegacao_de_acao,
)
from alfred.nucleo.provedor_llm import EventoLLM


def test_alegacao_de_arquivo_exige_sucesso_da_ferramenta_correta():
    frase = "Criei o arquivo ficticio.md."

    assert e_alegacao_de_acao(frase)
    assert not alegacao_confirmada(frase, [])
    assert not alegacao_confirmada(frase, [ResultadoFerramenta("criar_arquivo", "falha", "erro")])
    assert alegacao_confirmada(
        frase, [ResultadoFerramenta("criar_arquivo", "sucesso", "criação concluída")]
    )
    assert not alegacao_confirmada(
        frase, [ResultadoFerramenta("criar_arquivo", "simulacao", "simulação")]
    )


def test_frase_informativa_sem_alegacao_nao_e_retida():
    assert not e_alegacao_de_acao("Posso ajudar a preparar um rascunho.")


def test_agente_faz_no_maximo_uma_retentativa_e_fallback_deterministico():
    class ProvedorFalso:
        def __init__(self):
            self.chamadas = 0

        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            self.chamadas += 1
            yield EventoLLM(texto="Criei o arquivo ficticio.md.")

    async def executar():
        provedor = ProvedorFalso()
        agente = Agente(provedor, "Instruções fictícias")
        respostas = [frase async for frase in agente.responder("Crie um arquivo fictício")]
        assert provedor.chamadas == 2
        assert respostas == ["Não consigo confirmar que essa ação foi realizada."]

    asyncio.run(executar())
