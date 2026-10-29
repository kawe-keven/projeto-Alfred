from __future__ import annotations

import json
from io import BytesIO

import pytest

from alfred.adaptadores.llm import colibri
from alfred.adaptadores.llm.colibri import ProvedorColibri
from alfred.nucleo.provedor_llm import RespostaOllamaMalformada


def _linha(evento: object) -> bytes:
    return b"data: " + json.dumps(evento).encode("utf-8") + b"\n\n"


def test_colibri_rejeita_delta_com_tipo_invalido(monkeypatch) -> None:
    evento = {"choices": [{"delta": [], "finish_reason": None}]}
    resposta = BytesIO(_linha(evento) + b"data: [DONE]\n\n")
    monkeypatch.setattr(colibri, "urlopen", lambda *_args, **_kwargs: resposta)

    with pytest.raises(RespostaOllamaMalformada, match="evento de streaming inválido"):
        list(ProvedorColibri(modelo="teste").conversar([], sistema="regras"))
