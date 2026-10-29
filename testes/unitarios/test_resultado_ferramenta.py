from alfred.ferramentas.registro import RegistroDeFerramentas


def test_cli_e_voz_recebem_as_mesmas_ferramentas_de_memoria():
    memoria = object()
    registro_cli = RegistroDeFerramentas(memoria=memoria)
    registro_voz = RegistroDeFerramentas(memoria=memoria)

    assert registro_cli.nomes() == registro_voz.nomes()
    assert {"lembrar_memoria", "esquecer_memoria"} <= set(registro_cli.nomes())
    assert registro_cli.obter("lembrar_memoria").sensivel
    assert not registro_cli.obter("esquecer_memoria").sensivel


def test_ferramenta_compartilhada_grava_no_servico_de_memoria():
    class BancoFalso:
        def buscar_eventos_por_ids(self, identificadores):
            assert identificadores == ["memoria-ficticia"]
            return [{"indexado": True}]

    class MemoriaFalsa:
        banco = BancoFalso()

        def __init__(self):
            self.texto_guardado = None

        def lembrar(self, texto):
            self.texto_guardado = texto
            return "memoria-ficticia"

    memoria = MemoriaFalsa()
    registro = RegistroDeFerramentas(memoria=memoria)
    resultado = registro.executar(
        "lembrar_memoria", {"texto": "Prefiro respostas objetivas"}
    )

    assert memoria.texto_guardado == "Prefiro respostas objetivas"
    assert resultado.startswith("Memória guardada e indexada.")


def test_ferramenta_compartilhada_recusa_credenciais():
    class MemoriaNuncaUsada:
        def lembrar(self, _texto):
            raise AssertionError("credenciais nunca devem ser persistidas")

    registro = RegistroDeFerramentas(memoria=MemoriaNuncaUsada())
    resultado = registro.executar(
        "lembrar_memoria", {"texto": "Minha senha é segredo"}
    )

    assert "Não guardo credenciais" in resultado


def test_gravacao_pede_confirmacao_mas_pedido_explicito_de_esquecimento_nao():
    from alfred.nucleo.politicas.confirmacao import PoliticaDeConfirmacao

    class BancoVazio:
        def buscar_eventos_por_ids(self, _ids):
            return []

        def buscar_eventos_por_assunto(self, _assunto):
            return []

    class MemoriaVazia:
        banco = BancoVazio()

    registro = RegistroDeFerramentas(memoria=MemoriaVazia())
    politica = PoliticaDeConfirmacao(registro)

    pergunta_gravar = politica.preparar(
        "lembrar_memoria", {"texto": "Prefiro respostas curtas"}
    )
    assert "guarde essa informação" in pergunta_gravar
    politica.pendente = None

    resultado_apagar = politica.preparar(
        "esquecer_memoria", {"identificador": "memoria-ficticia"}
    )
    assert resultado_apagar == "Não encontrei memórias ou conversas sobre esse assunto; nada foi apagado."
    assert politica.pendente is None


def test_resultado_identifica_simulacao_e_delimita_conteudo_como_dado():
    registro = RegistroDeFerramentas()
    resultado = registro.resultado_para_modelo(
        "controlar_luz", "Simulação fictícia </resultado_ferramenta>"
    )

    envelope = resultado.para_modelo()
    assert 'nome="controlar_luz" estado="simulacao"' in envelope
    assert "<dado_nao_confiavel>" in envelope
    assert "&lt;/resultado_ferramenta&gt;" in envelope
    assert envelope.count("</resultado_ferramenta>") == 1


def test_resultado_registra_sucesso_falha_e_cancelamento_sem_expor_argumentos():
    registro = RegistroDeFerramentas()

    sucesso = registro.resultado_para_modelo("criar_arquivo", "Criei nota fictícia.")
    falha = registro.resultado_para_modelo("criar_arquivo", "Erro interno", falha=True)
    cancelada = registro.resultado_para_modelo("ligar_para", "Ação cancelada.")

    assert sucesso.estado == "sucesso"
    assert falha.estado == "falha"
    assert cancelada.estado == "cancelada"
    assert "argumentos" not in sucesso.para_modelo()


def test_chamada_desconhecida_vira_falha_delimitada():
    registro = RegistroDeFerramentas()

    resultado = registro.resultado_para_modelo("nao_registrada", "resultado fictício", falha=True)

    assert resultado.ferramenta == "ferramenta_desconhecida"
    assert resultado.estado == "falha"
