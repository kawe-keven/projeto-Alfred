"""Provedor de conversa em streaming para a API local do Ollama."""

from __future__ import annotations

import json
import re
import socket
from collections.abc import Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from alfred.nucleo.provedor_llm import (
    ErroConexaoOllama,
    Mensagem,
    ModeloOllamaNaoInstalado,
    RespostaOllamaMalformada,
    TempoEsgotadoOllama,
    EventoLLM,
    ChamadaFerramenta,
)


class ProvedorOllama:
    def __init__(
        self,
        modelo: str = "qwen3.5:9b",
        url_base: str = "http://localhost:11434",
        timeout: float = 120.0,
        keep_alive: str | None = None,
        num_ctx: int | None = None,
        num_predict: int | None = None,
        temperatura: float | None = None,
    ) -> None:
        if not modelo.strip():
            raise ValueError("O nome do modelo Ollama não pode ficar vazio")
        if timeout <= 0:
            raise ValueError("O timeout deve ser maior que zero")
        endereco = urlparse(url_base)
        if endereco.scheme != "http" or endereco.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("O Ollama deve usar um servidor na própria máquina")
        self.modelo = modelo
        self.url_base = url_base.rstrip("/")
        self.timeout = timeout
        if keep_alive is not None and not keep_alive.strip():
            raise ValueError("O tempo de retenção do modelo não pode ficar vazio")
        if num_ctx is not None and num_ctx < 1:
            raise ValueError("num_ctx deve ser maior que zero")
        if num_predict is not None and num_predict < 1:
            raise ValueError("num_predict deve ser maior que zero")
        if temperatura is not None and not 0 <= temperatura <= 2:
            raise ValueError("A temperatura deve ficar entre zero e dois")
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.temperatura = temperatura
        self._resposta_ativa = None

    def aquecer(self, sistema: str) -> None:
        """Carrega o modelo com um pedido mínimo, sem pré-processar o prompt de voz."""
        list(self.conversar(
            [Mensagem("user", "Responda somente: pronto.")],
            sistema="",
            # Um token podia cortar a resposta e acionar continuações sucessivas.
            _num_predict=8,
        ))

    def cancelar(self) -> None:
        resposta = self._resposta_ativa
        if resposta is not None:
            try:
                resposta.close()
            except OSError:
                pass

    def conversar(self, mensagens: Sequence[Mensagem], *, sistema: str,
                  _num_predict: int | None = None) -> Iterator[str]:
        opcoes = self._opcoes(_num_predict)
        corpo = json.dumps(
            {
                "model": self.modelo,
                "messages": [
                    {"role": "system", "content": sistema},
                    *(
                    _mensagem_ollama(mensagem)
                        for mensagem in mensagens
                    ),
                ],
                "stream": True,
                "think": False,
                **({"keep_alive": self.keep_alive} if self.keep_alive is not None else {}),
                **({"options": opcoes} if opcoes else {}),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        requisicao = Request(
            f"{self.url_base}/api/chat",
            data=corpo,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        recebido_final = False
        motivo_final = None
        texto_parcial = ""
        try:
            with urlopen(requisicao, timeout=self.timeout) as resposta:
                while True:
                    linha = resposta.readline()
                    if not linha:
                        break
                    if not linha.strip():
                        continue
                    try:
                        evento = json.loads(linha.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise RespostaOllamaMalformada(
                            "Ollama retornou um trecho de resposta inválido"
                        ) from None
                    if not isinstance(evento, dict):
                        raise RespostaOllamaMalformada(
                            "Ollama retornou um trecho de resposta inválido"
                        )
                    if "error" in evento:
                        if _indica_modelo_ausente(evento.get("error")):
                            raise _erro_modelo_ausente(self.modelo) from None
                        raise RespostaOllamaMalformada(
                            "Ollama informou uma falha ao gerar a resposta"
                        )

                    mensagem = evento.get("message", {})
                    if not isinstance(mensagem, dict):
                        raise RespostaOllamaMalformada(
                            "Ollama retornou uma mensagem em formato inválido"
                        )
                    conteudo = mensagem.get("content", "")
                    if not isinstance(conteudo, str):
                        raise RespostaOllamaMalformada(
                            "Ollama retornou conteúdo em formato inválido"
                        )
                    # O campo separado `thinking` (raciocínio interno) é deliberadamente ignorado.
                    if conteudo:
                        texto_parcial += conteudo
                        yield conteudo
                    if evento.get("done") is True:
                        recebido_final = True
                        motivo_final = evento.get("done_reason")
                        break
        except HTTPError as erro:
            corpo_erro = erro.read(16_384).decode("utf-8", errors="ignore")
            if _indica_modelo_ausente(corpo_erro):
                raise _erro_modelo_ausente(self.modelo) from None
            raise ErroConexaoOllama(
                f"Ollama respondeu com HTTP {erro.code}"
            ) from None
        except (TimeoutError, socket.timeout):
            raise TempoEsgotadoOllama(
                f"O Ollama excedeu o limite de {self.timeout:g} segundos"
            ) from None
        except URLError as erro:
            if isinstance(erro.reason, (TimeoutError, socket.timeout)):
                raise TempoEsgotadoOllama(
                    f"O Ollama excedeu o limite de {self.timeout:g} segundos"
                ) from None
            raise ErroConexaoOllama(
                f"Não foi possível conectar ao Ollama em {self.url_base}"
            ) from None
        except OSError:
            raise ErroConexaoOllama(
                f"Não foi possível conectar ao Ollama em {self.url_base}"
            ) from None

        if not recebido_final:
            raise RespostaOllamaMalformada(
                "Ollama encerrou o fluxo antes de concluir a resposta"
            )
        if motivo_final in {"length", "max_tokens"} or _resposta_parece_cortada(texto_parcial):
            # Continua quando o servidor atingiu o limite de geração ou encerrou
            # claramente no meio de uma resposta; o trecho já transmitido é preservado.
            mensagens_continuacao = [
                *mensagens,
                Mensagem("assistant", texto_parcial),
                Mensagem(
                    "user",
                    "A resposta anterior terminou antes de concluir o raciocínio. "
                    "Continue exatamente de onde parou, sem repetir o que já foi dito, "
                    "e conclua de forma breve e completa.",
                ),
            ]
            yield from self.conversar(mensagens_continuacao, sistema=sistema,
                                      _num_predict=_num_predict)

    def _opcoes(self, num_predict: int | None = None) -> dict[str, int | float]:
        opcoes: dict[str, int | float] = {}
        if self.temperatura is not None:
            opcoes["temperature"] = self.temperatura
        if self.num_ctx is not None:
            opcoes["num_ctx"] = self.num_ctx
        limite = self.num_predict if num_predict is None else num_predict
        if limite is not None:
            opcoes["num_predict"] = limite
        return opcoes

    def responder(self, mensagem: str) -> str:
        """Compatibilidade com o cliente síncrono anterior."""
        return "".join(
            self.conversar([Mensagem("user", mensagem)], sistema="")
        )

    def conversar_com_ferramentas(self, mensagens: Sequence[Mensagem], *, sistema: str, ferramentas: list[dict], _continuacoes: int = 0) -> Iterator[EventoLLM]:
        """Streaming local do Ollama, incluindo chamadas finais do protocolo tools."""
        opcoes = self._opcoes()
        corpo = json.dumps({
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema}, *(
                _mensagem_ollama(m) for m in mensagens
            )],
            "tools": ferramentas,
            "stream": True,
            "think": False,
            **({"keep_alive": self.keep_alive} if self.keep_alive is not None else {}),
            **({"options": opcoes} if opcoes else {}),
        }, ensure_ascii=False).encode("utf-8")
        req = Request(f"{self.url_base}/api/chat", data=corpo,
                      headers={"Content-Type": "application/json"}, method="POST")
        finalizado = False
        motivo_final = None
        texto_parcial = ""
        tem_chamadas = False
        chamadas_ferramenta: list[ChamadaFerramenta] = []
        try:
            with urlopen(req, timeout=self.timeout) as resposta:
                self._resposta_ativa = resposta
                while linha := resposta.readline():
                    if not linha.strip():
                        continue
                    try:
                        evento = json.loads(linha.decode("utf-8"))
                        if isinstance(evento, dict) and "error" in evento:
                            if _indica_modelo_ausente(evento.get("error")):
                                raise _erro_modelo_ausente(self.modelo)
                            raise RespostaOllamaMalformada("Ollama informou uma falha ao gerar a resposta")
                        if not isinstance(evento, dict):
                            raise ValueError
                        mensagem = evento["message"]
                        if not isinstance(mensagem, dict):
                            raise ValueError
                    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                        raise RespostaOllamaMalformada("Ollama retornou um evento inválido") from None
                    texto = mensagem.get("content", "")
                    if not isinstance(texto, str):
                        raise RespostaOllamaMalformada("Ollama retornou conteúdo em formato inválido")
                    if texto:
                        texto_parcial += texto
                        yield EventoLLM(texto=texto)
                    lista_chamadas = mensagem.get("tool_calls", [])
                    if not isinstance(lista_chamadas, list):
                        raise RespostaOllamaMalformada("Ollama retornou chamadas de ferramenta inválidas")
                    if lista_chamadas:
                        chamadas_atualizadas = []
                        for chamada in lista_chamadas:
                            if not isinstance(chamada, dict) or not isinstance(chamada.get("function"), dict):
                                raise RespostaOllamaMalformada("Ollama retornou uma chamada de ferramenta inválida")
                            funcao = chamada["function"]
                            nome = funcao.get("name", "")
                            argumentos = funcao.get("arguments")
                            if isinstance(argumentos, str):
                                try:
                                    argumentos = json.loads(argumentos)
                                except json.JSONDecodeError:
                                    argumentos = None
                            chamadas_atualizadas.append(
                                ChamadaFerramenta(nome if isinstance(nome, str) else "", argumentos)
                            )
                        # Algumas versões do Ollama emitem a chamada com done=false
                        # e terminam o stream num evento separado sem tool_calls.
                        chamadas_ferramenta = chamadas_atualizadas
                    if evento.get("done"):
                        finalizado = True
                        motivo_final = evento.get("done_reason")
                        break
                self._resposta_ativa = None
        except HTTPError as erro:
            detalhe = erro.read(16384).decode("utf-8", errors="ignore")
            if _indica_modelo_ausente(detalhe):
                raise _erro_modelo_ausente(self.modelo) from None
            raise ErroConexaoOllama(f"Ollama respondeu com HTTP {erro.code}") from None
        except (TimeoutError, socket.timeout):
            raise TempoEsgotadoOllama("O Ollama excedeu o tempo limite") from None
        except URLError:
            raise ErroConexaoOllama("Não foi possível conectar ao Ollama local") from None
        except OSError:
            raise ErroConexaoOllama("Não foi possível conectar ao Ollama local") from None
        finally:
            self._resposta_ativa = None
        if not finalizado:
            raise RespostaOllamaMalformada("Ollama encerrou antes de concluir")
        if chamadas_ferramenta:
            tem_chamadas = True
            yield EventoLLM(chamadas=tuple(chamadas_ferramenta))
        if (not tem_chamadas and _continuacoes < 2
                and (motivo_final in {"length", "max_tokens"}
                     or _resposta_parece_cortada(texto_parcial))):
            # O fluxo com ferramentas também precisa concluir respostas que o
            # Ollama interrompeu no limite de geração.
            mensagens_continuacao = [
                *mensagens,
                Mensagem("assistant", texto_parcial),
                Mensagem(
                    "user",
                    "A resposta anterior terminou antes de concluir. Continue exatamente "
                    "de onde parou, sem repetir o que já foi dito, e conclua de forma breve.",
                ),
            ]
            yield from self.conversar_com_ferramentas(
                mensagens_continuacao,
                sistema=sistema,
                ferramentas=ferramentas,
                _continuacoes=_continuacoes + 1,
            )


# Nome preservado para código que ainda importe o cliente da primeira versão.
ClienteOllama = ProvedorOllama


def _mensagem_ollama(mensagem: Mensagem) -> dict:
    resultado = {"role": mensagem.papel, "content": mensagem.conteudo}
    if mensagem.chamadas_ferramenta:
        resultado["tool_calls"] = [{"function": {"name": chamada.nome, "arguments": chamada.argumentos}}
                                   for chamada in mensagem.chamadas_ferramenta]
    return resultado


def _resposta_parece_cortada(texto: str) -> bool:
    """Identifica finais claramente incompletos sem impor tamanho à resposta."""
    final = texto.rstrip()
    if not final:
        return False
    if re.search(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s*$", final):
        return True
    terminou_com_pontuacao = final[-1] in ".!?…:;”’\")]}"
    return not terminou_com_pontuacao and len(final.split()) >= 8


def _indica_modelo_ausente(detalhe: object) -> bool:
    if not isinstance(detalhe, str):
        return False
    texto = detalhe.lower()
    return "model" in texto and any(
        termo in texto for termo in ("not found", "does not exist", "pull")
    )


def _erro_modelo_ausente(modelo: str) -> ModeloOllamaNaoInstalado:
    return ModeloOllamaNaoInstalado(
        f"Modelo '{modelo}' não instalado. Execute: ollama pull {modelo}"
    )
