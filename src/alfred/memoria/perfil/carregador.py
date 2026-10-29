"""Leitura e validação segura dos documentos de perfil do Alfred."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

NOMES = ("fatores_estaveis", "conhecimento_abrangente", "preferencias")
ARQUIVOS = {
    "fatores_estaveis": "Keven — Fatores estáveis.md",
    "conhecimento_abrangente": "Keven Conhecimento abrangente.md",
    "preferencias": "preferencias_ALFRED.md",
}
CAMPOS_OBRIGATORIOS = {"nome", "versao", "atualizado"}
LIMITE_PALAVRAS = {"fatores_estaveis": 500, "preferencias": 700}


class ErroDePerfil(Exception):
    """Perfil ausente, malformado ou inválido."""


@dataclass(frozen=True)
class DocumentoPerfil:
    nome: str
    versao: int
    atualizado: date
    corpo: str
    sha256: str


@dataclass(frozen=True)
class Perfil:
    fatores_estaveis: DocumentoPerfil
    conhecimento_abrangente: DocumentoPerfil
    preferencias: DocumentoPerfil

    def recarregar_se_mudou(self, pasta: Path) -> Perfil:
        """Devolve este perfil se os hashes forem iguais; caso contrário, recarrega tudo."""
        mudou = any(
            getattr(self, nome).sha256
            != hashlib.sha256(_ler_bytes(pasta / ARQUIVOS[nome])).hexdigest()
            for nome in NOMES
        )
        if not mudou:
            return self
        return carregar_perfil(pasta)


def _ler_bytes(caminho: Path) -> bytes:
    # Na fase 8, esta função passa a verificar assinatura e decifrar em memória.
    if caminho.is_symlink():
        raise ErroDePerfil(f"{caminho.name}: links simbólicos não são permitidos")
    try:
        return caminho.read_bytes()
    except FileNotFoundError:
        raise ErroDePerfil(f"{caminho.name}: arquivo não encontrado") from None
    except OSError as erro:
        raise ErroDePerfil(f"{caminho.name}: não foi possível ler o arquivo ({erro.strerror})") from erro


def _separar(texto: str, nome: str) -> tuple[dict[str, Any], str]:
    if not texto.startswith("---"):
        raise ErroDePerfil(f"{nome}: cabeçalho ausente")
    partes = texto.split("---", 2)
    if len(partes) < 3:
        raise ErroDePerfil(f"{nome}: cabeçalho não foi fechado com ---")
    try:
        cabecalho = yaml.safe_load(partes[1])
    except yaml.YAMLError:
        # Mensagens do parser podem incluir trechos do cabeçalho, que é dado privado.
        raise ErroDePerfil(f"{nome}: cabeçalho YAML inválido") from None
    if not isinstance(cabecalho, dict):
        raise ErroDePerfil(f"{nome}: cabeçalho deve ser um mapa chave: valor")
    return cabecalho, partes[2].strip()


def _validar(cabecalho: dict[str, Any], corpo: str, nome: str) -> None:
    faltando = CAMPOS_OBRIGATORIOS - cabecalho.keys()
    if faltando:
        raise ErroDePerfil(f"{nome}: campos obrigatórios ausentes {sorted(faltando)}")
    if cabecalho["nome"] != nome:
        raise ErroDePerfil(f"{nome}: o campo 'nome' deve ser igual ao nome do arquivo")
    # bool é subclasse de int em Python, mas não é uma versão válida.
    if isinstance(cabecalho["versao"], bool) or not isinstance(cabecalho["versao"], int):
        raise ErroDePerfil(f"{nome}: 'versao' deve ser inteiro")
    if type(cabecalho["atualizado"]) is not date:
        raise ErroDePerfil(f"{nome}: 'atualizado' deve ser uma data (AAAA-MM-DD)")
    limite = LIMITE_PALAVRAS.get(nome)
    palavras = len(corpo.split())
    if limite is not None and palavras > limite:
        log.warning("%s: %d palavras (limite %d)", nome, palavras, limite)


def carregar_documento(pasta: Path, nome: str) -> DocumentoPerfil:
    if nome not in NOMES:
        raise ErroDePerfil(f"{nome}: nome de perfil desconhecido")
    bruto = _ler_bytes(pasta / ARQUIVOS[nome])
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError as erro:
        raise ErroDePerfil(f"{nome}: o arquivo não está em UTF-8") from erro
    cabecalho, corpo = _separar(texto, nome)
    _validar(cabecalho, corpo, nome)
    documento = DocumentoPerfil(
        nome=nome,
        versao=cabecalho["versao"],
        atualizado=cabecalho["atualizado"],
        corpo=corpo,
        sha256=hashlib.sha256(bruto).hexdigest(),
    )
    log.info("Perfil %s v%d carregado (%d palavras)", nome, documento.versao, len(corpo.split()))
    return documento


def carregar_perfil(pasta: Path) -> Perfil:
    documentos = {nome: carregar_documento(pasta, nome) for nome in NOMES}
    return Perfil(**documentos)
