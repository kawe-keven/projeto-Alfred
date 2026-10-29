from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from alfred.interfaces.web import app as painel_web


def _aguardar_pergunta(painel, pergunta: str, timeout: float = 1.0) -> bool:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        with painel.confirmacao_lock:
            atual = (painel.confirmacao or {}).get("question")
        if atual == pergunta:
            return True
        time.sleep(0.005)
    return False


def test_confirmacoes_concorrentes_nao_trocam_a_acao_pendente(monkeypatch) -> None:
    evento_real = threading.Event

    class EventoComEsperaCurta:
        def __init__(self) -> None:
            self._evento = evento_real()

        def set(self) -> None:
            self._evento.set()

        def wait(self, timeout: float | None = None) -> bool:
            limite = 0.1 if timeout is None else min(timeout, 0.1)
            return self._evento.wait(limite)

    monkeypatch.setattr(
        painel_web,
        "threading",
        SimpleNamespace(Event=EventoComEsperaCurta, Lock=threading.Lock),
    )
    painel = painel_web.PainelAlfred()
    segunda_iniciada = evento_real()

    def solicitar_segunda() -> str:
        segunda_iniciada.set()
        return painel.solicitar_confirmacao("Aprovar exclusão?")

    resultados: dict[str, str] = {}
    primeira = threading.Thread(
        target=lambda: resultados.setdefault(
            "primeira", painel.solicitar_confirmacao("Enviar e-mail?")
        )
    )
    segunda = threading.Thread(
        target=lambda: resultados.setdefault("segunda", solicitar_segunda())
    )
    primeira.start()
    assert _aguardar_pergunta(painel, "Enviar e-mail?")
    segunda.start()
    assert segunda_iniciada.wait(1)
    try:
        time.sleep(0.05)
        with painel.confirmacao_lock:
            pergunta = (painel.confirmacao or {}).get("question")
        assert pergunta == "Enviar e-mail?"

        assert painel.responder_confirmacao("sim")
        primeira.join(1)
        assert not primeira.is_alive()
        assert resultados["primeira"] == "sim"

        assert _aguardar_pergunta(painel, "Aprovar exclusão?")
        assert painel.responder_confirmacao("sim")
        segunda.join(1)
        assert not segunda.is_alive()
        assert resultados["segunda"] == "sim"
    finally:
        painel.responder_confirmacao("não")
        primeira.join(1)
        segunda.join(1)


def test_corpo_http_rejeita_content_length_negativo_sem_ler_stream() -> None:
    from types import SimpleNamespace

    from alfred.interfaces.web.app import Requisicao

    class StreamNaoLegivel:
        def read(self, _tamanho: int) -> bytes:
            raise AssertionError("corpos inválidos não devem ser lidos")

    requisicao = SimpleNamespace(
        headers={"Content-Length": "-1"},
        rfile=StreamNaoLegivel(),
    )
    try:
        Requisicao.ler_json(requisicao)
    except ValueError:
        return
    raise AssertionError("Content-Length negativo precisa ser rejeitado")
