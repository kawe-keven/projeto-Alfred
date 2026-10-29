"""Reconstrói o índice vetorial usando somente Ollama local e vetores explícitos."""

from __future__ import annotations

import os
from pathlib import Path

from alfred.memoria.armazenamento.banco_relacional import BancoRelacional
from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.embeddings import GeradorEmbeddingsOllama
from alfred.seguranca.chaves.derivacao import derivar_subchave


_MODELO_PADRAO = "qwen3-embedding:0.6b"


def reindexar_memorias(raiz: str | Path, chave_mestra: bytes) -> int:
    """Calcula embeddings no Ollama local e grava no contrato vetorial sem texto."""

    from alfred.memoria.armazenamento.vetorial_chroma import (
        ErroRepositorioVetorial,
        RepositorioVetorialChroma,
    )

    raiz = Path(raiz)
    caminho_db = raiz / "alfred.db"
    if not caminho_db.is_file():
        raise FileNotFoundError("Banco principal ausente; execute criar primeiro")
    chave_db = derivar_subchave(chave_mestra, "alfred.db")
    with abrir_conexao(caminho_db, chave_db, escritor=False) as conexao:
        eventos = conexao.execute(
            "SELECT id, tipo, texto, criado_em, importancia, estado FROM eventos "
            "WHERE texto IS NOT NULL AND estado != 'arquivada' ORDER BY criado_em, id"
        ).fetchall()
        resumos = conexao.execute(
            "SELECT id, texto, gerado_em FROM resumos ORDER BY gerado_em, id"
        ).fetchall()
        meta = {
            str(linha["chave"]): str(linha["valor"])
            for linha in conexao.execute(
                "SELECT chave, valor FROM meta WHERE chave IN "
                "('modelo_embeddings','dimensao_embeddings')"
            ).fetchall()
        }

    itens: list[tuple[str, str, str, dict[str, str | int]]] = []
    colecao_por_tipo = {
        "conversa": "conversas",
        "nota": "memorias",
        "memoria": "memorias",
        "conhecimento": "conhecimento",
    }
    for linha in eventos:
        colecao = colecao_por_tipo[str(linha["tipo"])]
        itens.append(
            (
                colecao,
                str(linha["id"]),
                str(linha["texto"]),
                {
                    "tipo": str(linha["tipo"]),
                    "data": int(linha["criado_em"]),
                    "importancia": int(linha["importancia"]),
                    "estado": str(linha["estado"]),
                },
            )
        )
    for linha in resumos:
        itens.append(
            (
                "resumos",
                str(linha["id"]),
                str(linha["texto"]),
                {
                    "tipo": "resumo",
                    "data": int(linha["gerado_em"]),
                    "importancia": 50,
                    "estado": "ativa",
                },
            )
        )
    if not itens:
        return 0

    modelo = os.environ.get("ALFRED_MODELO_EMBEDDINGS", _MODELO_PADRAO)
    gerador = GeradorEmbeddingsOllama(modelo=modelo)
    vetores = gerador.gerar_em_lote([item[2] for item in itens], "documento")
    dimensao = len(vetores[0])
    indice = raiz / "chroma"
    staging = raiz / "chroma.reindexando"
    anterior = raiz / "chroma.anterior"
    modelo_existente = meta.get("modelo_embeddings", "")
    dimensao_existente = meta.get("dimensao_embeddings", "")
    reconstruir = bool(
        indice.exists()
        and (
            (modelo_existente and modelo_existente != modelo)
            or (dimensao_existente and dimensao_existente != str(dimensao))
        )
    )
    if reconstruir and anterior.exists():
        raise ErroRepositorioVetorial(
            "Já existe um índice anterior preservado; mova-o antes de reindexar"
        )
    if reconstruir and staging.exists():
        raise ErroRepositorioVetorial(
            "Há uma reconstrução interrompida; remova a pasta temporária do índice antes de repetir"
        )
    raiz.mkdir(parents=True, exist_ok=True)
    caminho_indice = staging if reconstruir else indice
    repositorio = RepositorioVetorialChroma(
        caminho_indice, modelo_embeddings=modelo, dimensao=dimensao
    )
    banco = BancoRelacional(caminho_db, chave_mestra)

    def marcar_resumo_indexado(id_resumo: str, indexado: bool) -> bool:
        with abrir_conexao(caminho_db, chave_db) as conexao:
            cursor = conexao.execute(
                "UPDATE resumos SET indexado=? WHERE id=?",
                (int(indexado), id_resumo),
            )
            conexao.commit()
            return cursor.rowcount == 1

    try:
        for (colecao, identificador, _texto, metadados), vetor in zip(
            itens, vetores, strict=True
        ):
            if repositorio.existe(colecao, identificador):
                repositorio.remover(colecao, [identificador])
            repositorio.adicionar(
                colecao,
                identificador,
                vetor,
                metadados,  # type: ignore[arg-type]
                modelo_embeddings=modelo,
            )

        for tabela, colecao in (("eventos", None), ("resumos", "resumos")):
            if tabela == "eventos":
                ids_sqlite: dict[str, list[str]] = {
                    nome: [item[1] for item in itens if item[0] == nome]
                    for nome in ("memorias", "conversas", "conhecimento")
                }
            else:
                ids_sqlite = {"resumos": [item[1] for item in itens if item[0] == colecao]}
            for nome, ids in ids_sqlite.items():
                ids_indexados = [
                    identificador
                    for identificador in ids
                    if repositorio.existe(nome, identificador)
                ]
                repositorio.reconciliar(
                    nome,
                    ids,
                    ids_indexados,
                    (lambda identificador, indexado: None)
                    if reconstruir
                    else marcar_resumo_indexado
                    if nome == "resumos"
                    else banco.marcar_indexado,
                )
        repositorio.close()
        if reconstruir:
            indice_anterior_criado = False
            if indice.exists():
                indice.rename(anterior)
                indice_anterior_criado = True
            try:
                staging.rename(indice)
            except OSError:
                if indice_anterior_criado and not indice.exists():
                    anterior.rename(indice)
                raise
        with abrir_conexao(caminho_db, chave_db) as conexao:
            conexao.execute("UPDATE eventos SET indexado=0")
            conexao.execute("UPDATE resumos SET indexado=0")
            conexao.execute(
                "UPDATE meta SET valor=? WHERE chave='modelo_embeddings'", (modelo,)
            )
            conexao.execute(
                "UPDATE meta SET valor=? WHERE chave='dimensao_embeddings'",
                (str(dimensao),),
            )
            conexao.commit()
        for colecao, identificador, _texto, _metadados in itens:
            if colecao == "resumos":
                marcar_resumo_indexado(identificador, True)
            else:
                banco.marcar_indexado(identificador, True)
        return len(itens)
    finally:
        repositorio.close()
