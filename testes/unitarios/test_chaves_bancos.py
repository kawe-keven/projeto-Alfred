from __future__ import annotations

import base64
import os
import uuid

import pytest

from alfred.memoria.armazenamento.identificadores import gerar_uuid7
from alfred.seguranca.chaves.derivacao import derivar_subchave, hkdf_sha256
from alfred.seguranca.chaves.provedores import (
    ChaveMestra,
    ChaveMestraAusente,
    ProvedorDeAmbiente,
    ProvedorDeKeyring,
    ProvedorInterativo,
    resolver_provedor_de_chave,
)


def test_hkdf_sha256_rfc5869_caso_1() -> None:
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    esperado = bytes.fromhex(
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )
    assert hkdf_sha256(ikm, salt=salt, info=info, tamanho=42) == esperado


def test_subchaves_tem_rotulos_distintos() -> None:
    mestra = bytes(range(32))
    chaves = {
        derivar_subchave(mestra, rotulo)
        for rotulo in ("alfred.db", "auditoria.db", "metricas.db", "auditoria.hmac")
    }
    assert len(chaves) == 4
    with pytest.raises(ValueError, match="Rótulo"):
        derivar_subchave(mestra, "outro.db")


def test_representacao_da_chave_oculta_os_bytes() -> None:
    chave = ChaveMestra(b"x" * 32)
    assert repr(chave) == "ChaveMestra(<oculta>)"
    assert "x" * 32 not in repr(chave)
    assert "x" * 32 not in str(chave)


def test_provedor_de_ambiente_decodifica_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    valor = bytes(range(32))
    monkeypatch.setenv("ALFRED_SQLCIPHER_CHAVE", base64.b64encode(valor).decode())
    assert ProvedorDeAmbiente().obter_chave_mestra() == valor


def test_provedor_interativo_usa_leitura_oculta() -> None:
    chamadas: list[str] = []
    codificada = base64.b64encode(b"z" * 32).decode()

    def ler(prompt: str) -> str:
        chamadas.append(prompt)
        return codificada

    assert ProvedorInterativo(leitor=ler).obter_chave_mestra() == b"z" * 32
    assert "oculta" in chamadas[0]


def test_resolvedor_prioriza_variavel_e_rejeita_ausencia() -> None:
    codificada = base64.b64encode(b"a" * 32).decode()
    resolvedor = resolver_provedor_de_chave(
        ambiente={"ALFRED_SQLCIPHER_CHAVE": codificada}, interativo_disponivel=True
    )
    assert isinstance(resolvedor, ProvedorDeAmbiente)
    assert resolvedor.obter_chave_mestra() == b"a" * 32
    with pytest.raises(ChaveMestraAusente, match="terminal"):
        resolver_provedor_de_chave(ambiente={}, interativo_disponivel=False)


class KeyringFalso:
    def __init__(self) -> None:
        self.credenciais: dict[tuple[str, str], str] = {}

    def get_password(self, servico: str, conta: str) -> str | None:
        return self.credenciais.get((servico, conta))

    def set_password(self, servico: str, conta: str, segredo: str) -> None:
        self.credenciais[(servico, conta)] = segredo


def test_keyring_guarda_e_le_chave_base64_sem_exibi_la() -> None:
    backend = KeyringFalso()
    provedor = ProvedorDeKeyring(backend)
    chave = bytes(range(32))
    provedor.guardar_chave_mestra(chave)
    assert provedor.obter_chave_mestra() == chave
    assert set(backend.credenciais) == {
        (ProvedorDeKeyring.SERVICO, ProvedorDeKeyring.CONTA)
    }
    assert backend.credenciais[
        (ProvedorDeKeyring.SERVICO, ProvedorDeKeyring.CONTA)
    ] == base64.b64encode(chave).decode("ascii")


def test_resolvedor_usa_keyring_antes_do_prompt_e_env_tem_precedencia() -> None:
    backend = KeyringFalso()
    keyring = ProvedorDeKeyring(backend)
    keyring.guardar_chave_mestra(b"k" * 32)
    resolvedor = resolver_provedor_de_chave(
        ambiente={}, interativo_disponivel=True, leitor=lambda _: "não deveria ler",
        provedor_keyring=keyring,
    )
    assert resolvedor is keyring
    assert resolvedor.obter_chave_mestra() == b"k" * 32

    env = base64.b64encode(b"e" * 32).decode("ascii")
    resolvedor_env = resolver_provedor_de_chave(
        ambiente={"ALFRED_SQLCIPHER_CHAVE": env},
        interativo_disponivel=True,
        provedor_keyring=keyring,
    )
    assert isinstance(resolvedor_env, ProvedorDeAmbiente)
    assert resolvedor_env.obter_chave_mestra() == b"e" * 32


def test_resolvedor_recua_para_leitura_oculta_se_keyring_sem_credencial() -> None:
    codificada = base64.b64encode(b"i" * 32).decode("ascii")
    resolvedor = resolver_provedor_de_chave(
        ambiente={},
        interativo_disponivel=True,
        leitor=lambda _: codificada,
        provedor_keyring=ProvedorDeKeyring(KeyringFalso()),
    )
    assert isinstance(resolvedor, ProvedorInterativo)
    assert resolvedor.obter_chave_mestra() == b"i" * 32


def test_keyring_invalido_nao_recua_para_outra_chave() -> None:
    backend = KeyringFalso()
    backend.credenciais[(ProvedorDeKeyring.SERVICO, ProvedorDeKeyring.CONTA)] = "invalida"
    with pytest.raises(ChaveMestraAusente):
        resolver_provedor_de_chave(
            ambiente={},
            interativo_disponivel=True,
            leitor=lambda _: base64.b64encode(b"f" * 32).decode("ascii"),
            provedor_keyring=ProvedorDeKeyring(backend),
        )


def test_keyring_public_api_com_backend_em_memoria(monkeypatch: pytest.MonkeyPatch) -> None:
    keyring = pytest.importorskip("keyring")
    import keyring.core
    from keyring.backend import KeyringBackend

    class BackendMemoria(KeyringBackend):
        priority = 1.0

        def __init__(self) -> None:
            self.credenciais: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.credenciais.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.credenciais[(service, username)] = password

    backend_anterior = getattr(keyring.core, "_keyring_backend", None)
    keyring.set_keyring(BackendMemoria())
    try:
        provedor = ProvedorDeKeyring()
        provedor.guardar_chave_mestra(b"m" * 32)
        assert ProvedorDeKeyring().obter_chave_mestra() == b"m" * 32
    finally:
        monkeypatch.setattr(keyring.core, "_keyring_backend", backend_anterior, raising=False)


def test_winerror_1312_recua_para_entrada_oculta() -> None:
    class BackendIsolado(KeyringFalso):
        def get_password(self, servico: str, conta: str) -> str | None:
            raise OSError(1312, "logon session unavailable")

    codificada = base64.b64encode(b"w" * 32).decode("ascii")
    provedor = resolver_provedor_de_chave(
        ambiente={},
        interativo_disponivel=True,
        leitor=lambda _: codificada,
        provedor_keyring=ProvedorDeKeyring(BackendIsolado()),
    )
    assert isinstance(provedor, ProvedorInterativo)
    assert provedor.obter_chave_mestra() == b"w" * 32


def test_chave_invalida_nao_aparece_no_erro() -> None:
    sentinela = "SEGREDO_FICTICIO_NAO_EXIBIR"
    with pytest.raises(ChaveMestraAusente) as erro:
        ProvedorInterativo(leitor=lambda _: sentinela).obter_chave_mestra()
    assert sentinela not in str(erro.value)


def test_gerador_produz_uuid_v7() -> None:
    identificador = uuid.UUID(gerar_uuid7())
    assert identificador.version == 7
    assert identificador.variant == uuid.RFC_4122
