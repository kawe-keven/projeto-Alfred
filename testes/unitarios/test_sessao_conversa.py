import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from alfred.configuracao.configuracao import Configuracao
from alfred.interfaces.cli.app import FIM, SessaoConversa
from alfred.memoria.perfil.carregador import ARQUIVOS, carregar_perfil
from alfred.nucleo.agente.agente import Agente
from alfred.nucleo.provedor_llm import Mensagem


def criar_perfil(pasta, preferencias="REGRAS_FICTICIAS", fator="SENTINELA_PRIVADA"):
    pasta.mkdir(parents=True, exist_ok=True)
    corpos = {
        "preferencias": preferencias,
        "fatores_estaveis": fator,
        "conhecimento_abrangente": "CONHECIMENTO_FICTICIO",
    }
    for nome, corpo in corpos.items():
        (pasta / ARQUIVOS[nome]).write_text(
            f"---\nnome: {nome}\nversao: 1\natualizado: 2026-10-15\n---\n{corpo}",
            encoding="utf-8",
        )
    return carregar_perfil(pasta)


class FakeProvedor:
    def __init__(self):
        self.chamadas = []
        self.respostas = iter(("resposta-1", "resposta-2", "resposta-3"))

    def conversar(self, mensagens, *, sistema):
        self.chamadas.append((list(mensagens), sistema))
        yield next(self.respostas)


def test_prompt_de_voz_mantem_o_nome_alfred():
    agente = Agente(FakeProvedor(), "prompt base", modo_voz=True)

    assert "IDENTIDADE FIXA" in agente.sistema
    assert "seu nome é Alfred" in agente.sistema
    assert "Não negue nem contradiga esse nome" in agente.sistema


def criar_sessao(tmp_path, janela=20):
    pasta = tmp_path / "perfil"
    perfil = criar_perfil(pasta)
    configuracao = Configuracao(pasta_perfil=pasta, janela_mensagens=janela)
    provedor = FakeProvedor()
    sessao = SessaoConversa(
        provedor,
        configuracao,
        perfil,
        agora=datetime(2026, 10, 15, tzinfo=timezone.utc),
    )
    return sessao, provedor, pasta


def test_janela_de_historico_limita_mensagens_enviadas(tmp_path):
    sessao, provedor, _ = criar_sessao(tmp_path, janela=3)

    list(sessao.responder("pergunta-1"))
    list(sessao.responder("pergunta-2"))
    list(sessao.responder("pergunta-3"))

    mensagens = provedor.chamadas[-1][0]
    assert mensagens == [
        Mensagem("user", "pergunta-2"),
        Mensagem("assistant", "resposta-2"),
        Mensagem("user", "pergunta-3"),
    ]


def test_limpar_zera_historico(tmp_path):
    sessao, _, _ = criar_sessao(tmp_path)
    list(sessao.responder("mensagem ficticia"))

    assert sessao.executar_comando("/limpar") == "Histórico da conversa apagado."
    assert sessao.historico == []


def test_recarregar_reconstroi_prompt_com_perfil_atualizado(tmp_path):
    sessao, _, pasta = criar_sessao(tmp_path)
    prompt_anterior = sessao.prompt_sistema
    criar_perfil(pasta, preferencias="REGRA_NOVA_FICTICIA", fator="OUTRO_DADO")

    assert sessao.executar_comando("/recarregar") == "Perfil recarregado."
    assert sessao.prompt_sistema != prompt_anterior
    assert "REGRA_NOVA_FICTICIA" in sessao.prompt_sistema


def test_comando_perfil_exibe_metadados_sem_vazar_corpo(tmp_path):
    sessao, _, _ = criar_sessao(tmp_path)

    saida = sessao.executar_comando("/perfil")

    assert isinstance(saida, str)
    assert "preferencias: versão 1" in saida
    assert "SENTINELA_PRIVADA" not in saida
    assert "CONHECIMENTO_FICTICIO" not in saida
    assert "sha256 " in saida


def test_sair_retorna_sinal_de_encerramento(tmp_path):
    sessao, _, _ = criar_sessao(tmp_path)
    assert sessao.executar_comando("/sair") is FIM


def test_fontes_lista_origens_do_ultimo_turno_sem_exibir_conteudo(tmp_path):
    sessao, _, _ = criar_sessao(tmp_path)
    list(sessao.responder("pergunta fictícia"))

    fontes = sessao.executar_comando("/fontes")

    assert "Mensagem atual do usuário" in fontes
    assert "preferencias_ALFRED.md" in fontes
    assert "não são verificados" in fontes
    assert "SENTINELA_PRIVADA" not in fontes


def test_pergunta_sobre_conversa_anterior_indica_historico_indisponivel(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("alfred.memoria.armazenamento.rag.criar_rag", lambda *_args, **_kwargs: None)
    sessao, provedor, _ = criar_sessao(tmp_path)

    list(sessao.responder("O que conversamos antes sobre a viagem?"))

    assert 'status="indisponivel"' in provedor.chamadas[-1][1]


def test_resumo_das_ultimas_conversas_busca_historico_local(monkeypatch, tmp_path):
    class RAGFalso:
        ultima_fontes = []
        ultima_busca_disponivel = True

        def __init__(self):
            self.consultas = []

        def iniciar_sessao(self, _modelo):
            return "sessao-ficticia"

        def recuperar_conversas_recentes(self, consulta):
            self.consultas.append(consulta)
            self.ultima_fontes = ["conversa local fictícia"]
            return "HISTORICO_LOCAL_FICTICIO"

        def recuperar(self, _consulta):
            raise AssertionError("A pergunta sobre últimas conversas deve usar a busca histórica")

        def registrar_turno(self, *_args):
            pass

    rag = RAGFalso()
    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag",
        lambda *_args, **_kwargs: rag,
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    list(sessao.responder("Me dê um resumo das últimas conversas"))

    assert rag.consultas == ["Me dê um resumo das últimas conversas"]
    assert "HISTORICO_LOCAL_FICTICIO" in provedor.chamadas[-1][1]
    assert "<tarefa_resumo_historico>" in provedor.chamadas[-1][1]
    assert "perfil cadastrado" not in provedor.chamadas[-1][1]
    assert "HISTORICO_LOCAL_FICTICIO" in provedor.chamadas[-1][0][-1].conteudo
    assert "não responda com o perfil" in provedor.chamadas[-1][0][-1].conteudo
    assert not any("Perfil local:" in fonte for fonte in sessao.ultima_fontes)


def test_pedido_explicito_de_memoria_nao_finge_persistencia_sem_rag(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag",
        lambda *_args, **_kwargs: None,
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    resposta = list(sessao.responder(
        "Alfred, registre na memória que prefiro respostas curtas e diretas."
    ))

    assert "memória persistente está indisponível" in resposta[0]
    assert not provedor.chamadas


def test_pedido_explicito_de_memoria_confirma_so_apos_indexar(monkeypatch, tmp_path):
    class RAGFalso:
        repositorio = object()
        ultima_fontes = []

        def iniciar_sessao(self, _modelo):
            return "sessao-ficticia"

        def lembrar(self, texto):
            assert texto == "prefiro respostas curtas e diretas"
            return "memoria-ficticia"

        class banco:
            @staticmethod
            def buscar_eventos_por_ids(_ids):
                return [{"indexado": 1}]

    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag",
        lambda *_args, **_kwargs: RAGFalso(),
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    resposta = list(sessao.responder(
        "Alfred, registre na memória que prefiro respostas curtas e diretas."
    ))

    assert resposta == ["Preferência salva e indexada na memória vetorial."]
    assert not provedor.chamadas


def test_pergunta_historica_nao_confunde_indice_ausente_com_sem_resultado(
    monkeypatch, tmp_path
):
    class RAGSemIndice:
        ultima_fontes = []
        ultima_busca_disponivel = False

        def iniciar_sessao(self, _modelo):
            return "sessao-sem-indice"

        def recuperar(self, _consulta):
            self.ultima_busca_disponivel = False
            return ""

        def registrar_turno(self, *_args):
            return None

    rag = RAGSemIndice()
    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag", lambda *_args, **_kwargs: rag
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    list(sessao.responder("O que conversamos antes sobre a viagem?"))

    assert 'status="indisponivel"' in provedor.chamadas[-1][1]


def test_pergunta_historica_sem_resultado_explica_que_nao_ha_correspondencia(
    monkeypatch, tmp_path
):
    class RAGSemCorrespondencia:
        ultima_fontes = []
        ultima_busca_disponivel = True

        def iniciar_sessao(self, _modelo):
            return "sessao-sem-correspondencia"

        def recuperar(self, _consulta):
            return ""

        def registrar_turno(self, *_args):
            return None

    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag",
        lambda *_args, **_kwargs: RAGSemCorrespondencia(),
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    list(sessao.responder("O que conversamos antes sobre a viagem?"))

    prompt = provedor.chamadas[-1][1]
    assert 'status="sem_correspondencia"' in prompt
    assert 'status="indisponivel"' not in prompt


def test_cli_consulta_memoria_persistente_e_registra_turno_concluido(
    monkeypatch, tmp_path
) -> None:
    class RAGFalso:
        ultima_fontes = ["fonte=conversa anterior; tipo=conversa"]

        def __init__(self):
            self.turnos = []

        def iniciar_sessao(self, _modelo):
            return "sessao-ficticia"

        def recuperar(self, consulta):
            assert consulta == "O que falamos ontem?"
            return 'CONTEXTO_RECUPERADO: {"conteudo":"assunto da conversa antiga"}'

        def registrar_turno(self, usuario, alfred, sessao_id):
            self.turnos.append((usuario, alfred, sessao_id))

    rag = RAGFalso()
    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag", lambda *_args, **_kwargs: rag
    )
    sessao, provedor, _ = criar_sessao(tmp_path)

    assert list(sessao.responder("O que falamos ontem?")) == ["resposta-1"]

    assert "assunto da conversa antiga" in provedor.chamadas[-1][1]
    assert rag.turnos == [
        ("O que falamos ontem?", "resposta-1", "sessao-ficticia")
    ]


def test_comando_fontes_sem_turno_e_ajuda(tmp_path):
    sessao, _, _ = criar_sessao(tmp_path)

    assert "Ainda não há" in sessao.executar_comando("/fontes")
    assert "/fontes" in sessao.executar_comando("/ajuda")
    assert "/voz" in sessao.executar_comando("/ajuda")


def test_comando_lembrar_exige_confirmacao_e_grava(monkeypatch, tmp_path):
    class BancoFalso:
        def buscar_eventos_por_ids(self, _ids):
            return [{"indexado": 1}]

    class RAGFalso:
        banco = BancoFalso()

        def __init__(self):
            self.texto = None

        def iniciar_sessao(self, _modelo):
            return "sessao-ficticia"

        def lembrar(self, texto):
            self.texto = texto
            return "memoria-ficticia"

    rag = RAGFalso()
    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag", lambda *_args, **_kwargs: rag
    )
    pasta = tmp_path / "perfil"
    perfil = criar_perfil(pasta)
    configuracao = Configuracao(pasta_perfil=pasta)
    sessao = SessaoConversa(
        FakeProvedor(), configuracao, perfil, confirmar=lambda _pergunta: "sim"
    )

    resultado = sessao.executar_comando("/lembrar Prefiro respostas curtas")

    assert rag.texto == "Prefiro respostas curtas"
    assert resultado == "Memória guardada e indexada."


def test_comando_lembrar_nao_grava_sem_confirmacao(monkeypatch, tmp_path):
    class RAGFalso:
        def iniciar_sessao(self, _modelo):
            return "sessao-ficticia"

        def lembrar(self, _texto):
            raise AssertionError("não deve gravar sem confirmação")

    monkeypatch.setattr(
        "alfred.memoria.armazenamento.rag.criar_rag", lambda *_args, **_kwargs: RAGFalso()
    )
    pasta = tmp_path / "perfil"
    perfil = criar_perfil(pasta)
    configuracao = Configuracao(pasta_perfil=pasta)
    sessao = SessaoConversa(
        FakeProvedor(), configuracao, perfil, confirmar=lambda _pergunta: "talvez"
    )

    resultado = sessao.executar_comando("/lembrar informação sensível")

    assert "não guardada" in resultado


def test_comando_voz_exibe_somente_metadados(monkeypatch, tmp_path):
    class SintetizadorFalso:
        def __init__(self, *_args, **_kwargs):
            self.versao = None

        def verificar_disponibilidade(self):
            self.versao = "0.5.6"
            return True

    monkeypatch.setattr(
        "alfred.adaptadores.voz.tts_voicestudio.SintetizadorVoiceStudio",
        SintetizadorFalso,
    )
    sessao, _, _ = criar_sessao(tmp_path)

    saida = sessao.executar_comando("/voz")

    assert "omnivoice" in saida
    assert "0.5.6" in saida
    assert "loopback" in saida
    assert "fallback ativo: não" in saida
    assert "SENTINELA_PRIVADA" not in saida


def test_python_m_alfred_inicia_e_sai_com_perfil_ficticio(tmp_path):
    pasta_perfil = tmp_path / "perfil"
    criar_perfil(pasta_perfil)
    ambiente = os.environ.copy()
    ambiente["ALFRED_PASTA_PERFIL"] = str(pasta_perfil)
    ambiente["PYTHONIOENCODING"] = "utf-8"
    raiz = Path(__file__).resolve().parents[2]
    ambiente["PYTHONPATH"] = os.pathsep.join(
        [str(raiz / "src"), ambiente.get("PYTHONPATH", "")]
    )

    processo = subprocess.run(
        [sys.executable, "-m", "alfred"],
        input="/sair\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=raiz,
        env=ambiente,
        check=False,
    )

    assert processo.returncode == 0
    assert "Alfred pronto" in processo.stdout
    assert "Até mais" in processo.stdout
    assert "SENTINELA_PRIVADA" not in processo.stdout
