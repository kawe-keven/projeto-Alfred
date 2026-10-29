from __future__ import annotations

import json
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from alfred.adaptadores.voz.tts_voicestudio import ErroVoiceStudio, SintetizadorVoiceStudio


class Vetor(list):
    @property
    def size(self):
        return len(self)

    def astype(self, _tipo):
        return self

    def __truediv__(self, escalar):
        return Vetor(valor / escalar for valor in self)


class NumpyFalso:
    float32 = float

    @staticmethod
    def frombuffer(dados, dtype=None):
        assert dtype == "<i2"
        return Vetor(item[0] for item in struct.iter_unpack("<h", dados))

    @staticmethod
    def arange(tamanho, dtype=None):
        assert dtype == "<i2"
        return Vetor(range(tamanho))

    @staticmethod
    def ones(tamanho, dtype=None):
        return Vetor([1.0] * tamanho)

    @staticmethod
    def zeros(tamanho, dtype=None):
        return Vetor([0.0] * tamanho)

    @staticmethod
    def concatenate(vetores):
        return Vetor(valor for vetor in vetores for valor in vetor)


@pytest.fixture(autouse=True)
def numpy_falso(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", NumpyFalso)


class ServidorFalso(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, responder=None):
        super().__init__(("127.0.0.1", 0), Manipulador)
        self.responder = responder
        self.primeiro_bloco = threading.Event()
        self.terminou = threading.Event()
        self.corpos = []

    def handle_error(self, _request, _client_address):
        pass


class Manipulador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/health":
            corpo = b'{"status":"ok","version":"0.5.6"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        self.send_error(404)

    def do_POST(self):
        tam = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(tam)
        self.server.corpos.append(corpo)
        responder = self.server.responder
        if responder:
            responder(self, corpo)
            return
        audio = struct.pack("<100h", *range(100))
        self.send_response(200)
        self.send_header("Content-Type", "audio/pcm")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        primeira = audio[:40]
        restante = audio[40:]
        self.wfile.write(f"{len(primeira):X}\r\n".encode() + primeira + b"\r\n")
        self.wfile.flush()
        self.server.primeiro_bloco.set()
        time.sleep(0.12)
        self.wfile.write(f"{len(restante):X}\r\n".encode() + restante + b"\r\n0\r\n\r\n")
        self.wfile.flush()
        self.server.terminou.set()


@pytest.fixture
def servidor_falso():
    servidor = ServidorFalso()
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        yield servidor
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=1)


def criar_sintetizador(servidor, **kwargs):
    base = f"http://127.0.0.1:{servidor.server_port}/v1"
    sintetizador = SintetizadorVoiceStudio(base, aquecer=False, **kwargs)
    sintetizador._preparado = True
    return sintetizador


class PiperFalso:
    def __init__(self, falhar=False):
        self.falhar = falhar
        self.carregamentos = 0
        self.textos = []
        self.reproducoes = []

    def carregar(self):
        self.carregamentos += 1
        if self.falhar:
            raise RuntimeError("falha sintética")

    def sintetizar(self, texto):
        import numpy as np
        self.textos.append(texto)
        return np.ones(12, dtype=np.float32), 22050

    def reproduzir(self, audio, taxa, *, ao_inicio=None):
        self.reproducoes.append((audio, taxa))
        if ao_inicio:
            ao_inicio(0.0)

    def parar(self):
        pass

    def fechar(self):
        pass


def test_stream_entrega_primeiro_bloco_antes_de_terminar(servidor_falso):
    sintetizador = criar_sintetizador(servidor_falso)
    blocos = iter(sintetizador._iterar_pcm("frase fictícia"))

    primeiro = next(blocos)

    assert primeiro
    assert servidor_falso.primeiro_bloco.wait(1)
    assert not servidor_falso.terminou.is_set()
    assert b"".join((primeiro, *blocos)) == struct.pack("<100h", *range(100))


def test_estilo_usa_campo_instructions_compativel_com_omnivoice(servidor_falso):
    sintetizador = criar_sintetizador(servidor_falso, estilo="estilo fictício")

    sintetizador._sintetizar_voice("frase sintética")

    corpo = json.loads(servidor_falso.corpos[0])
    assert corpo["instructions"] == "estilo fictício"
    assert "instruct" not in corpo


def test_repete_uma_vez_erro_http_transitorio(servidor_falso):
    chamadas = 0

    def responder(handler, _corpo):
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            handler.send_response(500)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        audio = struct.pack("<100h", *range(100))
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/pcm")
        handler.send_header("Content-Length", str(len(audio)))
        handler.end_headers()
        handler.wfile.write(audio)

    servidor_falso.responder = responder
    sintetizador = criar_sintetizador(servidor_falso)

    audio, taxa = sintetizador._sintetizar_voice("frase fictícia")

    assert len(audio) == 100
    assert taxa == 24000
    assert chamadas == 2
    sintetizador.fechar()


def test_mantem_fallback_na_sessao_apos_falha_do_voicestudio(
    servidor_falso, monkeypatch, capsys
):
    chamadas = 0

    def responder(handler, _corpo):
        nonlocal chamadas
        chamadas += 1
        if chamadas <= 2:
            handler.send_response(500)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        audio = struct.pack("<100h", *range(100))
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/pcm")
        handler.send_header("Content-Length", str(len(audio)))
        handler.end_headers()
        handler.wfile.write(audio)

    servidor_falso.responder = responder
    piper = PiperFalso()
    sintetizador = criar_sintetizador(
        servidor_falso, fallback="piper", sintetizador_fallback=piper
    )
    sintetizador._sd = SimpleNamespace()
    monkeypatch.setattr(
        sintetizador,
        "_abrir_saida",
        lambda: setattr(
            sintetizador,
            "_saida",
            SimpleNamespace(active=True, abort=lambda: None, close=lambda: None),
        ),
    )

    audio, taxa = sintetizador.sintetizar("frase fictícia de recuperação")
    assert sintetizador.fallback_ativo
    assert len(audio) == 12
    assert taxa == 22050

    audio, taxa = sintetizador.sintetizar("próxima frase fictícia")

    assert len(audio) == 12
    assert taxa == 22050
    assert sintetizador.fallback_ativo
    assert chamadas == 2
    assert piper.textos == ["frase fictícia de recuperação", "próxima frase fictícia"]
    sintetizador.fechar()


def test_frase_inteira_vai_para_fallback_se_stream_do_voicestudio_falha(
    servidor_falso, monkeypatch
):
    piper = PiperFalso()
    sintetizador = criar_sintetizador(
        servidor_falso, fallback="piper", sintetizador_fallback=piper
    )
    sintetizador._saida = SimpleNamespace(
        active=True, abort=lambda: None, close=lambda: None
    )

    def falhar_ao_iniciar_stream(_texto, **_kwargs):
        raise ErroVoiceStudio("Resposta malformada do VoiceStudio.")

    monkeypatch.setattr(sintetizador, "_iterar_pcm", falhar_ao_iniciar_stream)

    sintetizador.reproduzir_texto_stream("frase completa de teste")

    assert sintetizador.fallback_ativo
    assert piper.textos == ["frase completa de teste"]
    assert len(piper.reproducoes) == 1
    sintetizador.fechar()


def test_serializa_sinteses_concorrentes_no_mesmo_motor(servidor_falso):
    trava = threading.Lock()
    ativas = 0
    max_ativas = 0

    def responder(handler, _corpo):
        nonlocal ativas, max_ativas
        with trava:
            ativas += 1
            max_ativas = max(max_ativas, ativas)
        try:
            time.sleep(0.08)
            audio = struct.pack("<100h", *range(100))
            handler.send_response(200)
            handler.send_header("Content-Type", "audio/pcm")
            handler.send_header("Content-Length", str(len(audio)))
            handler.end_headers()
            handler.wfile.write(audio)
        finally:
            with trava:
                ativas -= 1

    servidor_falso.responder = responder
    sintetizador = criar_sintetizador(servidor_falso)
    barreira = threading.Barrier(3)
    falhas = []

    def sintetizar(texto):
        barreira.wait()
        try:
            sintetizador.sintetizar(texto)
        except Exception as erro:
            falhas.append(erro)

    threads = [
        threading.Thread(target=sintetizar, args=(f"frase fictícia {indice}",))
        for indice in range(2)
    ]
    for thread in threads:
        thread.start()
    barreira.wait()
    for thread in threads:
        thread.join(timeout=2)

    sintetizador.fechar()
    assert not any(thread.is_alive() for thread in threads)
    assert not falhas
    assert max_ativas == 1
    assert len(servidor_falso.corpos) == 2


@pytest.mark.parametrize(
    "url",
    ["http://example.com/v1", "http://192.168.1.20:3900/v1", "https://user@localhost/v1"],
)
def test_recusa_hosts_nao_loopback(url):
    with pytest.raises(ValueError, match="loopback"):
        SintetizadorVoiceStudio(url, aquecer=False)


def test_nao_segue_redirecionamento(servidor_falso):
    def redirecionar(handler, _corpo):
        handler.send_response(307)
        handler.send_header("Location", "http://example.com/audio")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    servidor_falso.responder = redirecionar
    sintetizador = criar_sintetizador(servidor_falso)

    with pytest.raises(ErroVoiceStudio, match="Redirecionamento.*recusado"):
        sintetizador._sintetizar_voice("frase fictícia")


def test_timeout_de_leitura_vira_erro_curto(servidor_falso):
    def atrasar(handler, _corpo):
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/pcm")
        handler.send_header("Content-Length", "4")
        handler.end_headers()
        handler.wfile.flush()
        time.sleep(0.15)
        try:
            handler.wfile.write(b"\0\0\0\0")
        except OSError:
            pass

    servidor_falso.responder = atrasar
    sintetizador = criar_sintetizador(servidor_falso, timeout_leitura_s=0.04)

    with pytest.raises(ErroVoiceStudio, match="tempo esgotado"):
        sintetizador._sintetizar_voice("frase fictícia")


def test_servidor_offline_nao_troca_de_motor_e_avisa_uma_vez(monkeypatch, capsys):
    sintetizador = SintetizadorVoiceStudio(
        "http://127.0.0.1:1/v1", aquecer=False
    )
    sintetizador._preparado = True
    sintetizador._sd = SimpleNamespace()

    with pytest.raises(ErroVoiceStudio):
        sintetizador.sintetizar("uma frase fictícia")
    with pytest.raises(ErroVoiceStudio):
        sintetizador.sintetizar("outra frase fictícia")

    assert capsys.readouterr().out.count("VoiceStudio indisponível") == 1
    assert sintetizador.fallback_ativo


def test_nao_permite_motor_de_voz_alternativo():
    with pytest.raises(ValueError, match="requer um sintetizador configurado"):
        SintetizadorVoiceStudio("http://127.0.0.1:3900/v1", fallback="piper", aquecer=False)


def test_voz_ou_motor_inexistente_tem_mensagem_sem_corpo(servidor_falso):
    sentinela = "PESSOA_SECRETA_FICTICIA"

    def erro(handler, corpo):
        assert sentinela.encode() in corpo
        detalhe = json.dumps({"error": {"message": sentinela, "code": "invalid_voice"}}).encode()
        handler.send_response(400)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(detalhe)))
        handler.end_headers()
        handler.wfile.write(detalhe)

    servidor_falso.responder = erro
    sintetizador = criar_sintetizador(servidor_falso, fallback="texto")

    with pytest.raises(ErroVoiceStudio, match="Motor ou voz") as capturado:
        sintetizador._sintetizar_voice(sentinela)
    assert sentinela not in str(capturado.value)


def test_licenca_pendente_do_modelo_tem_erro_claro_sem_expor_detalhes(servidor_falso):
    def erro(handler, _corpo):
        detalhe = json.dumps({
            "detail": {
                "code": "model_licence_required",
                "message": "Aceite a licença de um modelo fictício.",
                "models": [{"repo_id": "modelo-ficticio"}],
            }
        }).encode()
        handler.send_response(403)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(detalhe)))
        handler.end_headers()
        handler.wfile.write(detalhe)

    servidor_falso.responder = erro
    sintetizador = criar_sintetizador(servidor_falso, fallback="texto")

    with pytest.raises(ErroVoiceStudio, match="licença do modelo.*VoiceStudio") as capturado:
        list(sintetizador._iterar_pcm("frase fictícia"))
    assert "modelo-ficticio" not in str(capturado.value)


def test_texto_e_instructions_nao_vazam_para_logs_ou_erros(servidor_falso, caplog):
    sentinela_texto = "SENTINELA_TEXTO_FICTICIO_82A1"
    sentinela_instructions = "SENTINELA_ESTILO_FICTICIO_91B2"

    def erro(handler, corpo):
        pedido = json.loads(corpo)
        assert sentinela_texto in pedido["input"]
        assert pedido["instructions"] == sentinela_instructions
        detalhe = json.dumps(
            {
                "error": {
                    "message": f"{sentinela_texto} {sentinela_instructions}",
                    "code": "synthetic_failure",
                }
            }
        ).encode()
        handler.send_response(400)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(detalhe)))
        handler.end_headers()
        handler.wfile.write(detalhe)

    servidor_falso.responder = erro
    sintetizador = criar_sintetizador(
        servidor_falso, estilo=sentinela_instructions
    )

    with pytest.raises(ErroVoiceStudio) as capturado:
        sintetizador._sintetizar_voice(sentinela_texto)

    saidas = str(capturado.value) + caplog.text
    assert sentinela_texto not in saidas
    assert sentinela_instructions not in saidas


def test_resposta_malformada_e_rotas_ausentes_sao_claras(servidor_falso):
    sintetizador = criar_sintetizador(servidor_falso, fallback="texto")
    servidor_falso.responder = lambda handler, _body: (
        handler.send_response(200),
        handler.send_header("Content-Type", "application/json"),
        handler.send_header("Content-Length", "2"),
        handler.end_headers(),
        handler.wfile.write(b"{}"),
    )
    with pytest.raises(ErroVoiceStudio, match="Resposta malformada"):
        sintetizador._sintetizar_voice("texto fictício")

    servidor_falso.responder = None
    assert str(SintetizadorVoiceStudio._erro_status(404)) == "Rota do VoiceStudio ausente ou alterada."


def test_verifica_versao_e_aquece_cache_sem_audio_dispositivo(servidor_falso, monkeypatch):
    class StreamFalso:
        active = False
        latency = 0.01

        def __init__(self, **_kwargs):
            self.escrito = []

        def start(self):
            self.active = True

        def write(self, bloco):
            self.escrito.append(bloco)

        def abort(self):
            self.active = False

        def close(self):
            self.active = False

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=StreamFalso))
    sintetizador = SintetizadorVoiceStudio(
        f"http://127.0.0.1:{servidor_falso.server_port}/v1", aquecer=True,
    )
    sintetizador.carregar()

    assert sintetizador.versao == "0.5.6"
    assert set(sintetizador._cache) == {"entendido."}
    assert len(servidor_falso.corpos) == 1
    sintetizador.fechar()


def test_cancelamento_fecha_conexao_ativa(servidor_falso):
    iniciou = threading.Event()

    def aguardar(handler, _corpo):
        handler.send_response(200)
        handler.send_header("Content-Type", "audio/pcm")
        handler.send_header("Content-Length", "4")
        handler.end_headers()
        handler.wfile.flush()
        iniciou.set()
        time.sleep(0.3)
        try:
            handler.wfile.write(b"\0\0\0\0")
        except OSError:
            pass

    servidor_falso.responder = aguardar
    sintetizador = criar_sintetizador(servidor_falso)
    falhas = []

    def requisitar():
        try:
            sintetizador._sintetizar_voice("frase fictícia")
        except Exception as erro:
            falhas.append(erro)

    thread = threading.Thread(target=requisitar)
    thread.start()
    assert iniciou.wait(1)
    limite = time.monotonic() + 1
    while not sintetizador._conexoes and time.monotonic() < limite:
        time.sleep(0.005)
    conexao = next(iter(sintetizador._conexoes))
    sintetizador.parar()
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert conexao.sock is None
