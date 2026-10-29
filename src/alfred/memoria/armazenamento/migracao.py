"""Aplicador simples de migrações SQL transacionais."""

from __future__ import annotations

import re
import os
from pathlib import Path

from alfred.memoria.armazenamento.conexao import abrir_conexao


class ErroMigracao(RuntimeError):
    """Falha segura de migração, sem expor SQL, dados ou caminhos."""


_PADRAO_MIGRACAO = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def _listar_migracoes(pasta: Path) -> list[tuple[int, Path]]:
    resultado: list[tuple[int, Path]] = []
    for arquivo in pasta.iterdir():
        correspondencia = _PADRAO_MIGRACAO.fullmatch(arquivo.name)
        if correspondencia and arquivo.is_file():
            resultado.append((int(correspondencia.group(1)), arquivo))
    resultado.sort(key=lambda item: item[0])
    versoes = [versao for versao, _ in resultado]
    if len(versoes) != len(set(versoes)):
        raise ErroMigracao("Há números de migração duplicados")
    return resultado


def _remover_lados(caminho: Path) -> None:
    for sufixo in ("-wal", "-shm"):
        lado = Path(f"{caminho}{sufixo}")
        if lado.exists():
            lado.unlink()


def aplicar_migracoes(
    caminho: str | Path,
    chave: bytes,
    *,
    pasta_migracoes: str | Path | None = None,
    finalidade: str = "dados",
) -> int:
    """Aplica migrações em ordem, restaurando cópia cifrada se algo falhar."""

    arquivo_db = Path(caminho)
    pasta = (
        Path(pasta_migracoes)
        if pasta_migracoes is not None
        else Path(__file__).with_name("migracoes")
    )
    try:
        migracoes = _listar_migracoes(pasta)
    except OSError:
        raise ErroMigracao("Não foi possível ler os arquivos de migração") from None
    if not migracoes:
        raise ErroMigracao("Nenhuma migração disponível")

    backup = arquivo_db.with_name(f"{arquivo_db.name}.migracao.bak")
    backup_criado = False
    versao_final = 0
    try:
        with abrir_conexao(arquivo_db, chave, finalidade=finalidade) as conexao:
            versao_atual = int(conexao.execute("PRAGMA user_version").fetchone()[0])
            versao_codigo = migracoes[-1][0]
            if versao_atual > versao_codigo:
                raise ErroMigracao("O banco foi criado por uma versão mais nova do código")
            possui_meta = conexao.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if possui_meta:
                linha_meta = conexao.execute(
                    "SELECT valor FROM meta WHERE chave=?", ("schema_version",)
                ).fetchone()
                if linha_meta is not None and int(linha_meta[0]) != versao_atual:
                    raise ErroMigracao("A versão registrada no banco é inconsistente")
            pendentes = [(v, p) for v, p in migracoes if v > versao_atual]
            if not pendentes:
                return versao_atual
            if backup.exists():
                raise ErroMigracao("Há uma cópia temporária de migração inesperada")
            conexao.execute("VACUUM INTO ?", (str(backup),))
            backup_criado = backup.exists()
            for versao, arquivo_migracao in pendentes:
                if versao != int(conexao.execute("PRAGMA user_version").fetchone()[0]) + 1:
                    raise ErroMigracao("A sequência das migrações contém uma lacuna")
                sql = arquivo_migracao.read_text(encoding="utf-8")
                conexao.execute("BEGIN IMMEDIATE")
                try:
                    for instrucao in sql.split(";"):
                        if instrucao.strip():
                            conexao.execute(instrucao)
                    if conexao.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
                    ).fetchone():
                        conexao.execute(
                            "INSERT INTO meta(chave, valor) VALUES(?, ?) "
                            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                            ("schema_version", str(versao)),
                        )
                    conexao.execute(f"PRAGMA user_version={versao}")
                    conexao.commit()
                except Exception:
                    conexao.rollback()
                    raise
                versao_final = versao
    except ErroMigracao:
        if backup_criado:
            _restaurar_backup(arquivo_db, backup)
        raise
    except Exception:
        if backup_criado:
            _restaurar_backup(arquivo_db, backup)
        raise ErroMigracao(
            "Falha ao aplicar migração; a cópia cifrada anterior foi restaurada"
        ) from None
    else:
        if backup_criado and backup.exists():
            backup.unlink()
        return versao_final


def _restaurar_backup(arquivo_db: Path, backup: Path) -> None:
    try:
        _remover_lados(arquivo_db)
        os.replace(backup, arquivo_db)
    except OSError:
        raise ErroMigracao(
            "Falha de migração e não foi possível restaurar a cópia cifrada"
        ) from None
