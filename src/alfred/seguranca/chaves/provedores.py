"""Leitura da chave-mestra sem persistência pelo Alfred."""

from __future__ import annotations

import base64
import binascii
import getpass
import os
import sys
from collections.abc import Callable, Mapping
from typing import Protocol


NOME_VARIAVEL_CHAVE = "ALFRED_SQLCIPHER_CHAVE"


class ChaveMestra(bytes):
    """Bytes de chave com representação acidentalmente segura."""

    def __new__(cls, valor: bytes) -> ChaveMestra:
        if not isinstance(valor, bytes) or len(valor) != 32:
            raise ValueError("A chave-mestra deve conter exatamente 32 bytes")
        return super().__new__(cls, valor)

    def __repr__(self) -> str:
        return "ChaveMestra(<oculta>)"

    def __str__(self) -> str:
        return "<chave-mestra oculta>"


class ChaveMestraAusente(RuntimeError):
    """Indica que não há chave disponível sem expor o valor recebido."""


class KeyringIndisponivel(ChaveMestraAusente):
    """O backend de credenciais do sistema não pôde ser usado."""


class CredencialKeyringAusente(ChaveMestraAusente):
    """O backend está acessível, mas não contém a credencial Alfred."""


class ProvedorDeChave(Protocol):
    def obter_chave_mestra(self) -> ChaveMestra:
        """Retorna a chave de 32 bytes apenas para uso em memória."""


def _decodificar_chave(valor: str) -> ChaveMestra:
    try:
        decodificada = base64.b64decode(valor.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise ChaveMestraAusente(
            "A chave deve estar em base64 válido e representar exatamente 32 bytes"
        ) from None
    if len(decodificada) != 32:
        raise ChaveMestraAusente(
            "A chave deve estar em base64 válido e representar exatamente 32 bytes"
        )
    return ChaveMestra(decodificada)


class ProvedorDeAmbiente:
    """Lê a chave-mestra base64 de ALFRED_SQLCIPHER_CHAVE."""

    def __init__(
        self,
        nome_variavel: str = NOME_VARIAVEL_CHAVE,
        ambiente: Mapping[str, str] | None = None,
    ) -> None:
        self.nome_variavel = nome_variavel
        self._ambiente = os.environ if ambiente is None else ambiente

    def obter_chave_mestra(self) -> ChaveMestra:
        valor = self._ambiente.get(self.nome_variavel)
        if valor is None:
            raise ChaveMestraAusente(
                f"{self.nome_variavel} não está definida; use a leitura interativa oculta"
            )
        return _decodificar_chave(valor)


class ProvedorInterativo:
    """Solicita a chave em leitura oculta; mantém os bytes só em memória."""

    def __init__(self, leitor: Callable[[str], str] | None = None) -> None:
        self._leitor = leitor or getpass.getpass

    def obter_chave_mestra(self) -> ChaveMestra:
        try:
            valor = self._leitor("Chave-mestra SQLCipher (base64, entrada oculta): ")
        except (EOFError, OSError):
            raise ChaveMestraAusente(
                "Não foi possível ler a chave; execute em um terminal interativo"
            ) from None
        return _decodificar_chave(valor)


class ProvedorDeKeyring:
    """Lê ou grava a chave-mestra no cofre do sistema via pacote opcional keyring."""

    SERVICO = "alfred"
    CONTA = "sqlcipher-chave-mestra"

    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend
        self._chave_em_memoria: ChaveMestra | None = None

    def _obter_backend(self) -> object:
        if self._backend is not None:
            return self._backend
        try:
            import keyring
        except ImportError:
            raise KeyringIndisponivel(
                "Keyring não instalado; use o extra seguranca ou a leitura oculta"
            ) from None
        self._backend = keyring
        return keyring

    def obter_chave_mestra(self) -> ChaveMestra:
        if self._chave_em_memoria is not None:
            return self._chave_em_memoria
        backend = self._obter_backend()
        try:
            valor = backend.get_password(self.SERVICO, self.CONTA)  # type: ignore[attr-defined]
        except Exception:
            raise KeyringIndisponivel(
                "O cofre do sistema não está disponível; use a leitura oculta"
            ) from None
        if valor is None:
            raise CredencialKeyringAusente("Não há chave-mestra no cofre do sistema")
        chave = _decodificar_chave(valor)
        self._chave_em_memoria = chave
        return chave

    def guardar_chave_mestra(self, chave: bytes) -> None:
        """Grava uma chave já obtida explicitamente; não gera nem exibe segredos."""

        validada = ChaveMestra(chave)
        backend = self._obter_backend()
        valor = base64.b64encode(validada).decode("ascii")
        try:
            backend.set_password(self.SERVICO, self.CONTA, valor)  # type: ignore[attr-defined]
        except Exception:
            raise KeyringIndisponivel(
                "Não foi possível gravar a chave no cofre do sistema"
            ) from None
        self._chave_em_memoria = validada


def resolver_provedor_de_chave(
    *,
    ambiente: dict[str, str] | None = None,
    interativo_disponivel: bool | None = None,
    leitor: Callable[[str], str] | None = None,
    provedor_keyring: ProvedorDeKeyring | None = None,
) -> ProvedorDeChave:
    """Prioriza ambiente, keyring disponível e por fim leitura oculta."""

    valores = os.environ if ambiente is None else ambiente
    if NOME_VARIAVEL_CHAVE in valores:
        return ProvedorDeAmbiente(ambiente=valores)
    keyring = provedor_keyring or ProvedorDeKeyring()
    try:
        keyring.obter_chave_mestra()
    except (CredencialKeyringAusente, KeyringIndisponivel):
        pass
    else:
        return keyring
    disponivel = sys.stdin.isatty() if interativo_disponivel is None else interativo_disponivel
    if disponivel:
        return ProvedorInterativo(leitor)
    raise ChaveMestraAusente(
        "Chave SQLCipher ausente no ambiente e no keyring; execute em terminal "
        "para digitá-la sem exibição"
    )
