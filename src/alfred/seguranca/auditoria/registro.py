"""Trilha de auditoria SQLCipher com cadeia HMAC e âncora local."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.chaves.derivacao import derivar_subchave


GENESIS_HASH = hashlib.sha256(b"alfred-auditoria-genesis-v1").digest()
_CAMPOS_NUMERICOS = frozenset(
    {"duracao_ms", "quantidade", "tamanho_bytes", "tentativas", "latencia_ms", "recurso_mb"}
)
_CAMPOS_BOOLEANOS = frozenset({"barge_in", "reutilizado", "confirmado"})
_ENUMS = {
    "interface": frozenset({"cli", "voz"}),
    "estado": frozenset({"ativa", "resumida", "arquivada", "pendente", "concluido"}),
    "origem": frozenset({"usuario", "alfred", "arquivo", "importacao", "sistema"}),
    "codigo": frozenset(
        {"ok", "erro", "negado", "invalido", "timeout", "indisponivel", "nao_encontrado"}
    ),
    "modo": frozenset({"leitura", "escrita", "backup", "verificacao", "reindexacao"}),
    "componente": frozenset({"llm", "stt", "tts", "banco", "chroma", "auditoria"}),
}
_CAMPOS_HASH = frozenset({"hash", "hash_texto", "hash_arquivo"})
_REGEX_IDENTIFICADOR = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_REGEX_HASH = re.compile(r"^[0-9a-fA-F]{16,64}$")
_RESULTADOS = {"ok", "falha", "negado", "cancelado"}
_ATORES = {"usuario", "alfred", "sistema"}


class ErroAuditoria(RuntimeError):
    """Falha segura de auditoria sem conteúdo, chave ou caminho."""


@dataclass(frozen=True)
class ResultadoVerificacao:
    valida: bool
    seq_inconsistente: int | None = None
    codigo: Literal[
        "valida",
        "hash_invalido",
        "ancora_ausente",
        "ancora_invalida",
        "truncada",
        "ancora_desatualizada",
    ] = "valida"


def _json_canonico(valor: object) -> str:
    return json.dumps(
        valor,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validar_identificador(valor: str, rotulo: str) -> None:
    if not isinstance(valor, str) or not _REGEX_IDENTIFICADOR.fullmatch(valor):
        raise ErroAuditoria(f"Campo {rotulo} deve ser um identificador curto")


def _validar_metadados(meta: dict[str, object]) -> str:
    for chave, valor in meta.items():
        if not isinstance(chave, str):
            raise ErroAuditoria("Metadado não permitido")
        if chave in _CAMPOS_NUMERICOS:
            if (
                isinstance(valor, bool)
                or not isinstance(valor, (int, float))
                or not math.isfinite(valor)
                or valor < 0
            ):
                raise ErroAuditoria("Tipo de metadado inválido")
        elif chave in _CAMPOS_BOOLEANOS:
            if not isinstance(valor, bool):
                raise ErroAuditoria("Tipo de metadado inválido")
        elif chave in _ENUMS:
            if not isinstance(valor, str) or valor not in _ENUMS[chave]:
                raise ErroAuditoria("Valor enumerado de metadado inválido")
        elif chave in _CAMPOS_HASH:
            if not isinstance(valor, str) or not _REGEX_HASH.fullmatch(valor):
                raise ErroAuditoria("Hash de metadado inválido")
        else:
            raise ErroAuditoria("Chave de metadado não permitida")
    try:
        return _json_canonico(meta)
    except (TypeError, ValueError):
        raise ErroAuditoria("Metadados não podem ser serializados") from None


def _payload_hash(
    seq: int,
    ts_ms: int,
    categoria: str,
    acao: str,
    resultado: str,
    ator: str,
    ferramenta: str | None,
    meta_json: str,
    hash_anterior: bytes,
) -> bytes:
    dados = {
        "seq": seq,
        "ts_ms": ts_ms,
        "categoria": categoria,
        "acao": acao,
        "resultado": resultado,
        "ator": ator,
        "ferramenta": ferramenta,
        "meta_json": meta_json,
        "hash_anterior": hash_anterior.hex(),
    }
    return _json_canonico(dados).encode("utf-8")


class RegistroDeAuditoria:
    """Escreve e verifica eventos de auditoria sem guardar conteúdo pessoal."""

    def __init__(
        self,
        caminho_banco: str | Path,
        caminho_ancora: str | Path,
        chave_mestra: bytes,
        *,
        relogio_ms: object | None = None,
    ) -> None:
        if len(chave_mestra) != 32:
            raise ValueError("A chave-mestra deve conter exatamente 32 bytes")
        self.caminho_banco = Path(caminho_banco)
        self.caminho_ancora = Path(caminho_ancora)
        if self.caminho_banco.resolve() == self.caminho_ancora.resolve():
            raise ValueError("Banco e âncora devem usar arquivos diferentes")
        self._chave_banco = derivar_subchave(chave_mestra, "auditoria.db")
        self._chave_hmac = derivar_subchave(chave_mestra, "auditoria.hmac")
        self._relogio_ms = relogio_ms or (lambda: time.time_ns() // 1_000_000)

    def _preparar_esquema(self, conexao: object) -> None:
        conexao.execute(
            "CREATE TABLE IF NOT EXISTS auditoria ("
            "seq INTEGER PRIMARY KEY, ts_ms INTEGER NOT NULL, categoria TEXT NOT NULL, "
            "acao TEXT NOT NULL, resultado TEXT NOT NULL "
            "CHECK (resultado IN ('ok','falha','negado','cancelado')), "
            "ator TEXT NOT NULL CHECK (ator IN ('usuario','alfred','sistema')), "
            "ferramenta TEXT, meta_json TEXT NOT NULL, hash_anterior BLOB NOT NULL, hash BLOB NOT NULL)"
        )
        conexao.execute(
            "CREATE TRIGGER IF NOT EXISTS auditoria_sem_update "
            "BEFORE UPDATE ON auditoria BEGIN SELECT RAISE(ABORT, 'auditoria imutavel'); END"
        )
        conexao.execute(
            "CREATE TRIGGER IF NOT EXISTS auditoria_sem_delete "
            "BEFORE DELETE ON auditoria BEGIN SELECT RAISE(ABORT, 'auditoria imutavel'); END"
        )
        conexao.commit()

    def registrar(
        self,
        categoria: str,
        acao: str,
        resultado: str,
        ator: str,
        ferramenta: str | None = None,
        **meta: object,
    ) -> int:
        _validar_identificador(categoria, "categoria")
        _validar_identificador(acao, "acao")
        if resultado not in _RESULTADOS:
            raise ErroAuditoria("Resultado de auditoria inválido")
        if ator not in _ATORES:
            raise ErroAuditoria("Ator de auditoria inválido")
        if ferramenta is not None:
            _validar_identificador(ferramenta, "ferramenta")
        meta_json = _validar_metadados(meta)
        ts_ms = int(self._relogio_ms())  # type: ignore[operator]
        try:
            with abrir_conexao(
                self.caminho_banco, self._chave_banco, finalidade="auditoria"
            ) as conexao:
                self._preparar_esquema(conexao)
                verificacao = self._verificar_na_conexao(conexao)
                if not verificacao.valida:
                    raise ErroAuditoria("A cadeia ou âncora de auditoria está inconsistente")
                anterior = conexao.execute(
                    "SELECT seq, hash FROM auditoria ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq = 1 if anterior is None else int(anterior["seq"]) + 1
                hash_anterior = GENESIS_HASH if anterior is None else bytes(anterior["hash"])
                conteudo = _payload_hash(
                    seq,
                    ts_ms,
                    categoria,
                    acao,
                    resultado,
                    ator,
                    ferramenta,
                    meta_json,
                    hash_anterior,
                )
                hash_atual = hmac.new(self._chave_hmac, conteudo, hashlib.sha256).digest()
                conexao.execute(
                    "INSERT INTO auditoria(seq, ts_ms, categoria, acao, resultado, ator, "
                    "ferramenta, meta_json, hash_anterior, hash) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        seq,
                        ts_ms,
                        categoria,
                        acao,
                        resultado,
                        ator,
                        ferramenta,
                        meta_json,
                        hash_anterior,
                        hash_atual,
                    ),
                )
                conexao.commit()
                self._gravar_ancora(seq, hash_atual)
                return seq
        except ErroAuditoria:
            raise
        except Exception:
            raise ErroAuditoria("Não foi possível registrar o evento de auditoria") from None

    def verificar_cadeia(self) -> ResultadoVerificacao:
        try:
            with abrir_conexao(
                self.caminho_banco,
                self._chave_banco,
                finalidade="auditoria",
                escritor=False,
            ) as conexao:
                self._preparar_esquema(conexao)
                return self._verificar_na_conexao(conexao)
        except Exception:
            return ResultadoVerificacao(False, 1, "hash_invalido")

    def _verificar_na_conexao(self, conexao: object) -> ResultadoVerificacao:
        anterior = GENESIS_HASH
        sequencia_esperada = 1
        hash_final = GENESIS_HASH
        linhas = conexao.execute(
            "SELECT seq, ts_ms, categoria, acao, resultado, ator, ferramenta, "
            "meta_json, hash_anterior, hash FROM auditoria ORDER BY seq"
        ).fetchall()
        for linha in linhas:
            seq = int(linha["seq"])
            anterior_linha = bytes(linha["hash_anterior"])
            hash_linha = bytes(linha["hash"])
            if seq != sequencia_esperada or not hmac.compare_digest(anterior_linha, anterior):
                return ResultadoVerificacao(False, seq, "hash_invalido")
            conteudo = _payload_hash(
                seq,
                int(linha["ts_ms"]),
                str(linha["categoria"]),
                str(linha["acao"]),
                str(linha["resultado"]),
                str(linha["ator"]),
                linha["ferramenta"],
                str(linha["meta_json"]),
                anterior_linha,
            )
            calculado = hmac.new(self._chave_hmac, conteudo, hashlib.sha256).digest()
            if not hmac.compare_digest(calculado, hash_linha):
                return ResultadoVerificacao(False, seq, "hash_invalido")
            anterior = hash_linha
            hash_final = hash_linha
            sequencia_esperada += 1

        ancora = self._ler_ancora()
        if ancora is None:
            if linhas:
                return ResultadoVerificacao(False, len(linhas), "ancora_ausente")
            return ResultadoVerificacao(True)
        seq_ancora, hash_ancora, ancora_valida = ancora
        if not ancora_valida:
            return ResultadoVerificacao(False, max(seq_ancora, 1), "ancora_invalida")
        seq_final = len(linhas)
        if seq_final < seq_ancora:
            return ResultadoVerificacao(False, seq_final + 1, "truncada")
        if seq_final > seq_ancora:
            return ResultadoVerificacao(False, seq_ancora + 1, "ancora_desatualizada")
        if not hmac.compare_digest(hash_final, hash_ancora):
            return ResultadoVerificacao(False, max(seq_final, 1), "ancora_invalida")
        return ResultadoVerificacao(True)

    def _conteudo_ancora(self, seq: int, hash_final: bytes) -> tuple[dict[str, object], str]:
        dados: dict[str, object] = {"seq": seq, "hash": hash_final.hex()}
        canonico = _json_canonico(dados)
        assinatura = hmac.new(
            self._chave_hmac, b"ancora\0" + canonico.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return dados, assinatura

    def _gravar_ancora(self, seq: int, hash_final: bytes) -> None:
        dados, assinatura = self._conteudo_ancora(seq, hash_final)
        conteudo = _json_canonico({**dados, "hmac": assinatura}) + "\n"
        temporario = self.caminho_ancora.with_name(self.caminho_ancora.name + ".tmp")
        try:
            self.caminho_ancora.parent.mkdir(parents=True, exist_ok=True)
            with temporario.open("w", encoding="ascii", newline="\n") as arquivo:
                arquivo.write(conteudo)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, self.caminho_ancora)
        except OSError:
            temporario.unlink(missing_ok=True)
            raise ErroAuditoria("Não foi possível atualizar a âncora de auditoria") from None

    def _ler_ancora(self) -> tuple[int, bytes, bool] | None:
        if not self.caminho_ancora.exists():
            return None
        try:
            dados = json.loads(self.caminho_ancora.read_text(encoding="ascii"))
            seq = dados.get("seq")
            hash_hex = dados.get("hash")
            assinatura = dados.get("hmac")
            if (
                isinstance(seq, bool)
                or not isinstance(seq, int)
                or seq < 0
                or not isinstance(hash_hex, str)
                or not re.fullmatch(r"[0-9a-f]{64}", hash_hex)
                or not isinstance(assinatura, str)
                or not re.fullmatch(r"[0-9a-f]{64}", assinatura)
            ):
                return (1, GENESIS_HASH, False)
            hash_final = bytes.fromhex(hash_hex)
            esperado, _ = self._conteudo_ancora(seq, hash_final)
            canonico = _json_canonico(esperado)
            mac_esperado = hmac.new(
                self._chave_hmac,
                b"ancora\0" + canonico.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return seq, hash_final, hmac.compare_digest(mac_esperado, assinatura)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return (1, GENESIS_HASH, False)
