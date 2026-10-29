import asyncio
import logging
import sys
from types import SimpleNamespace

import pytest

from alfred.ferramentas.registro import RegistroDeFerramentas
from alfred.nucleo.agente.agente import Agente, DivisorDeFrases
from alfred.nucleo.politicas.confirmacao import PoliticaDeConfirmacao
from alfred.nucleo.provedor_llm import ChamadaFerramenta, EventoLLM
from alfred.interfaces.ciclo_de_voz.orquestrador import EstadoVoz, OrquestradorDeVoz
from alfred.interfaces.ciclo_de_voz.app import (
    montar_contexto_memoria,
    registrar_turno_memoria,
)
from alfred.adaptadores.voz.vad import DetectorDeVoz
from alfred.adaptadores.voz import stt as modulo_stt
from alfred.adaptadores.voz.stt import TranscritorLocal, normalizar_transcricao_pt_br
from alfred.adaptadores.voz.texto_voz import (
    dividir_primeira_frase_em_oracoes,
    normalizar_texto_para_voz,
)
from alfred.nucleo.agente.roteador_rapido import rotear_comando


def test_divisor_de_frases_mantem_abreviacao_decimal_e_fragmentos():
    divisor = DivisorDeFrases()
    assert divisor.adicionar("São 2.") == []
    assert divisor.adicionar("5 volts, Sr.") == []
    assert divisor.adicionar(" Silva. Tudo certo!") == ["São 2.5 volts, Sr. Silva."]
    assert divisor.finalizar() == "Tudo certo!"


def test_divisor_aguarda_terminar_oracao_antes_de_enviar_ao_tts():
    divisor = DivisorDeFrases()
    assert divisor.adicionar("Laranjeiras e no desenvolvimento dos seus projetos em") == []
    assert divisor.adicionar(" tecnologia.") == []
    assert divisor.finalizar() == (
        "Laranjeiras e no desenvolvimento dos seus projetos em tecnologia."
    )


def test_sintetizador_passa_velocidade_configurada_ao_piper(tmp_path, monkeypatch):
    from alfred.adaptadores.voz.tts import SintetizadorPiper

    chamadas = []
    class ConfiguracaoSintese:
        def __init__(self, *, length_scale):
            self.length_scale = length_scale
    class Voz:
        config = SimpleNamespace(sample_rate=22050)
        def synthesize(self, texto, *, syn_config):
            chamadas.append((texto, syn_config.length_scale))
            yield SimpleNamespace(audio_float_array=[0.0])
    class Stream:
        latency = 0.01
        blocksize = 0
        active = True
        def start(self): pass
        def write(self, _audio): pass
        def abort(self): pass
        def close(self): pass
    class Piper:
        @staticmethod
        def load(_caminho): return Voz()
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(
        asarray=lambda valores, dtype=None: valores,
        concatenate=lambda blocos: list(blocos),
        float32="float32",
    ))
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        OutputStream=lambda **_kwargs: Stream()
    ))
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(
        PiperVoice=Piper, SynthesisConfig=ConfiguracaoSintese
    ))
    arquivo = tmp_path / "voz.onnx"
    arquivo.write_bytes(b"modelo-ficticio")
    sintetizador = SintetizadorPiper(str(arquivo), length_scale=1.4)

    sintetizador.carregar()
    sintetizador.sintetizar("Frase de teste.")

    assert chamadas
    assert all(escala == 1.4 for _, escala in chamadas)
    sintetizador.fechar()


def test_push_to_talk_confirma_inicio_imediatamente(capsys):
    class VAD:
        def __init__(self):
            self.resetadas = 0

        def resetar(self):
            self.resetadas += 1

    vad = VAD()
    orquestrador = OrquestradorDeVoz(object(), vad, object(), object(), object())

    orquestrador.ativar_manual()

    assert orquestrador._apertado
    assert orquestrador.estado is EstadoVoz.OUVINDO
    assert vad.resetadas == 1
    assert "Pode falar agora." in capsys.readouterr().out


def test_push_to_talk_nao_arma_enquanto_microfone_esta_mudo(capsys):
    class VAD:
        def resetar(self):
            pass

    orquestrador = OrquestradorDeVoz(object(), VAD(), object(), object(), object())
    orquestrador.mudo = True

    orquestrador.ativar_manual()

    assert not orquestrador._apertado
    assert "Microfone silenciado" in capsys.readouterr().out


def test_modo_conversa_detecta_fala_sem_apertar_espaco(capsys):
    class Captura:
        async def frames(self):
            yield object()
    class VAD:
        chamadas = 0
        def processar(self, _frame, **_kwargs):
            self.chamadas += 1
            return "inicio", object()
        def resetar(self): pass

    vad = VAD()
    orquestrador = OrquestradorDeVoz(
        Captura(), vad, object(), object(), object(), modo="conversa"
    )
    asyncio.run(orquestrador._ler_microfone())

    assert vad.chamadas == 1
    assert not orquestrador._apertado
    assert "Conversa contínua ativa" in capsys.readouterr().out


def test_primeira_fala_e_a_resposta_real_sem_aviso_de_espera():
    class STT:
        def transcrever(self, _audio):
            return SimpleNamespace(texto="pergunta fictícia", confianca=0.45)
    class TTS:
        def __init__(self): self.tocadas = []
        def sintetizar(self, texto): return texto, 16000
        def reproduzir(self, audio, _taxa): self.tocadas.append(audio)
        def parar(self): pass
    class AgenteFalso:
        provedor = object()
        async def responder(self, texto, receber_confirmacao=None, ao_primeiro_token=None):
            await asyncio.sleep(0.04)
            yield "Resposta fictícia."

    async def executar():
        tts = TTS()
        orquestrador = OrquestradorDeVoz(
            object(), object(), STT(), tts, AgenteFalso(),
        )
        await orquestrador._processar([0.0], 1.0)
        assert tts.tocadas == ["Resposta fictícia."]

    asyncio.run(executar())


def test_registro_recusa_argumentos_invalidos():
    registro = RegistroDeFerramentas()
    with pytest.raises(ValueError):
        registro.executar("controlar_luz", {"comodo": "sala", "acao": "ligar", "extra": "injetado"})
    with pytest.raises(ValueError):
        registro.executar("ligar_para", {"contato": " "})


@pytest.mark.parametrize(("fala", "esperado"), [("sim", True), ("não", False), ("talvez", None), ("pode", True)])
def test_confirmacao_verbal_e_exclusivamente_regras(fala, esperado):
    from alfred.nucleo.politicas.confirmacao import interpretar_confirmacao
    assert interpretar_confirmacao(fala) is esperado


def test_confirmacao_sensivel_executa_apenas_com_sim():
    async def executar():
        registro = RegistroDeFerramentas()
        politica = PoliticaDeConfirmacao(registro)
        pergunta = politica.preparar("ligar_para", {"contato": "Ana"})
        assert pergunta == "Quer que eu ligue para Ana? Diga sim ou não."
        resultado = await politica.resolver(asyncio.sleep(0, result="sim"))
        assert resultado == "Simulação de ligação recebida."
        assert politica.pendente is None
    asyncio.run(executar())


@pytest.mark.parametrize("fala", ["não", "talvez"])
def test_nao_ou_ambigua_cancela(fala):
    async def executar():
        politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
        politica.preparar("ligar_para", {"contato": "Ana"})
        resultado = await politica.resolver(asyncio.sleep(0, result=fala))
        assert "cancelada" in resultado.lower()
    asyncio.run(executar())


def test_silencio_cancela_confirmacao():
    async def executar():
        politica = PoliticaDeConfirmacao(RegistroDeFerramentas(), timeout_s=0.001)
        politica.preparar("ligar_para", {"contato": "Ana"})
        resultado = await politica.resolver(asyncio.Event().wait())
        assert "cancelada" in resultado.lower()
    asyncio.run(executar())


def test_confirmacao_de_voz_com_baixa_confianca_nao_autoriza_acao():
    class STT:
        def transcrever(self, _audio):
            return SimpleNamespace(texto="sim", confianca=0.1)

    async def executar():
        politica = PoliticaDeConfirmacao(RegistroDeFerramentas())
        politica.preparar("ligar_para", {"contato": "Ana"})
        orquestrador = OrquestradorDeVoz(None, None, STT(), None, None)
        orquestrador._turnos.put_nowait(([], 0.0))

        async def confirmar():
            return await orquestrador._aguardar_confirmacao()

        resultado = await politica.resolver(confirmar())
        assert "cancelada" in resultado.casefold()
        assert politica.pendente is None

    asyncio.run(executar())


class LLMFalso:
    def __init__(self):
        self.chamadas = 0
        self.contextos = []

    def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
        self.chamadas += 1
        self.contextos.append(list(mensagens))
        if self.chamadas == 1:
            yield EventoLLM(chamadas=(ChamadaFerramenta("controlar_luz", {"comodo": "sala", "acao": "ligar"}),))
        else:
            yield EventoLLM(texto="Aumentei a luz.")
            yield EventoLLM(texto=" Pronto.")


def test_agente_retem_resultado_de_ferramenta_e_contexto():
    async def executar():
        provedor = LLMFalso()
        agente = Agente(provedor, "regras fictícias", limite_interacoes=1)
        resposta = [x async for x in agente.responder("tá escuro")]
        assert resposta == ["Aumentei a luz.", "Pronto."]
        assert any(m.papel == "tool" for m in agente.historico)
        outra = [x async for x in agente.responder("aumenta mais um pouco")]
        assert outra
        assert any(m.conteudo == "aumenta mais um pouco" for m in provedor.contextos[-1])
    asyncio.run(executar())


def test_voz_recupera_conversa_anterior_e_persiste_turno_concluido():
    class RAGFalso:
        def __init__(self):
            self.turnos = []
            self.consultas = []

        def recuperar(self, consulta):
            self.consultas.append(consulta)
            return 'CONTEXTO_RECUPERADO: {"conteudo":"assunto da conversa antiga"}'

        def registrar_turno(self, usuario, alfred, sessao_id):
            self.turnos.append((usuario, alfred, sessao_id))

    class Provedor:
        def __init__(self):
            self.sistemas = []

        def conversar_com_ferramentas(self, _mensagens, *, sistema, ferramentas):
            self.sistemas.append(sistema)
            yield EventoLLM(texto="Isso já foi conversado.")

    async def executar():
        rag = RAGFalso()
        provedor = Provedor()
        agente = Agente(
            provedor,
            "regras fictícias",
            modo_voz=True,
            contexto_por_mensagem=lambda texto: montar_contexto_memoria(rag, texto),
            registrar_conversa=lambda usuario, resposta: registrar_turno_memoria(
                rag, "sessao-voz-ficticia", usuario, resposta
            ),
        )

        resposta = [fala async for fala in agente.responder("O que conversamos antes?")]

        assert resposta == ["Isso já foi conversado."]
        assert rag.consultas == ["O que conversamos antes?"]
        assert "assunto da conversa antiga" in provedor.sistemas[-1]
        assert rag.turnos == [
            ("O que conversamos antes?", "Isso já foi conversado.", "sessao-voz-ficticia")
        ]

    asyncio.run(executar())


def test_voz_distingue_indice_indisponivel_de_busca_sem_correspondencia():
    class RAGSemIndice:
        ultima_busca_disponivel = False

        def recuperar(self, _consulta):
            return ""

    contexto = montar_contexto_memoria(RAGSemIndice(), "O que conversamos antes?")

    assert 'status="indisponivel"' in contexto

    class RAGSemCorrespondencia:
        ultima_busca_disponivel = True

        def recuperar(self, _consulta):
            return ""

    contexto_sem_resultado = montar_contexto_memoria(
        RAGSemCorrespondencia(), "O que conversamos antes?"
    )
    assert 'status="sem_correspondencia"' in contexto_sem_resultado
    assert 'status="indisponivel"' not in contexto_sem_resultado


def test_bloco_de_linguagem_falada_aparece_somente_no_modo_voz():
    class LLMQueRegistraSistema:
        def __init__(self): self.sistemas = []
        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            self.sistemas.append(sistema)
            yield EventoLLM(texto="Entendido.")

    async def obter_sistema(modo_voz):
        provedor = LLMQueRegistraSistema()
        agente = Agente(provedor, "regras fictícias", modo_voz=modo_voz)
        _ = [frase async for frase in agente.responder("fala fictícia")]
        return provedor.sistemas[0]

    sistema_texto = asyncio.run(obter_sistema(False))
    sistema_voz = asyncio.run(obter_sistema(True))
    assert "MODO VOZ" not in sistema_texto
    assert "MODO VOZ" in sistema_voz
    assert "erros de transcrição" in sistema_voz


def test_horario_volatil_fica_no_fim_do_prompt_de_voz():
    from datetime import date, datetime, timezone
    from alfred.memoria.perfil.carregador import DocumentoPerfil, Perfil
    from alfred.memoria.perfil.montador_prompt import montar_prompt_sistema

    def montar(agora):
        def documento(nome, corpo):
            return DocumentoPerfil(nome, 1, date(2026, 10, 15), corpo, "a" * 64)
        perfil = Perfil(
            fatores_estaveis=documento("fatores_estaveis", "DADO_FICTICIO"),
            conhecimento_abrangente=documento("conhecimento_abrangente", "CONHECIMENTO_FICTICIO"),
            preferencias=documento("preferencias", "PREFERENCIA_FICTICIA"),
        )
        return montar_prompt_sistema(perfil, agora)

    primeiro_horario = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    segundo_horario = datetime(2026, 10, 15, 12, 1, tzinfo=timezone.utc)
    class Provedor:
        def __init__(self): self.sistemas = []
        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            self.sistemas.append(sistema)
            yield EventoLLM(texto="Entendido.")

    async def executar():
        provedor_1, provedor_2 = Provedor(), Provedor()
        agente_1 = Agente(provedor_1, montar(primeiro_horario), modo_voz=True)
        agente_2 = Agente(provedor_2, montar(segundo_horario), modo_voz=True)
        assert agente_1.sistema == agente_2.sistema
        assert "Data e hora atuais:" not in agente_1.sistema
        _ = [fala async for fala in agente_1.responder("fala fictícia")]
        esperado = primeiro_horario.astimezone().isoformat(timespec="seconds")
        assert provedor_1.sistemas[0].endswith(f"Data e hora atuais: {esperado}")

    asyncio.run(executar())


def test_fim_de_fala_sem_hipotese_usa_limite_curto_e_conector_espera_mais():
    def criar_vad():
        vad = DetectorDeVoz(silencio_fim=14, silencio_fim_hesitacao=30)
        vad.probabilidade = lambda _frame: 0.9
        assert vad.processar(None)[0] == "inicio"
        vad.probabilidade = lambda _frame: 0.0
        return vad

    completa = criar_vad()
    for _ in range(13):
        evento, _ = completa.processar(None, texto_parcial="A sala está escura.")
        assert evento == "continuar"
    assert completa.processar(None, texto_parcial="A sala está escura.")[0] == "fim"

    hesitacao = criar_vad()
    for _ in range(29):
        assert hesitacao.processar(None, texto_parcial="E...")[0] == "continuar"
    assert hesitacao.processar(None, texto_parcial="E...")[0] == "fim"

    sem_parcial = criar_vad()
    for _ in range(13):
        assert sem_parcial.processar(None)[0] == "continuar"
    assert sem_parcial.processar(None)[0] == "fim"


def test_backchannel_curto_nao_interrompe_e_fala_sustentada_interrompe():
    vad = DetectorDeVoz(frames_minimos_interrupcao=14, limiar_interrupcao=0.85)
    vad.probabilidade = lambda _frame: 0.9
    for _ in range(13):
        assert vad.processar(None, durante_fala=True)[0] == "continuar"
    vad.probabilidade = lambda _frame: 0.1
    assert vad.processar(None, durante_fala=True)[0] == "continuar"
    vad.probabilidade = lambda _frame: 0.9
    for _ in range(13):
        assert vad.processar(None, durante_fala=True)[0] == "continuar"
    assert vad.processar(None, durante_fala=True)[0] == "interromper"


@pytest.mark.parametrize(("perfil", "beam"), [("rápido", 1), ("equilibrado", 5), ("preciso", 8)])
def test_perfis_stt_definem_decodificacao_local_sem_timestamps(monkeypatch, caplog, perfil, beam):
    chamadas = {}
    class ModeloFalso:
        def transcribe(self, audio, **kwargs):
            chamadas.update(kwargs)
            return [type("Segmento", (), {"text": " frase fictícia", "avg_logprob": -0.1})()], None

    transcritor = TranscritorLocal(perfil=perfil, vocabulario=("NomeFicticio",))
    transcritor._modelo = ModeloFalso()
    resultado = transcritor.transcrever([0.01] * 16000)

    assert resultado.texto == "frase fictícia"
    assert chamadas["language"] == "pt"
    assert chamadas["beam_size"] == beam
    assert chamadas["condition_on_previous_text"] is False
    assert chamadas["word_timestamps"] is False
    assert "português brasileiro" in chamadas["initial_prompt"]
    assert "Alfred" not in chamadas["initial_prompt"]
    assert chamadas["no_speech_threshold"] == 0.6
    assert chamadas["temperature"] == 0.0
    assert "NomeFicticio" in chamadas["hotwords"]
    assert "NomeFicticio" not in caplog.text


def test_transcritor_nao_envia_silencio_ao_whisper():
    chamadas = []
    class ModeloFalso:
        def transcribe(self, audio, **kwargs):
            chamadas.append(audio)
            return [], None

    transcritor = TranscritorLocal()
    transcritor._modelo = ModeloFalso()
    resultado = transcritor.transcrever([0.0] * 16000)
    assert resultado.texto == ""
    assert resultado.confianca == 0.0
    assert chamadas == []


def test_download_parakeet_retomado_usa_faixa_existente(tmp_path, monkeypatch):
    parcial = tmp_path / "modelo.part"
    parcial.write_bytes(b"abc")
    requisicoes = []

    class Resposta:
        status = 206
        headers = {"Content-Range": "bytes 3-5/6", "Content-Length": "3"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _tamanho):
            if hasattr(self, "lido"):
                return b""
            self.lido = True
            return b"def"

    def abrir(requisicao, timeout):
        requisicoes.append((requisicao.get_header("Range"), timeout))
        return Resposta()

    monkeypatch.setattr(modulo_stt.urllib.request, "urlopen", abrir)

    modulo_stt._baixar_com_retomada("https://exemplo.invalid/modelo", parcial)

    assert parcial.read_bytes() == b"abcdef"
    assert requisicoes == [("bytes=3-", 180)]


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Ah, é... liga a luz da sala, não, do quarto", "liga a luz do quarto"),
        ("hmm, tipo, toca toca música", "toca música"),
        ("liga a luz da sala", "liga a luz da sala"),
        ("É verdade, tipo, vou.", "É verdade, vou."),
    ],
)
def test_normaliza_hesitacao_repeticao_e_autocorrecao(entrada, esperado):
    assert normalizar_transcricao_pt_br(entrada) == esperado


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("São 15:45.", "São quinze horas e quarenta e cinco minutos."),
        ("Custa R$ 12,50 e tem 10% de desconto.", "Custa doze reais e cinquenta centavos e tem dez por cento de desconto."),
        ("A reunião é em 16/10/2026, às 15:00.", "A reunião é em dezesseis de outubro de dois mil e vinte e seis, às quinze horas."),
        ("A reunião é em 2026-10-16.", "A reunião é em dezesseis de outubro de dois mil e vinte e seis."),
        ("Acesse https://exemplo.com/a e ana@example.com.", "Acesse exemplo ponto com barra a e ana arroba example ponto com."),
        ("A API mede 2,5 kg.", "A a pê i mede dois vírgula cinco quilogramas."),
        ("Eu ia agora.", "Eu ia agora."),
        ("Ele ficou em 20º lugar.", "Ele ficou em vigésimo lugar."),
    ],
)
def test_normaliza_texto_para_fala(entrada, esperado):
    assert normalizar_texto_para_voz(entrada) == esperado


def test_divisor_de_oracoes_preserva_decimal_e_despacha_trechos_longos():
    texto = "A" * 45 + " 2,5 volts, " + "B" * 45 + "; " + "C" * 25 + "."
    partes = dividir_primeira_frase_em_oracoes(texto, minimo_caracteres=80)
    assert len(partes) == 3
    assert "2,5" in partes[0]
    assert dividir_primeira_frase_em_oracoes("Frase curta.") == ["Frase curta."]


def test_proxima_oracao_sintetiza_enquanto_audio_atual_toca():
    import time
    eventos = []
    class TTSFalso:
        def sintetizar(self, texto):
            eventos.append(("sintese_inicio", texto, time.perf_counter()))
            time.sleep(0.03)
            return texto, 16000
        def reproduzir(self, audio, taxa):
            eventos.append(("reproducao_inicio", audio, time.perf_counter()))
            time.sleep(0.10)
            eventos.append(("reproducao_fim", audio, time.perf_counter()))
        def parar(self): pass
    class SemUso: pass

    async def executar():
        from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz
        orquestrador = OrquestradorDeVoz(SemUso(), SemUso(), SemUso(), TTSFalso(), SemUso())
        fila = asyncio.Queue()
        await fila.put("primeira")
        await fila.put("segunda")
        await fila.put(None)
        await orquestrador._reproduzir_fila(fila)
        await fila.join()

    asyncio.run(executar())
    inicio_sintese = next(e[2] for e in eventos if e[0] == "sintese_inicio" and e[1] == "segunda")
    fim_primeiro = next(e[2] for e in eventos if e[0] == "reproducao_fim" and e[1] == "primeira")
    assert inicio_sintese < fim_primeiro
    assert [e[1] for e in eventos if e[0] == "sintese_inicio"] == ["primeira", "segunda"]


def test_fila_confirma_somente_frases_com_reproducao_concluida():
    class TTSComFalha:
        def sintetizar(self, texto):
            return texto, 16000
        def reproduzir(self, audio, taxa):
            if audio == "incompleta":
                raise RuntimeError("falha de reprodução")
        def parar(self): pass
    class SemUso: pass

    async def executar():
        from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz
        orquestrador = OrquestradorDeVoz(SemUso(), SemUso(), SemUso(), TTSComFalha(), SemUso())
        fila = asyncio.Queue()
        confirmadas = []
        await fila.put("incompleta")
        await fila.put("completa")
        await fila.put(None)
        await orquestrador._reproduzir_fila(fila, confirmadas)
        await fila.join()
        return confirmadas

    assert asyncio.run(executar()) == ["completa"]


@pytest.mark.parametrize(
    ("fala", "ferramenta"),
    [
        ("Que horas são?", "consultar_hora"),
        ("acende a luz da sala", "controlar_luz"),
        ("apaga a luz do quarto", "controlar_luz"),
        ("toca música por bossa nova", "tocar_musica"),
    ],
)
def test_roteador_rapido_reconhece_intencoes_exatas(fala, ferramenta):
    assert rotear_comando(fala).chamada.nome == ferramenta


@pytest.mark.parametrize("fala", ["para a música", "liga para Ana", "acende a luz da biblioteca"])
def test_roteador_rapido_nao_adivinha_acao_ou_argumento(fala):
    assert rotear_comando(fala) is None


def test_atalho_usa_ferramenta_registrada_e_descreve_simulacao():
    class LLMQueContaChamadas:
        def __init__(self): self.chamadas = 0
        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            self.chamadas += 1
            yield EventoLLM(texto="A resposta veio do modelo.")

    async def executar():
        provedor = LLMQueContaChamadas()
        agente = Agente(provedor, "regras fictícias", modo_voz=True)
        resposta_hora = [fala async for fala in agente.responder("que horas são")]
        resposta_luz = [fala async for fala in agente.responder("acende a luz da sala")]
        resposta_desconhecida = [fala async for fala in agente.responder("acende a luz da biblioteca")]
        assert resposta_hora[0].startswith("Agora são ")
        assert "simulação" in resposta_luz[0]
        assert resposta_desconhecida == ["A resposta veio do modelo."]
        assert provedor.chamadas == 1
    asyncio.run(executar())


def test_comando_de_voz_responde_sem_fala_de_espera():
    from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz

    class Captura: pass
    class VAD: pass
    class STT:
        def transcrever(self, _audio):
            return type("T", (), {"texto": "Crie um lembrete fictício para amanhã.", "confianca": 0.9})()
    class TTS:
        def __init__(self): self.tocadas = []
        def sintetizar(self, texto): return texto, 16000
        def reproduzir(self, audio, _taxa): self.tocadas.append(audio)
        def parar(self): pass
    class AgenteFalso:
        provedor = object()
        async def responder(self, texto, receber_confirmacao=None, ao_primeiro_token=None):
            yield "Resposta fictícia."

    async def executar():
        tts = TTS()
        orquestrador = OrquestradorDeVoz(
            Captura(), VAD(), STT(), tts, AgenteFalso(),
        )
        await orquestrador._processar([0.0], 1.0)
        assert tts.tocadas == ["Resposta fictícia."]
    asyncio.run(executar())


def test_wer_do_benchmark_sintetico_conta_substituicao():
    from scripts.medir_voz import wer
    assert wer("um dois três", "um quatro três") == pytest.approx(1 / 3)
    assert wer("um dois", "um dois") == 0


def test_resposta_do_modelo_nao_autoriza_acao_sensivel():
    class LLMQueTentaAutorizar:
        def __init__(self): self.rodadas = 0
        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            self.rodadas += 1
            if self.rodadas == 1:
                yield EventoLLM(texto="sim")
                yield EventoLLM(chamadas=(ChamadaFerramenta("ligar_para", {"contato": "Ana"}),))
            else:
                assert any(m.papel == "tool" and "cancelada" in m.conteudo for m in mensagens)
                yield EventoLLM(texto="Ação cancelada.")
    async def executar():
        agente = Agente(LLMQueTentaAutorizar(), "regras fictícias")
        saidas = [frase async for frase in agente.responder("Liga para Ana.")]
        assert any("Diga sim ou não" in frase for frase in saidas)
        assert any(m.papel == "tool" and "cancelada" in m.conteudo for m in agente.historico)
    asyncio.run(executar())


def test_historico_guarda_exatamente_n_interacoes():
    class LLMFalsoSemFerramentas:
        def conversar_com_ferramentas(self, mensagens, *, sistema, ferramentas):
            yield EventoLLM(texto="Anotado.")
    async def executar():
        agente = Agente(LLMFalsoSemFerramentas(), "regras", limite_interacoes=2)
        for turno in ("um", "dois", "três", "quatro"):
            _ = [frase async for frase in agente.responder(turno)]
        usuarios = [m.conteudo for m in agente.historico if m.papel == "user"]
        assert usuarios == ["três", "quatro"]
    asyncio.run(executar())


def test_log_registra_transcricao_e_resposta(tmp_path):
    from alfred.interfaces.ciclo_de_voz.orquestrador import OrquestradorDeVoz
    sentinela = "DADO-FICTICIO-PRIVADO"
    class Captura:
        pass
    class VAD:
        pass
    class STT:
        def transcrever(self, _):
            return type("T", (), {"texto": sentinela, "confianca": 0.9})()
    class TTS:
        def sintetizar(self, texto):
            return texto, 16000
        def reproduzir(self, *_):
            pass
        def parar(self):
            pass
    class AgenteFalso:
        provedor = object()
        async def responder(self, texto, receber_confirmacao=None, ao_primeiro_token=None):
            yield sentinela
    log_path = tmp_path / "voz.log"
    logger = logging.getLogger("alfred.voz")
    nivel_anterior = logger.level
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    logger.addHandler(handler)
    try:
        orq = OrquestradorDeVoz(Captura(), VAD(), STT(), TTS(), AgenteFalso())
        asyncio.run(orq._processar([0.0], 1.0))
        handler.flush()
        conteudo = log_path.read_text(encoding="utf-8")
        assert "frase_input=" in conteudo
        assert "frase_output=" in conteudo
        assert sentinela in conteudo
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(nivel_anterior)


def test_maquina_de_estados_cancela_tarefa_em_barge_in():
    from alfred.interfaces.ciclo_de_voz.orquestrador import EstadoVoz, OrquestradorDeVoz
    class Captura:
        dono = None
        async def frames(self):
            self.dono.estado = EstadoVoz.FALANDO
            yield object()
    class VAD:
        interrompeu = False
        def processar(self, frame, *, durante_fala=False):
            return ("interromper", frame) if durante_fala else ("continuar", None)
        def resetar(self):
            pass
        def registrar_interrupcao(self, frame):
            self.interrompeu = frame
    class TTS:
        def __init__(self): self.parou = False
        def parar(self): self.parou = True
    class AgenteFalso:
        provedor = object()
    async def executar():
        tts = TTS()
        captura = Captura()
        vad = VAD()
        orq = OrquestradorDeVoz(captura, vad, object(), tts, AgenteFalso())
        orq.ativar_manual()  # Simula pressionar espaço para interromper a fala.
        captura.dono = orq
        iniciou = asyncio.Event()
        async def tarefa_ativa():
            iniciou.set()
            await asyncio.Event().wait()
        orq._tarefa_turno = asyncio.create_task(tarefa_ativa())
        await iniciou.wait()
        await orq._ler_microfone()
        await asyncio.sleep(0)
        assert orq._tarefa_turno.cancelled()
        assert tts.parou
        assert orq.estado == EstadoVoz.OUVINDO
        assert vad.interrompeu is not False
        assert len(orq._frames_fala) == 1  # O primeiro bloco capturado fica preservado.
    asyncio.run(executar())
