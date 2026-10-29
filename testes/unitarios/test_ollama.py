import io
import json
import socket
from urllib.error import HTTPError, URLError

import pytest

from alfred.adaptadores.llm import ollama
from alfred.adaptadores.llm.ollama import ProvedorOllama
from alfred.nucleo.provedor_llm import (
    ErroConexaoOllama,
    Mensagem,
    ModeloOllamaNaoInstalado,
    RespostaOllamaMalformada,
    TempoEsgotadoOllama,
    ChamadaFerramenta,
    EventoLLM,
)


class FakeResposta:
    def __init__(self, linhas):
        self.linhas = iter(linhas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def readline(self):
        return next(self.linhas, b"")


def linha(evento):
    return (json.dumps(evento) + "\n").encode("utf-8")


def test_streaming_envia_sistema_e_historico_e_ignora_thinking(monkeypatch):
    capturado = {}

    def abrir(request, timeout):
        capturado["request"] = request
        capturado["timeout"] = timeout
        return FakeResposta(
            [
                linha({"message": {"thinking": "raciocinio privado", "content": "Olá "}, "done": False}),
                linha({"message": {"content": "mundo"}, "done": True}),
            ]
        )

    monkeypatch.setattr(ollama, "urlopen", abrir)
    provedor = ProvedorOllama(timeout=16)

    trechos = list(
        provedor.conversar([Mensagem("user", "oi")], sistema="regras fictícias")
    )

    payload = json.loads(capturado["request"].data.decode("utf-8"))
    assert trechos == ["Olá ", "mundo"]
    assert payload["messages"] == [
        {"role": "system", "content": "regras fictícias"},
        {"role": "user", "content": "oi"},
    ]
    assert payload["stream"] is True
    assert payload["think"] is False
    assert capturado["timeout"] == 16


def test_opcoes_de_voz_sao_enviadas_no_chat_e_nas_ferramentas(monkeypatch):
    capturados = []

    def abrir(request, timeout):
        capturados.append(json.loads(request.data.decode("utf-8")))
        return FakeResposta([linha({"message": {"content": "ok"}, "done": True} )])

    monkeypatch.setattr(ollama, "urlopen", abrir)
    provedor = ProvedorOllama(keep_alive="30m", num_ctx=8192, num_predict=144)
    list(provedor.conversar([Mensagem("user", "pergunta fictícia")], sistema="regras fictícias"))
    list(provedor.conversar_com_ferramentas([], sistema="regras fictícias", ferramentas=[]))

    assert len(capturados) == 2
    for payload in capturados:
        assert payload["keep_alive"] == "30m"
        assert payload["options"] == {"num_ctx": 8192, "num_predict": 144}
        assert payload["think"] is False


def test_aquecimento_usa_fala_ficticia_e_reserva_oito_tokens(monkeypatch):
    capturado = {}

    def abrir(request, timeout):
        capturado.update(json.loads(request.data.decode("utf-8")))
        return FakeResposta([linha({"message": {"content": "pronto"}, "done": True})])

    monkeypatch.setattr(ollama, "urlopen", abrir)
    ProvedorOllama(keep_alive="30m", num_predict=144).aquecer("regras fictícias")

    assert capturado["messages"][-1]["content"] == "Responda somente: pronto."
    assert capturado["options"]["num_predict"] == 8


def test_servidor_fora_do_ar_tem_erro_distinto(monkeypatch):
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(ConnectionRefusedError())))

    with pytest.raises(ErroConexaoOllama, match="Não foi possível conectar"):
        list(ProvedorOllama().conversar([], sistema=""))


def test_provedor_recusa_servidor_remoto():
    with pytest.raises(ValueError, match="própria máquina"):
        ProvedorOllama(url_base="http://servidor-remoto:11434")


def test_modelo_ausente_sugere_ollama_pull(monkeypatch):
    erro = HTTPError(
        "http://localhost:11434/api/chat",
        404,
        "Not Found",
        {},
        io.BytesIO(b'{"error":"model qwen3.5:9b not found, try pulling it first"}'),
    )
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(erro))

    with pytest.raises(ModeloOllamaNaoInstalado, match="ollama pull qwen3.5:9b"):
        list(ProvedorOllama().conversar([], sistema=""))


def test_resposta_malformada_tem_erro_distinto(monkeypatch):
    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda *_args, **_kwargs: FakeResposta(["isto não é JSON\n".encode("utf-8")]),
    )

    with pytest.raises(RespostaOllamaMalformada, match="trecho de resposta inválido"):
        list(ProvedorOllama().conversar([], sistema=""))


def test_fluxo_sem_evento_final_e_malformado(monkeypatch):
    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda *_args, **_kwargs: FakeResposta([linha({"message": {"content": "oi"}})]),
    )

    with pytest.raises(RespostaOllamaMalformada, match="antes de concluir"):
        list(ProvedorOllama().conversar([], sistema=""))


def test_timeout_tem_erro_distinto(monkeypatch):
    monkeypatch.setattr(
        ollama,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.timeout()),
    )

    with pytest.raises(TempoEsgotadoOllama, match="excedeu o limite"):
        list(ProvedorOllama(timeout=3).conversar([], sistema=""))


def test_chamadas_de_ferramenta_em_streaming_e_historico(monkeypatch):
    capturado = {}
    def abrir(request, timeout):
        capturado["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResposta([linha({"message": {"content": "", "tool_calls": [
            {"function": {"name": "consultar_hora", "arguments": {}}}
        ]}, "done": True})])
    monkeypatch.setattr(ollama, "urlopen", abrir)
    eventos = list(ProvedorOllama().conversar_com_ferramentas(
        [Mensagem("assistant", "", chamadas_ferramenta=(ChamadaFerramenta("consultar_hora", {}),)),
         Mensagem("tool", "12:00", "consultar_hora")],
        sistema="sistema", ferramentas=[]))
    assert eventos == [EventoLLM(chamadas=(ChamadaFerramenta("consultar_hora", {}),))]
    assert capturado["payload"]["messages"][-2:] == [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "consultar_hora", "arguments": {}}}]},
        {"role": "tool", "content": "12:00"},
    ]


def test_preserva_chamada_de_ferramenta_enviada_antes_do_evento_final(monkeypatch):
    chamada = {"function": {"name": "criar_arquivo", "arguments": {"nome": "nota.md", "conteudo": "texto"}}}
    eventos_stream = [
        linha({"message": {"content": "", "tool_calls": [chamada]}, "done": False}),
        linha({"message": {"content": ""}, "done": True, "done_reason": "stop"}),
    ]
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: FakeResposta(eventos_stream))

    eventos = list(ProvedorOllama().conversar_com_ferramentas(
        [Mensagem("user", "Crie uma nota")], sistema="sistema", ferramentas=[]
    ))

    assert eventos == [EventoLLM(chamadas=(ChamadaFerramenta(
        "criar_arquivo", {"nome": "nota.md", "conteudo": "texto"}
    ),))]
