"""Comandos operacionais locais para os armazenamentos do Alfred.

Execute com ``python -m alfred.interfaces.cli.armazenamento --help``.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Sequence

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.metricas import ArmazenamentoDeMetricas
from alfred.memoria.armazenamento.migracao import aplicar_migracoes
from alfred.seguranca.auditoria.registro import RegistroDeAuditoria
from alfred.seguranca.chaves.derivacao import derivar_subchave
from alfred.seguranca.chaves.provedores import (
    ChaveMestraAusente,
    CredencialKeyringAusente,
    ProvedorDeKeyring,
    ProvedorInterativo,
    resolver_provedor_de_chave,
)


def _caminhos(raiz: Path) -> dict[str, Path]:
    return {
        "principal": raiz / "alfred.db",
        "auditoria": raiz / "auditoria.db",
        "metricas": raiz / "metricas.db",
        "ancora": raiz / "auditoria.ancora",
    }


def _obter_chave() -> bytes:
    return resolver_provedor_de_chave().obter_chave_mestra()


def _criar(raiz: Path, chave: bytes) -> int:
    raiz.mkdir(parents=True, exist_ok=True)
    caminhos = _caminhos(raiz)
    principal = aplicar_migracoes(
        caminhos["principal"], derivar_subchave(chave, "alfred.db")
    )
    aplicar_migracoes(
        caminhos["metricas"],
        derivar_subchave(chave, "metricas.db"),
        pasta_migracoes=Path(__file__).parents[2]
        / "memoria"
        / "armazenamento"
        / "migracoes_metricas",
        finalidade="metricas",
    )
    auditoria = RegistroDeAuditoria(
        caminhos["auditoria"], caminhos["ancora"], chave
    )
    if not auditoria.verificar_cadeia().valida:
        raise RuntimeError("Não foi possível inicializar a auditoria local")
    return principal


def _configurar_chave(raiz: Path) -> str:
    """Provisiona uma chave no cofre do sistema sem imprimi-la."""
    principal = _caminhos(raiz)["principal"]
    cofre = ProvedorDeKeyring()
    try:
        chave = cofre.obter_chave_mestra()
    except CredencialKeyringAusente:
        if principal.exists():
            raise ChaveMestraAusente(
                "Já existe alfred.db, mas não há chave no cofre; não gere outra chave"
            ) from None
        chave = secrets.token_bytes(32)
        cofre.guardar_chave_mestra(chave)

    if principal.exists():
        # Valida a chave sem alterar banco existente.
        BancoRelacional(principal, chave).contagens()
        return "Chave existente validada no cofre do sistema."

    _criar(raiz, chave)
    return "Chave criada no cofre do Windows e bancos locais inicializados."


def _restaurar_chave(raiz: Path) -> str:
    """Importa ao cofre a chave original somente após validar o banco existente."""
    principal = _caminhos(raiz)["principal"]
    if not principal.is_file():
        raise ChaveMestraAusente(
            "Não existe alfred.db para validar; use configurar-chave em uma instalação nova"
        )

    chave = ProvedorInterativo().obter_chave_mestra()
    try:
        BancoRelacional(principal, chave).contagens()
    except Exception:
        raise ChaveMestraAusente(
            "A chave não abriu o banco existente; o cofre não foi alterado"
        ) from None

    ProvedorDeKeyring().guardar_chave_mestra(chave)
    return "Chave validada no banco existente e guardada no cofre do Windows."


def _status(raiz: Path, chave: bytes | None) -> dict[str, str]:
    caminhos = _caminhos(raiz)
    resultado = {nome: ("presente" if caminho.is_file() else "ausente") for nome, caminho in caminhos.items()}
    if chave is not None and caminhos["principal"].is_file():
        contagens = BancoRelacional(caminhos["principal"], chave).contagens()
        resultado["registros"] = str(sum(contagens.values()))
    resultado["chroma"] = "presente" if (raiz / "chroma").is_dir() else "ausente"
    return resultado


def _verificar(raiz: Path, chave: bytes) -> bool:
    caminhos = _caminhos(raiz)
    sucesso = True
    for nome, rotulo in (("principal", "alfred.db"), ("metricas", "metricas.db")):
        caminho = caminhos[nome]
        if not caminho.is_file():
            print(f"{rotulo}: ausente")
            sucesso = False
            continue
        try:
            with abrir_conexao(
                caminho,
                derivar_subchave(chave, rotulo),
                finalidade="metricas" if nome == "metricas" else "dados",
                escritor=False,
            ) as conexao:
                ok = conexao.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            print(f"{rotulo}: {'válido' if ok else 'inconsistente'}")
            sucesso &= ok
        except Exception:
            print(f"{rotulo}: não foi possível verificar")
            sucesso = False
    auditoria = RegistroDeAuditoria(caminhos["auditoria"], caminhos["ancora"], chave)
    if not caminhos["auditoria"].is_file():
        print("auditoria: ausente")
        return False
    resultado = auditoria.verificar_cadeia()
    print(f"auditoria: {'válida' if resultado.valida else 'inconsistente'}")
    sucesso &= resultado.valida
    return sucesso


def _backup(raiz: Path, destino: Path, chave: bytes) -> int:
    raiz_resolvida = raiz.resolve()
    destino_resolvido = destino.resolve()
    if destino_resolvido == raiz_resolvida or raiz_resolvida in destino_resolvido.parents:
        raise ValueError("O destino do backup não pode ficar dentro da origem")
    caminhos = _caminhos(raiz)
    destino.mkdir(parents=True, exist_ok=True)
    copiados = 0
    for nome, rotulo in (("principal", "alfred.db"), ("auditoria", "auditoria.db"), ("metricas", "metricas.db")):
        origem = caminhos[nome]
        if not origem.is_file():
            continue
        saida = destino / rotulo
        if saida.exists():
            raise FileExistsError("O destino já contém um arquivo de backup")
        with abrir_conexao(
            origem,
            derivar_subchave(chave, rotulo),
            finalidade="auditoria" if nome == "auditoria" else "metricas" if nome == "metricas" else "dados",
            escritor=False,
        ) as conexao:
            conexao.execute("VACUUM INTO ?", (str(saida),))
        copiados += 1
    ancora = caminhos["ancora"]
    if ancora.is_file():
        shutil.copy2(ancora, destino / ancora.name)
    chroma = raiz / "chroma"
    if chroma.is_dir():
        shutil.copytree(chroma, destino / "chroma", dirs_exist_ok=False)
    if copiados == 0:
        raise FileNotFoundError("Nenhum banco local disponível para backup")
    return copiados


def _limpar_metricas(raiz: Path, chave: bytes, retencao_dias: int) -> dict[str, int]:
    caminho = _caminhos(raiz)["metricas"]
    if not caminho.is_file():
        raise FileNotFoundError("Banco de métricas ausente; execute criar primeiro")
    aplicar_migracoes(
        caminho,
        derivar_subchave(chave, "metricas.db"),
        pasta_migracoes=Path(__file__).parents[2]
        / "memoria"
        / "armazenamento"
        / "migracoes_metricas",
        finalidade="metricas",
    )
    return ArmazenamentoDeMetricas(
        caminho, chave, retencao_dias=retencao_dias
    ).limpar_expiradas()


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operações locais dos bancos cifrados do Alfred")
    parser.add_argument(
        "--diretorio",
        type=Path,
        default=Path(os.getenv("ALFRED_DIRETORIO_BANCOS", "dados/bancos")),
        help="diretório dos armazenamentos (padrão: ALFRED_DIRETORIO_BANCOS ou dados/bancos)",
    )
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("gerar-chave", help="gera uma chave-mestra base64; não a salva")
    sub.add_parser(
        "configurar-chave",
        help="gera e guarda a chave no cofre do Windows e inicializa os bancos",
    )
    sub.add_parser(
        "restaurar-chave",
        help="valida a chave original do banco e guarda-a no cofre do Windows",
    )
    sub.add_parser("criar", help="cria bancos cifrados e aplica migrações")
    sub.add_parser("status", help="mostra presença e contagens agregadas")
    sub.add_parser("verificar", help="verifica integridade e cadeia de auditoria")
    backup = sub.add_parser("backup", help="cria cópia cifrada dos bancos existentes")
    backup.add_argument("destino", type=Path)
    sub.add_parser("reindexar", help="reconstrói índice vetorial usando Ollama local")
    limpar = sub.add_parser("limpar-metricas", help="remove métricas fora da retenção")
    limpar.add_argument("--retencao-dias", type=int, default=90)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = construir_parser()
    argumentos = parser.parse_args(argv)
    if argumentos.comando == "gerar-chave":
        print(base64.b64encode(secrets.token_bytes(32)).decode("ascii"))
        return 0
    raiz = argumentos.diretorio
    if argumentos.comando == "configurar-chave":
        try:
            print(_configurar_chave(raiz))
            return 0
        except ChaveMestraAusente as erro:
            print(str(erro), file=sys.stderr)
            return 2
        except Exception:
            print(
                "Não foi possível configurar a chave no cofre; nenhum segredo foi exibido.",
                file=sys.stderr,
            )
            return 1
    if argumentos.comando == "restaurar-chave":
        if not sys.stdin.isatty():
            print(
                "Execute restaurar-chave em um terminal interativo para digitar a chave sem exibi-la.",
                file=sys.stderr,
            )
            return 2
        try:
            print(_restaurar_chave(raiz))
            return 0
        except ChaveMestraAusente as erro:
            print(str(erro), file=sys.stderr)
            return 2
        except Exception:
            print(
                "A chave foi validada, mas não foi possível gravá-la no cofre do Windows.",
                file=sys.stderr,
            )
            return 1
    if argumentos.comando == "status" and not any(
        caminho.exists() for caminho in _caminhos(raiz).values()
    ):
        for nome, estado in _status(raiz, None).items():
            print(f"{nome}: {estado}")
        return 0
    try:
        chave = _obter_chave()
        if argumentos.comando == "criar":
            versao = _criar(raiz, chave)
            print(f"bancos locais prontos; esquema principal versão {versao}")
        elif argumentos.comando == "status":
            for nome, estado in _status(raiz, chave).items():
                print(f"{nome}: {estado}")
        elif argumentos.comando == "verificar":
            return 0 if _verificar(raiz, chave) else 1
        elif argumentos.comando == "backup":
            total = _backup(raiz, argumentos.destino, chave)
            print(f"backup local cifrado concluído; bancos: {total}")
        elif argumentos.comando == "limpar-metricas":
            removidas = _limpar_metricas(raiz, chave, argumentos.retencao_dias)
            print(
                "métricas expiradas removidas; "
                f"linhas: {sum(removidas.values())}"
            )
        elif argumentos.comando == "reindexar":
            from alfred.memoria.armazenamento.reindexacao import reindexar_memorias

            total = reindexar_memorias(raiz, chave)
            print(f"reindexação concluída; itens processados: {total}")
        return 0
    except ChaveMestraAusente as erro:
        print(str(erro), file=sys.stderr)
        return 2
    except Exception:
        print("Operação local não concluída; confira estado e permissões sem expor dados.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
