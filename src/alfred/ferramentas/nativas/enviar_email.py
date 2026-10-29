"""Envio de e-mail por SMTP com credenciais fornecidas pelo usuário."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import parseaddr
import smtplib
import ssl

from alfred.seguranca.credenciais_email import CofreEmailIndisponivel, obter


def _endereco_valido(endereco: str) -> bool:
    nome, parsed = parseaddr(endereco)
    return bool(parsed and "@" in parsed and "\r" not in endereco and "\n" not in endereco)


def verificar_configuracao() -> str | None:
    try:
        return None if obter() else (
            "E-mail não configurado. Use /configurar_email remetente senha_de_app "
            "servidor_smtp porta no chat local do Alfred."
        )
    except CofreEmailIndisponivel as erro:
        return f"E-mail não configurado: {erro}"


def executar(destinatario: str, assunto: str, mensagem: str) -> str:
    """Envia mensagem simples; a autorização do usuário ocorre antes no agente."""
    credenciais = obter()
    if credenciais is None:
        return "E-mail não configurado. Use /configurar_email remetente senha_de_app servidor_smtp porta."
    remetente = credenciais["remetente"]
    senha = credenciais["senha"]
    servidor = credenciais["servidor"]
    porta_texto = credenciais["porta"]
    if not _endereco_valido(remetente) or not _endereco_valido(destinatario):
        raise ValueError("Endereço de e-mail inválido")
    if "\r" in assunto or "\n" in assunto:
        raise ValueError("Assunto inválido")
    try:
        porta = int(porta_texto)
    except ValueError:
        raise ValueError("Porta SMTP inválida") from None
    if not 1 <= porta <= 65535:
        raise ValueError("Porta SMTP inválida")

    email = EmailMessage()
    email["From"] = remetente
    email["To"] = destinatario
    email["Subject"] = assunto
    email.set_content(mensagem)
    contexto = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(servidor, porta, context=contexto, timeout=20) as smtp:
            smtp.login(remetente, senha)
            smtp.send_message(email)
    else:
        with smtplib.SMTP(servidor, porta, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=contexto)
            smtp.ehlo()
            smtp.login(remetente, senha)
            smtp.send_message(email)
    return f"E-mail enviado para {destinatario}."
