"""Credenciais SMTP no cofre de credenciais do sistema operacional."""

from __future__ import annotations

import json
import re


SERVICO_EMAIL = "alfred"
CONTA_EMAIL = "smtp-configuracao"


class CofreEmailIndisponivel(RuntimeError):
    """O cofre seguro não pode ser acessado ou atualizado."""


def _keyring():
    try:
        import keyring
    except ImportError:
        raise CofreEmailIndisponivel(
            "Cofre do sistema indisponível. Instale as dependências de segurança do Alfred."
        ) from None
    return keyring


def validar_configuracao(remetente: str, senha: str, servidor: str, porta: str) -> dict[str, str]:
    remetente = remetente.strip()
    servidor = servidor.strip()
    if len(remetente) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", remetente):
        raise ValueError("Informe um endereço de e-mail válido.")
    if not senha or len(senha) > 1024 or any(ord(c) < 32 for c in senha):
        raise ValueError("A senha de SMTP está vazia ou contém caracteres inválidos.")
    if len(servidor) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", servidor):
        raise ValueError("Informe o servidor SMTP, por exemplo smtp.gmail.com.")
    try:
        numero_porta = int(porta)
    except ValueError:
        raise ValueError("A porta SMTP deve ser um número entre 1 e 65535.") from None
    if not 1 <= numero_porta <= 65535:
        raise ValueError("A porta SMTP deve ser um número entre 1 e 65535.")
    return {
        "remetente": remetente,
        "senha": senha,
        "servidor": servidor,
        "porta": str(numero_porta),
    }


def guardar(configuracao: dict[str, str]) -> None:
    valor = json.dumps(configuracao, ensure_ascii=False)
    try:
        _keyring().set_password(SERVICO_EMAIL, CONTA_EMAIL, valor)
    except Exception as erro:
        raise CofreEmailIndisponivel(
            "O cofre do Windows recusou o acesso nesta sessão. Inicie o Alfred na sua sessão normal do Windows e tente configurar novamente."
        ) from erro


def obter() -> dict[str, str] | None:
    erro_keyring = False
    try:
        valor = _keyring().get_password(SERVICO_EMAIL, CONTA_EMAIL)
    except Exception:
        valor = None
        erro_keyring = True
    if valor is None and erro_keyring:
        raise CofreEmailIndisponivel(
            "O cofre do Windows não está disponível nesta sessão."
        )
    if valor is None:
        return None
    try:
        resultado = json.loads(valor)
        if not isinstance(resultado, dict) or set(resultado) != {"remetente", "senha", "servidor", "porta"}:
            raise ValueError
        return {chave: str(conteudo) for chave, conteudo in resultado.items()}
    except (ValueError, TypeError, json.JSONDecodeError):
        raise CofreEmailIndisponivel(
            "As credenciais salvas no cofre estão inválidas; configure-as novamente."
        ) from None
