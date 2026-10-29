"""Cliente local compatível com a API OpenAI servida pelo Colibri."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from alfred.nucleo.provedor_llm import (
    ChamadaFerramenta,
    ErroConexaoOllama,
    EventoLLM,
    Mensagem,
    RespostaOllamaMalformada,
    TempoEsgotadoOllama,
)


class ProvedorColibri:
    """Adapta streaming OpenAI/SSE do Colibri ao contrato interno do Alfred."""

    def __init__(
        self,
        modelo: str,
        url_base: str = "http://127.0.0.1:8000/v1",
        timeout: float = 120.0,
        max_tokens: int = 96,
        temperatura: float = 0.8,
    ) -> None:
        endereco = urlparse(url_base)
        if endereco.scheme != "http" or endereco.hostname not in {
            "localhost", "127.0.0.1", "::1"
        }:
            raise ValueError("O Colibri deve usar um servidor na própria máquina")
        if not modelo.strip() or timeout <= 0 or max_tokens < 1:
            raise ValueError("Modelo, timeout e limite de tokens do Colibri devem ser válidos")
        if not 0 <= temperatura <= 2:
            raise ValueError("A temperatura deve ficar entre zero e dois")
        self.modelo = modelo
        self.url_base = url_base.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperatura = temperatura
        self._resposta_ativa = None

    def cancelar(self) -> None:
        resposta = self._resposta_ativa
        if resposta is not None:
            try:
                resposta.close()
            except OSError:
                pass

    def aquecer(self, sistema: str = "") -> None:
        list(self.conversar([Mensagem("user", "Responda somente: pronto.")], sistema=sistema))

    def conversar(self, mensagens: Sequence[Mensagem], *, sistema: str) -> Iterator[str]:
        for evento in self._stream(mensagens, sistema=sistema, ferramentas=None):
            if evento.texto:
                yield evento.texto

    def conversar_com_ferramentas(
        self, mensagens: Sequence[Mensagem], *, sistema: str, ferramentas: list[dict]
    ) -> Iterator[EventoLLM]:
        yield from self._stream(mensagens, sistema=sistema, ferramentas=ferramentas)

    def _stream(
        self,
        mensagens: Sequence[Mensagem],
        *,
        sistema: str,
        ferramentas: list[dict] | None,
    ) -> Iterator[EventoLLM]:
        corpo = {
            "model": self.modelo,
            "messages": _mensagens_openai(mensagens, sistema),
            "stream": True,
            "max_tokens": self.max_tokens,
            "temperature": self.temperatura,
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        requisicao = Request(
            f"{self.url_base}/chat/completions",
            data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        chamadas: dict[int, dict[str, str]] = {}
        finalizado = False
        try:
            with urlopen(requisicao, timeout=self.timeout) as resposta:
                self._resposta_ativa = resposta
                for linha in resposta:
                    if not linha.startswith(b"data:"):
                        continue
                    dados = linha[5:].strip()
                    if dados == b"[DONE]":
                        finalizado = True
                        break
                    try:
                        evento = json.loads(dados.decode("utf-8"))
                        escolhas = evento["choices"]
                        escolha = escolhas[0]
                        delta = escolha["delta"]
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
                        raise RespostaOllamaMalformada(
                            "Colibri retornou um evento de streaming inválido"
                        ) from None
                    if not isinstance(evento, dict) or not isinstance(escolhas, list):
                        raise RespostaOllamaMalformada(
                            "Colibri retornou um evento de streaming inválido"
                        )
                    if not isinstance(escolha, dict) or not isinstance(delta, dict):
                        raise RespostaOllamaMalformada(
                            "Colibri retornou um evento de streaming inválido"
                        )
                    texto = delta.get("content") or ""
                    if not isinstance(texto, str):
                        raise RespostaOllamaMalformada(
                            "Colibri retornou conteúdo de streaming inválido"
                        )
                    if texto:
                        yield EventoLLM(texto=texto)
                    chamadas_delta = delta.get("tool_calls", [])
                    if not isinstance(chamadas_delta, list):
                        raise RespostaOllamaMalformada(
                            "Colibri retornou chamadas de ferramenta inválidas"
                        )
                    for chamada in chamadas_delta:
                        if not isinstance(chamada, dict):
                            raise RespostaOllamaMalformada(
                                "Colibri retornou chamadas de ferramenta inválidas"
                            )
                        indice = chamada.get("index", 0)
                        funcao = chamada.get("function") or {}
                        if not isinstance(funcao, dict):
                            raise RespostaOllamaMalformada(
                                "Colibri retornou chamadas de ferramenta inválidas"
                            )
                        identificador = chamada.get("id", "")
                        nome = funcao.get("name", "")
                        argumentos = funcao.get("arguments", "")
                        if (
                            isinstance(indice, bool)
                            or not isinstance(indice, int)
                            or indice < 0
                            or not isinstance(identificador, str)
                            or not isinstance(nome, str)
                            or not isinstance(argumentos, str)
                        ):
                            raise RespostaOllamaMalformada(
                                "Colibri retornou chamadas de ferramenta inválidas"
                            )
                        item = chamadas.setdefault(indice, {"id": "", "name": "", "arguments": ""})
                        item["id"] += identificador
                        item["name"] += nome
                        item["arguments"] += argumentos
                    if escolha.get("finish_reason") is not None:
                        finalizado = True
                self._resposta_ativa = None
        except HTTPError as erro:
            erro.read(4096)
            raise ErroConexaoOllama(f"Colibri respondeu com HTTP {erro.code}") from None
        except (TimeoutError, socket.timeout):
            raise TempoEsgotadoOllama("Colibri excedeu o tempo limite configurado") from None
        except URLError:
            raise ErroConexaoOllama(f"Não foi possível conectar ao Colibri em {self.url_base}") from None
        except OSError:
            raise ErroConexaoOllama("Não foi possível conectar ao Colibri local") from None
        finally:
            self._resposta_ativa = None
        if not finalizado:
            raise RespostaOllamaMalformada("Colibri encerrou o fluxo antes de concluir")
        if chamadas:
            resultado = []
            for chamada in chamadas.values():
                try:
                    argumentos = json.loads(chamada["arguments"] or "{}")
                except json.JSONDecodeError:
                    raise RespostaOllamaMalformada(
                        "Colibri retornou argumentos de ferramenta inválidos"
                    ) from None
                resultado.append(ChamadaFerramenta(chamada["name"], argumentos))
            yield EventoLLM(chamadas=tuple(resultado))


def _mensagens_openai(mensagens: Sequence[Mensagem], sistema: str) -> list[dict]:
    resultado = [{"role": "system", "content": sistema}]
    ids_pendentes: dict[str, list[str]] = {}
    for indice, mensagem in enumerate(mensagens):
        if mensagem.chamadas_ferramenta:
            chamadas = []
            for subindice, chamada in enumerate(mensagem.chamadas_ferramenta):
                chamada_id = f"alfred_{indice}_{subindice}"
                ids_pendentes.setdefault(chamada.nome, []).append(chamada_id)
                chamadas.append({
                    "id": chamada_id,
                    "type": "function",
                    "function": {
                        "name": chamada.nome,
                        "arguments": json.dumps(chamada.argumentos, ensure_ascii=False),
                    },
                })
            resultado.append({"role": "assistant", "content": mensagem.conteudo or None,
                              "tool_calls": chamadas})
        elif mensagem.papel == "tool":
            fila = ids_pendentes.get(mensagem.nome_ferramenta or "", [])
            resultado.append({
                "role": "tool",
                "tool_call_id": fila.pop(0) if fila else f"alfred_{indice}_0",
                "name": mensagem.nome_ferramenta or "tool",
                "content": mensagem.conteudo,
            })
        else:
            resultado.append({"role": mensagem.papel, "content": mensagem.conteudo})
    return resultado
