"""Cria documentos Markdown ou texto, atomicamente, em uma pasta confinada."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from pathlib import Path

from alfred.configuracao.configuracao import carregar_configuracao
from alfred.ferramentas.nativas._caminhos import (
    resolver_arquivo_confinado,
    resolver_pasta_absoluta,
    validar_nome_simples,
)

log = logging.getLogger("alfred.arquivos")
_LOCK_COTA = threading.Lock()
_EXTENSOES_PERMITIDAS = {".md", ".txt"}


def executar(nome: str, conteudo: str) -> str:
    """Cria arquivo novo sem sobrescrita e aplica cotas configuráveis."""
    nome_base, extensao = _separar_nome(nome)
    if not isinstance(conteudo, str):
        raise ValueError("O conteúdo precisa ser texto.")
    dados = conteudo.encode("utf-8")
    configuracao = carregar_configuracao()
    identificador_hash = hashlib.sha256(nome_base.casefold().encode("utf-8")).hexdigest()[:8]
    if len(dados) > configuracao.arquivo_limite_bytes:
        raise ValueError(
            f"O arquivo ultrapassa o limite de {configuracao.arquivo_limite_bytes} bytes."
        )

    try:
        pasta = resolver_pasta_absoluta(configuracao.pasta_arquivos, criar=True)
        destino = resolver_arquivo_confinado(pasta, f"{nome_base}{extensao}")
    except (OSError, ValueError) as erro:
        log.warning(
            "ferramenta=criar_arquivo operacao=validacao falha=%s bytes=%d id=%s",
            type(erro).__name__, len(dados), identificador_hash,
        )
        raise ValueError(str(erro)) from None

    with _LOCK_COTA:
        if any(
            item.name.casefold() == destino.name.casefold()
            for item in pasta.iterdir()
        ):
            raise ValueError("Esse arquivo já existe; nenhum arquivo foi sobrescrito.")
        quantidade, bytes_atuais = _medir_uso(pasta)
        if quantidade >= configuracao.arquivos_limite_arquivos:
            raise ValueError(
                f"A pasta atingiu o limite de {configuracao.arquivos_limite_arquivos} arquivos."
            )
        if bytes_atuais + len(dados) > configuracao.arquivos_limite_bytes:
            raise ValueError(
                f"A pasta atingiria o limite total de {configuracao.arquivos_limite_bytes} bytes."
            )
        _gravar_atomicamente(destino, dados, len(dados), identificador_hash)

    log.info(
        "ferramenta=criar_arquivo operacao=criar bytes=%d id=%s",
        len(dados), identificador_hash,
    )
    return f"Criei o arquivo {destino.name}."


def _separar_nome(nome: str) -> tuple[str, str]:
    if not isinstance(nome, str):
        raise ValueError("Informe o nome do arquivo.")
    valor = nome.strip()
    sufixo = Path(valor).suffix.lower()
    if not sufixo:
        sufixo = ".md"
    if sufixo not in _EXTENSOES_PERMITIDAS:
        raise ValueError("A extensão precisa ser .md ou .txt.")
    base = valor[:-len(sufixo)] if valor.lower().endswith(sufixo) else valor
    return validar_nome_simples(base), sufixo


def _medir_uso(pasta: Path) -> tuple[int, int]:
    quantidade = 0
    total = 0
    pendentes = [pasta]
    while pendentes:
        atual = pendentes.pop()
        for item in atual.iterdir():
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise ValueError("Links simbólicos ou junctions não podem ficar na pasta de arquivos.")
            if item.is_dir():
                pendentes.append(item)
            elif item.is_file():
                quantidade += 1
                try:
                    total += item.stat(follow_symlinks=False).st_size
                except OSError:
                    raise ValueError("Não foi possível verificar o tamanho dos arquivos existentes.") from None
    return quantidade, total


def _gravar_atomicamente(
    destino: Path, dados: bytes, tamanho: int, identificador_hash: str
) -> None:
    temporario: Path | None = None
    try:
        descritor, nome_temporario = tempfile.mkstemp(
            prefix=".alfred-", suffix=".tmp", dir=destino.parent
        )
        temporario = Path(nome_temporario)
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        # Hard-link cria o destino atomicamente e falha se outro processo
        # tiver criado o mesmo nome; o conteúdo temporário já está completo.
        os.link(temporario, destino)
    except FileExistsError:
        raise ValueError("Esse arquivo já existe; nenhum arquivo foi sobrescrito.") from None
    except OSError as erro:
        log.warning(
            "ferramenta=criar_arquivo operacao=gravar falha=%s bytes=%d id=%s",
            type(erro).__name__, tamanho, identificador_hash,
        )
        raise ValueError("Não foi possível gravar o arquivo atomicamente.") from None
    finally:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                log.error(
                    "ferramenta=criar_arquivo operacao=limpar_temporario falha=OSError id=%s",
                    identificador_hash,
                )
