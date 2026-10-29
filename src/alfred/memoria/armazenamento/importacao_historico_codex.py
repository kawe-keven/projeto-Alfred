"""Importa mensagens de sessões locais do Codex para o histórico cifrado Alfred."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import abrir_conexao

log = logging.getLogger(__name__)
_NAMESPACE = uuid.UUID("a33b5a87-0f5c-4cb0-8d83-3a7f911c468a")


def _abrir_texto(caminho: Path) -> TextIO:
    if caminho.suffix == ".zst":
        try:
            from compression import zstd
        except ImportError:
            import zstandard as zstd

        return zstd.open(caminho, "rt", encoding="utf-8", errors="replace")
    return caminho.open("r", encoding="utf-8", errors="replace")


def _instante_ms(valor: object) -> int | None:
    if not isinstance(valor, str):
        return None
    try:
        instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return int(instante.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def _texto_mensagem(conteudo: object) -> str:
    if not isinstance(conteudo, list):
        return ""
    trechos = [
        item["text"].strip()
        for item in conteudo
        if isinstance(item, dict)
        and item.get("type") in {"input_text", "output_text", "text"}
        and isinstance(item.get("text"), str)
        and item["text"].strip()
    ]
    return "\n".join(trechos).strip()


def _ler_sessao(caminho: Path) -> tuple[str, int, list[tuple[str, int, str, str]]]:
    id_origem = caminho.stem.removesuffix(".jsonl")
    inicio = 0
    mensagens: list[tuple[str, int, str, str]] = []
    with _abrir_texto(caminho) as arquivo:
        for linha in arquivo:
            try:
                registro = json.loads(linha)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(registro, dict):
                continue
            carga = registro.get("payload")
            if not isinstance(carga, dict):
                continue
            if registro.get("type") == "session_meta":
                id_origem = str(carga.get("id") or id_origem)
                inicio = _instante_ms(carga.get("timestamp")) or inicio
                continue
            if registro.get("type") != "response_item" or carga.get("type") != "message":
                continue
            papel_origem = carga.get("role")
            if papel_origem not in {"user", "assistant"}:
                continue
            texto = _texto_mensagem(carga.get("content"))
            instante = _instante_ms(registro.get("timestamp"))
            if not texto or instante is None:
                continue
            papel = "usuario" if papel_origem == "user" else "alfred"
            id_mensagem = str(carga.get("id") or f"{instante}:{papel}:{hashlib.sha256(texto.encode()).hexdigest()}")
            mensagens.append((id_mensagem, instante, papel, texto))
            inicio = min(inicio, instante) if inicio else instante
    return id_origem, inicio, mensagens


def importar_historico_codex(
    diretorio_codex: str | Path,
    banco_destino: BancoRelacional,
) -> int:
    """Importa idempotentemente as mensagens textuais de todas as sessões Codex locais."""
    raiz = Path(diretorio_codex).expanduser()
    if not raiz.is_dir():
        return 0
    caminhos = sorted({*raiz.glob("sessions/**/*.jsonl"), *raiz.glob("archived_sessions/**/*.jsonl.zst")})
    inseridos = 0
    for caminho in caminhos:
        try:
            id_origem, inicio, mensagens = _ler_sessao(caminho)
        except (OSError, ImportError, ValueError) as erro:
            log.info("Uma sessão local do Codex não pôde ser importada (%s).", type(erro).__name__)
            continue
        if not mensagens:
            continue
        id_sessao = str(uuid.uuid5(_NAMESPACE, id_origem))
        with abrir_conexao(banco_destino.caminho, banco_destino._chave_banco) as conexao:
            conexao.execute(
                "INSERT OR IGNORE INTO sessoes(id, iniciada_em, interface, modelo_llm) "
                "VALUES(?, ?, 'cli', 'codex_importado')",
                (id_sessao, inicio or mensagens[0][1]),
            )
            novos = []
            for id_mensagem, instante, papel, texto in mensagens:
                id_evento = str(uuid.uuid5(_NAMESPACE, f"{id_origem}:{id_mensagem}"))
                novos.append((
                    id_evento, papel, texto, instante, id_sessao,
                    50,
                    hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                ))
            antes = conexao.total_changes
            conexao.executemany(
                "INSERT OR IGNORE INTO eventos "
                "(id, tipo, papel, texto, criado_em, sessao_id, origem, importancia, hash_texto) "
                "VALUES(?, 'conversa', ?, ?, ?, ?, 'importacao', ?, ?)",
                novos,
            )
            inseridos += conexao.total_changes - antes
            conexao.commit()
    return inseridos


def diretorio_codex_padrao() -> Path:
    """Retorna a pasta de dados Codex do usuário que executa o Alfred."""
    configurado = os.getenv("ALFRED_DIRETORIO_CODEX")
    return Path(configurado).expanduser() if configurado else Path.home() / ".codex"
