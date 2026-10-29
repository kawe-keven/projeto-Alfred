import io
import json
from urllib.error import HTTPError

import pytest

from alfred.memoria.armazenamento import embeddings
from alfred.memoria.armazenamento.embeddings import (
    ErroGeracaoEmbeddings,
    GeradorEmbeddingsOllama,
    GeradorFalso,
)


class RespostaFalsa:
    def __init__(self, corpo):
        self.corpo = json.dumps(corpo).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.corpo


def test_ollama_envia_lotes_limitados_e_nao_usa_documents(monkeypatch):
    chamadas = []

    def urlopen_falso(requisicao, timeout):
        dados = json.loads(requisicao.data.decode("utf-8"))
        chamadas.append((requisicao, dados, timeout))
        return RespostaFalsa(
            {"embeddings": [[float(indice), 1.0] for indice, _ in enumerate(dados["input"])]}
        )

    monkeypatch.setattr(embeddings, "urlopen", urlopen_falso)
    gerador = GeradorEmbeddingsOllama(tamanho_lote=2, num_gpu=0)

    vetores = gerador.gerar_em_lote(
        ["texto fictício A", "texto fictício B", "texto fictício C"], "documento"
    )

    assert len(vetores) == 3
    assert len(chamadas) == 2
    assert [len(chamada[1]["input"]) for chamada in chamadas] == [2, 1]
    assert all(chamada[1]["model"] == "qwen3-embedding:0.6b" for chamada in chamadas)
    assert all(chamada[1]["options"]["num_gpu"] == 0 for chamada in chamadas)
    assert all(chamada[1]["keep_alive"] == "1m" for chamada in chamadas)
    assert all(chamada[0].full_url == "http://localhost:11434/api/embed" for chamada in chamadas)


def test_gerador_ollama_recusa_servidor_remoto():
    with pytest.raises(ValueError, match="localhost"):
        GeradorEmbeddingsOllama(url_base="http://servidor-remoto:11434")


def test_erro_http_nao_expoe_corpo_que_pode_conter_texto(monkeypatch):
    def urlopen_falso(*_, **__):
        raise HTTPError(
            "http://localhost:11434/api/embed",
            500,
            "erro",
            {},
            io.BytesIO(b"sentinela-ficticia-secreta"),
        )

    monkeypatch.setattr(embeddings, "urlopen", urlopen_falso)
    gerador = GeradorEmbeddingsOllama()

    with pytest.raises(ErroGeracaoEmbeddings) as erro:
        gerador.gerar_em_lote(["sentinela-ficticia-secreta"], "consulta")

    assert "sentinela-ficticia-secreta" not in str(erro.value)


def test_gerador_falso_e_deterministico_e_normalizado():
    gerador = GeradorFalso(dimensao=8)

    primeiro = gerador.gerar_em_lote(["frase fictícia"], "consulta")[0]
    segundo = gerador.gerar_em_lote(["frase fictícia"], "documento")[0]

    assert primeiro == segundo
    assert len(primeiro) == 8
    assert sum(valor * valor for valor in primeiro) == pytest.approx(1.0)
