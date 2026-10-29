"""Importação local e idempotente do histórico de voz registrado pelo Alfred."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from collections.abc import Iterable

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import abrir_conexao

log = logging.getLogger(__name__)
_LINHA_CONVERSA = re.compile(
    r"^(?P<data>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
    r"\w+ alfred\.voz conversa (?P<campo>frase_input|frase_output)="
    r'(?P<texto>"(?:\\.|[^"\\])*") resultado=.*$'
)


def _normalizar(texto: str) -> str:
    return " ".join(texto.casefold().split())


def importar_historico_voz(
    caminho_log: str | Path,
    banco_destino: BancoRelacional,
    bancos_existentes: Iterable[BancoRelacional] = (),
) -> int:
    """Importa falas preservadas no log sem repetir imports ou cópias já salvas."""
    caminho = Path(caminho_log)
    if not caminho.is_file():
        return 0

    fontes = [banco_destino, *bancos_existentes]
    existentes: dict[tuple[str, str], list[int]] = {}
    importacoes: set[str] = set()
    for fonte in fontes:
        try:
            with abrir_conexao(fonte.caminho, fonte._chave_banco, escritor=False) as db:
                linhas = db.execute(
                    "SELECT id, tipo, papel, texto, criado_em, origem "
                    "FROM eventos WHERE tipo='conversa' AND texto IS NOT NULL"
                ).fetchall()
            for linha in linhas:
                if linha["origem"] == "importacao":
                    importacoes.add(str(linha["id"]))
                papel = str(linha["papel"] or "")
                chave = (papel, _normalizar(str(linha["texto"])))
                existentes.setdefault(chave, []).append(int(linha["criado_em"]))
        except Exception as erro:
            log.info("Uma fonte local de histórico não pôde ser consultada (%s).", type(erro).__name__)

    importadas = 0
    for arquivo in sorted(caminho.parent.glob(caminho.name + "*")):
        if not arquivo.is_file():
            continue
        try:
            linhas_log = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as erro:
            log.info("Um log local de voz não pôde ser lido (%s).", type(erro).__name__)
            continue
        novos: list[tuple[int, str, str, str]] = []
        for numero_linha, linha in enumerate(linhas_log, start=1):
            correspondencia = _LINHA_CONVERSA.match(linha)
            if correspondencia is None:
                continue
            try:
                texto = json.loads(correspondencia.group("texto"))
                instante = datetime.strptime(
                    correspondencia.group("data"), "%Y-%m-%d %H:%M:%S,%f"
                ).astimezone()
            except (ValueError, TypeError):
                continue
            if not isinstance(texto, str) or not texto.strip():
                continue
            papel = "usuario" if correspondencia.group("campo") == "frase_input" else "alfred"
            instante_ms = int(instante.timestamp() * 1000)
            chave_texto = (papel, _normalizar(texto))
            repetida = any(
                abs(instante_ms - anterior) <= 3000
                for anterior in existentes.get(chave_texto, ())
            )
            if repetida:
                continue
            identidade = f"{arquivo.resolve()}:{numero_linha}:{instante_ms}:{papel}"
            identificador = str(uuid.uuid5(uuid.NAMESPACE_URL, identidade))
            if identificador in importacoes:
                continue
            novos.append((instante_ms, identificador, papel, texto.strip()))
            importacoes.add(identificador)

        if not novos:
            continue
        novos.sort(key=lambda item: (item[0], item[1]))
        sessao = banco_destino.criar_sessao(
            "voz", novos[0][0], modelo_llm="historico_importado"
        )
        for instante_ms, identificador, papel, texto in novos:
            banco_destino.inserir_evento(
                tipo="conversa",
                criado_em=instante_ms,
                origem="importacao",
                hash_texto=hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                papel=papel,
                texto=texto,
                sessao_id=sessao,
                indexado=False,
                id_evento=identificador,
            )
            importadas += 1
    return importadas
