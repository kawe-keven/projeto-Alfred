"""Confirmação de ações sensíveis dirigida exclusivamente por código."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from alfred.ferramentas.registro import Ferramenta, RegistroDeFerramentas


@dataclass(frozen=True)
class AcaoPendente:
    ferramenta: Ferramenta
    argumentos: dict[str, str]
    versao_perfil: int | None = None


def interpretar_confirmacao(texto: str) -> bool | None:
    normalizado = " ".join(texto.casefold().strip(" .,!?").split())
    if normalizado in {"sim", "confirmo", "confirma", "pode", "pode sim", "isso", "claro"}:
        return True
    if normalizado in {"não", "nao", "cancela", "cancelar", "deixa", "não quero", "nao quero"}:
        return False
    return None


class PoliticaDeConfirmacao:
    def __init__(self, registro: RegistroDeFerramentas, timeout_s: float = 10) -> None:
        self.registro = registro
        self.timeout_s = timeout_s
        self.pendente: AcaoPendente | None = None

    def preparar(self, nome: str, argumentos: object) -> str | None:
        ferramenta = self.registro.obter(nome)
        valores = ferramenta.validar(argumentos)
        if nome == "usar_arquivo_perfil":
            from alfred.ferramentas.nativas import usar_arquivo_perfil
            if valores["operacao"] in {"listar", "ver"}:
                return self.registro.executar(nome, valores)
            descricao, versao = usar_arquivo_perfil.preparar_escrita(valores)
            self.pendente = AcaoPendente(ferramenta, valores, versao)
            return f"{descricao} Confirma esta alteração? Diga sim ou não."
        if nome == "enviar_email":
            from alfred.ferramentas.nativas import enviar_email
            faltante = enviar_email.verificar_configuracao()
            if faltante:
                return faltante
        if not ferramenta.sensivel:
            return self.registro.executar(nome, valores)
        self.pendente = AcaoPendente(ferramenta, valores)
        if nome == "lembrar_memoria":
            return "Quer que eu guarde essa informação na memória compartilhada? Diga sim ou não."
        if nome == "esquecer_memoria":
            return (
                f"Confirma apagar a memória {valores['identificador']} e as referências dela? "
                "Diga sim ou não."
            )
        if nome == "ligar_para":
            return f"Quer que eu ligue para {valores['contato']}? Diga sim ou não."
        if nome == "enviar_email":
            return (
                "Vou enviar este e-mail:\n"
                f"Para: {valores['destinatario']}\n"
                f"Assunto: {valores['assunto']}\n"
                f"Mensagem:\n{valores['mensagem']}\n"
                "Confirma o envio? Diga sim ou não."
            )
        if nome == "ler_arquivo":
            return f"Quer que eu use o arquivo {valores['nome']} como contexto de perfil? Diga sim ou não."
        return "Esta ação precisa da sua confirmação. Diga sim ou não."

    def resumo_voz(self) -> str:
        """Resumo curto falado; o texto completo fica disponível em `pendente`/pergunta."""
        pendente = self.pendente
        if pendente is None or pendente.ferramenta.nome != "usar_arquivo_perfil":
            return "Esta ação precisa da sua confirmação. Diga sim ou não."
        args = pendente.argumentos
        operacao = args["operacao"]
        nome = args.get("nome", "")
        frases = {
            "criar": f"Vou criar o perfil de {nome}.",
            "adicionar_fato": f"Vou adicionar um fato ao perfil de {nome}.",
            "remover_fato": f"Vou remover um fato do perfil de {nome}.",
            "remover_pessoa": f"Vou apagar o perfil de {nome}.",
        }
        return frases.get(operacao, "Confirma esta alteração?") + " Diga sim ou não."

    async def resolver(self, proxima_fala: asyncio.Future[str] | asyncio.Task[str] | Any) -> str:
        pendente, self.pendente = self.pendente, None
        if pendente is None:
            return "Não há ação aguardando confirmação."
        try:
            fala = await asyncio.wait_for(proxima_fala, timeout=self.timeout_s)
        except (TimeoutError, asyncio.TimeoutError):
            return "Sem confirmação; ação cancelada."
        autorizada = interpretar_confirmacao(fala)
        if autorizada is True:
            if pendente.ferramenta.nome == "usar_arquivo_perfil":
                from alfred.ferramentas.nativas import usar_arquivo_perfil
                return usar_arquivo_perfil.executar_confirmado(
                    pendente.argumentos, versao_esperada=pendente.versao_perfil
                )
            return self.registro.executar(pendente.ferramenta.nome, pendente.argumentos)
        return "Ação cancelada." if autorizada is False else "Resposta ambígua; ação cancelada."
