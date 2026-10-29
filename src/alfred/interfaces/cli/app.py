"""Interface de terminal do Alfred."""

from __future__ import annotations

import getpass
import logging
import sys
from collections.abc import Callable

from alfred.adaptadores.llm.fabrica import criar_provedor
from alfred.configuracao.configuracao import Configuracao, carregar_configuracao
from alfred.interfaces.cli.sessao import FIM, SessaoConversa
from alfred.memoria.perfil.carregador import ErroDePerfil, carregar_perfil
from alfred.nucleo.provedor_llm import ErroProvedorLLM
from alfred.nucleo.saudacao import saudacao_por_horario

log = logging.getLogger(__name__)


def _criar_sessao(
    configuracao: Configuracao,
    *,
    confirmar: Callable[[str], str] | None = None,
    interativo_disponivel: bool = False,
) -> SessaoConversa:
    perfil = carregar_perfil(configuracao.pasta_perfil)
    provedor = criar_provedor(configuracao)
    return SessaoConversa(
        provedor, configuracao, perfil, confirmar=confirmar,
        interativo_disponivel=interativo_disponivel,
    )


def _configurar_email_interativo(
    entrada: Callable[[str], str], saida: Callable[[str], object]
) -> None:
    from alfred.seguranca.credenciais_email import (
        CofreEmailIndisponivel,
        guardar,
        validar_configuracao,
    )

    try:
        remetente = entrada("Endereço de e-mail: ").strip()
        servidor = entrada("Servidor SMTP: ").strip()
        porta = entrada("Porta SMTP [587]: ").strip() or "587"
        senha = getpass.getpass("Senha de app SMTP (entrada oculta): ")
        guardar(validar_configuracao(remetente, senha, servidor, porta))
    except (ValueError, CofreEmailIndisponivel) as erro:
        saida(str(erro))
    except (EOFError, KeyboardInterrupt):
        saida("Configuração de e-mail cancelada.")
    else:
        saida("Credenciais de e-mail armazenadas de forma protegida neste computador.")


def executar(
    *,
    configuracao: Configuracao | None = None,
    entrada: Callable[[str], str] = input,
    saida: Callable[[str], object] = print,
) -> int:
    try:
        configuracao = configuracao or carregar_configuracao()
        sessao = _criar_sessao(
            configuracao,
            confirmar=lambda pergunta: entrada(pergunta),
            interativo_disponivel=sys.stdin.isatty(),
        )
    except ErroDePerfil as erro:
        log.debug("Inicialização interrompida: %s", erro)
        print(f"Erro no perfil: {erro}", file=sys.stderr)
        print(
            "Confira os arquivos fatores_estaveis.md, conhecimento_abrangente.md "
            "e preferencias.md em dados/perfil, incluindo o cabeçalho YAML.",
            file=sys.stderr,
        )
        return 1
    except ValueError as erro:
        log.debug("Configuração inválida: %s", erro)
        print(f"Erro na configuração: {erro}", file=sys.stderr)
        return 1

    saida(f"{saudacao_por_horario()} Alfred pronto. Digite /ajuda para ver os comandos.")
    while True:
        try:
            texto = entrada("Você: ").strip()
        except EOFError:
            saida("Até mais.")
            return 0
        except KeyboardInterrupt:
            saida("\nAté mais.")
            return 0

        if not texto:
            continue
        if texto.startswith("/"):
            try:
                if texto.startswith(("/configurar_email ", "/configuraremail ")):
                    saida("Por segurança, não cole credenciais no terminal. Digite somente /configurar_email para informá-las em campos adequados.")
                    continue
                if texto in {"/configurar_email", "/configuraremail"}:
                    _configurar_email_interativo(entrada, saida)
                    continue
                resultado = sessao.executar_comando(texto)
                if resultado is FIM:
                    saida("Até mais.")
                    return 0
                saida(resultado or "Comando desconhecido. Digite /ajuda.")
            except ErroDePerfil as erro:
                log.debug("Não foi possível recarregar o perfil: %s", erro)
                saida(f"Erro ao recarregar perfil: {erro}")
            continue

        try:
            saida("Alfred: ", end="")
            for trecho in sessao.responder(texto):
                saida(trecho, end="", flush=True)
            saida("")
        except KeyboardInterrupt:
            # A sessão só grava a resposta completa; o próximo turno continua normalmente.
            saida("\nResposta interrompida.")
        except ErroProvedorLLM as erro:
            log.debug("Falha do provedor LLM: %s", erro)
            saida(f"\nErro ao conversar com o modelo: {erro}")
    return 0


def main() -> int:
    return executar()
