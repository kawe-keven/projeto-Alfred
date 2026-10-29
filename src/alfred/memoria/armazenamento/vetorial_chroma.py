"""Implementação Chroma com embeddings pré-calculados e metadados mínimos."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path

import numpy as np

from alfred.memoria.armazenamento.repositorio_vetorial import (
    ColecaoVetorial,
    MetadadosVetoriais,
    ResultadoReconciliacao,
)
from alfred.memoria.armazenamento.compatibilidade_chroma import preparar_chromadb

preparar_chromadb()

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings


VERSAO_CHROMADB = "1.5.9"
COLECOES: tuple[ColecaoVetorial, ...] = (
    "memorias",
    "conversas",
    "conhecimento",
    "resumos",
)
_CAMPOS_META = frozenset({"tipo", "data", "importancia", "estado"})
_FILTROS_META = frozenset({"tipo", "data", "importancia", "estado"})
_TIPOS_POR_COLECAO = {
    "memorias": frozenset({"memoria", "nota"}),
    "conversas": frozenset({"conversa"}),
    "conhecimento": frozenset({"conhecimento"}),
    "resumos": frozenset({"resumo"}),
}
_ESTADOS = frozenset({"ativa", "resumida", "arquivada"})
_ID_PERMITIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODELO_PERMITIDO = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")


class ErroRepositorioVetorial(RuntimeError):
    """Erro seguro do repositório, sem refletir valores de entrada."""


class RepositorioVetorialChroma:
    """Cliente persistente Chroma; nunca recebe texto nem baixa embeddings."""

    def __init__(
        self,
        caminho: str | Path,
        *,
        modelo_embeddings: str,
        dimensao: int,
    ) -> None:
        if version("chromadb") != VERSAO_CHROMADB:
            raise ErroRepositorioVetorial(
                "Versão incompatível do ChromaDB; instale a versão fixada no extra memoria"
            )
        if not isinstance(modelo_embeddings, str) or not _MODELO_PERMITIDO.fullmatch(modelo_embeddings):
            raise ValueError("O nome do modelo de embeddings é obrigatório")
        if isinstance(dimensao, bool) or not isinstance(dimensao, int) or dimensao < 1:
            raise ValueError("A dimensão de embeddings deve ser positiva")
        self.modelo_embeddings = modelo_embeddings
        self.dimensao = dimensao
        try:
            preparar_chromadb()
            self._cliente = chromadb.PersistentClient(
                path=str(caminho),
                settings=Settings(anonymized_telemetry=False),
            )
            self._fechado = False
            self._colecoes: dict[ColecaoVetorial, Collection] = {}
            for nome in COLECOES:
                colecao = self._cliente.get_or_create_collection(
                    name=nome,
                    metadata={
                        "hnsw:space": "cosine",
                        "modelo_embeddings": modelo_embeddings,
                        "dimensao_embeddings": dimensao,
                    },
                    embedding_function=None,
                )
                metadados = colecao.metadata or {}
                if (
                    metadados.get("modelo_embeddings") != modelo_embeddings
                    or metadados.get("dimensao_embeddings") != dimensao
                    or metadados.get("hnsw:space") != "cosine"
                ):
                    raise ErroRepositorioVetorial(
                        "Coleção com modelo ou dimensão incompatível; execute reindexar"
                    )
                self._colecoes[nome] = colecao
        except ErroRepositorioVetorial:
            self.close()
            raise
        except Exception:
            self.close()
            raise ErroRepositorioVetorial(
                "Não foi possível abrir o armazenamento vetorial local"
            ) from None

    def _validar_colecao(self, colecao: str) -> Collection:
        try:
            return self._colecoes[colecao]  # type: ignore[index]
        except (KeyError, TypeError):
            raise ErroRepositorioVetorial("Coleção vetorial desconhecida") from None

    def _validar_modelo(self, modelo: str) -> None:
        if modelo != self.modelo_embeddings:
            raise ErroRepositorioVetorial(
                "Modelo de embeddings incompatível; execute reindexar"
            )

    def _validar_vetor(self, vetor: Sequence[float]) -> list[float]:
        if len(vetor) != self.dimensao:
            raise ErroRepositorioVetorial(
                "Dimensão do vetor incompatível; execute reindexar"
            )
        if any(
            isinstance(valor, bool)
            or not isinstance(valor, (int, float))
            or not math.isfinite(valor)
            for valor in vetor
        ):
            raise ErroRepositorioVetorial("Vetor inválido")
        return [float(valor) for valor in vetor]

    @staticmethod
    def _validar_id(identificador: str) -> None:
        if not isinstance(identificador, str) or not _ID_PERMITIDO.fullmatch(identificador):
            raise ErroRepositorioVetorial("Identificador vetorial inválido")

    @staticmethod
    def _validar_metadados(
        colecao: ColecaoVetorial, metadados: Mapping[str, object]
    ) -> dict[str, str | int]:
        if set(metadados) != _CAMPOS_META:
            raise ErroRepositorioVetorial("Metadados vetoriais inválidos")
        tipo = metadados["tipo"]
        data = metadados["data"]
        importancia = metadados["importancia"]
        estado = metadados["estado"]
        if not isinstance(tipo, str) or tipo not in _TIPOS_POR_COLECAO[colecao]:
            raise ErroRepositorioVetorial("Tipo de metadado incompatível com a coleção")
        if isinstance(data, bool) or not isinstance(data, int) or data < 0:
            raise ErroRepositorioVetorial("Data de metadado inválida")
        if (
            isinstance(importancia, bool)
            or not isinstance(importancia, int)
            or not 0 <= importancia <= 100
        ):
            raise ErroRepositorioVetorial("Importância de metadado inválida")
        if not isinstance(estado, str) or estado not in _ESTADOS:
            raise ErroRepositorioVetorial("Estado de metadado inválido")
        return {
            "tipo": tipo,
            "data": data,
            "importancia": importancia,
            "estado": estado,
        }

    @staticmethod
    def _validar_filtros(filtros: Mapping[str, str | int] | None) -> dict[str, object] | None:
        if filtros is None:
            return None
        if not filtros or not set(filtros).issubset(_FILTROS_META):
            raise ErroRepositorioVetorial("Filtros vetoriais inválidos")
        for chave, valor in filtros.items():
            if chave == "tipo" and (
                not isinstance(valor, str)
                or valor not in {"conversa", "nota", "memoria", "conhecimento", "resumo"}
            ):
                raise ErroRepositorioVetorial("Filtro vetorial inválido")
            if chave == "estado" and (not isinstance(valor, str) or valor not in _ESTADOS):
                raise ErroRepositorioVetorial("Filtro vetorial inválido")
            if chave == "data" and (
                isinstance(valor, bool) or not isinstance(valor, int) or valor < 0
            ):
                raise ErroRepositorioVetorial("Filtro vetorial inválido")
            if chave == "importancia" and (
                isinstance(valor, bool)
                or not isinstance(valor, int)
                or not 0 <= valor <= 100
            ):
                raise ErroRepositorioVetorial("Filtro vetorial inválido")
        # Chroma requires exactly one operator at each mapping level.
        # Conjoin individual metadata predicates with its explicit $and form.
        if len(filtros) == 1:
            chave, valor = next(iter(filtros.items()))
            return {chave: valor}
        return {"$and": [{chave: valor} for chave, valor in filtros.items()]}

    def adicionar(
        self,
        colecao: ColecaoVetorial,
        id_vetor: str,
        vetor: Sequence[float],
        metadados: MetadadosVetoriais,
        *,
        modelo_embeddings: str,
    ) -> None:
        self._validar_modelo(modelo_embeddings)
        self._validar_id(id_vetor)
        item = self._validar_metadados(colecao, metadados)
        vetor_validado = self._validar_vetor(vetor)
        self._validar_colecao(colecao).add(
            ids=[id_vetor], embeddings=[vetor_validado], metadatas=[item]
        )

    def buscar(
        self,
        colecao: ColecaoVetorial,
        vetor: Sequence[float],
        k: int = 10,
        filtros: Mapping[str, str | int] | None = None,
        *,
        modelo_embeddings: str,
    ) -> list[str]:
        return [
            identificador
            for identificador, _distancia in self.buscar_com_distancias(
                colecao, vetor, k, filtros, modelo_embeddings=modelo_embeddings
            )
        ]

    def buscar_com_distancias(
        self,
        colecao: ColecaoVetorial,
        vetor: Sequence[float],
        k: int = 10,
        filtros: Mapping[str, str | int] | None = None,
        *,
        modelo_embeddings: str,
    ) -> list[tuple[str, float]]:
        """Retorna IDs e distâncias cosine para permitir limiar de relevância."""
        self._validar_modelo(modelo_embeddings)
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k deve ser um inteiro positivo")
        argumentos: dict[str, object] = {
            "query_embeddings": [self._validar_vetor(vetor)],
            "n_results": k,
            "include": ["distances"],
        }
        where = self._validar_filtros(filtros)
        if where is not None:
            argumentos["where"] = where
        resultado = self._validar_colecao(colecao).query(**argumentos)
        ids = resultado["ids"][0]
        distancias = resultado.get("distances")
        if not ids or distancias is None or not distancias[0]:
            return []
        return [
            (str(identificador), float(distancia))
            for identificador, distancia in zip(ids, distancias[0], strict=True)
        ]

    def remover(self, colecao: ColecaoVetorial, ids: Sequence[str]) -> None:
        for identificador in ids:
            self._validar_id(identificador)
        if ids:
            self._validar_colecao(colecao).delete(ids=list(ids))

    def existe(self, colecao: ColecaoVetorial, id_vetor: str) -> bool:
        self._validar_id(id_vetor)
        resultado = self._validar_colecao(colecao).get(ids=[id_vetor], include=[])
        return bool(resultado["ids"])

    def contar(self, colecao: ColecaoVetorial) -> int:
        return int(self._validar_colecao(colecao).count())

    def listar_ids(self, colecao: ColecaoVetorial) -> list[str]:
        objeto = self._validar_colecao(colecao)
        total = objeto.count()
        resultado: list[str] = []
        tamanho_lote = 1000
        for inicio in range(0, total, tamanho_lote):
            lote = objeto.get(limit=tamanho_lote, offset=inicio, include=[])
            resultado.extend(lote["ids"])
        return resultado

    def snapshot_visualizacao(self) -> dict[str, object]:
        """Retorna todos os vetores do índice, sem texto original nem limite de amostra."""
        registros: list[dict[str, object]] = []
        vetores_por_colecao: dict[str, list[list[float]]] = {}
        ids_por_colecao: dict[str, list[str]] = {}
        totais: dict[str, int] = {}

        for nome in COLECOES:
            objeto = self._validar_colecao(nome)
            total = int(objeto.count())
            totais[nome] = total
            vetores: list[list[float]] = []
            ids: list[str] = []
            rotulos = {"memorias": "mem", "conversas": "cvs", "conhecimento": "kno", "resumos": "res"}
            for inicio in range(0, total, 1000):
                dados = objeto.get(
                    limit=min(1000, total - inicio),
                    offset=inicio,
                    include=["embeddings", "metadatas"],
                )
                embeddings = dados.get("embeddings")
                metadados = dados.get("metadatas") or []
                if embeddings is None:
                    continue
                for ident, vetor, meta in zip(dados["ids"], embeddings, metadados, strict=True):
                    if len(vetor) != self.dimensao:
                        continue
                    ids.append(str(ident))
                    vetores.append([float(valor) for valor in vetor])
                    registros.append({
                        "id": f"{rotulos[nome]}-{len(ids):05d}",
                        "colecao": nome,
                        "tipo": str((meta or {}).get("tipo", "")),
                        "data": int((meta or {}).get("data", 0)),
                        "importancia": int((meta or {}).get("importancia", 0)),
                        "estado": str((meta or {}).get("estado", "")),
                    })
            vetores_por_colecao[nome] = vetores
            ids_por_colecao[nome] = ids

        todos_vetores = [vetor for nome in COLECOES for vetor in vetores_por_colecao[nome]]
        if registros:
            matriz = np.asarray(todos_vetores, dtype=np.float32)
            indices = np.arange(1, self.dimensao + 1, dtype=np.float32)
            projecao = np.column_stack([
                np.sin(indices * (eixo + 1) * 12.9898 + eixo * 78.233)
                for eixo in range(3)
            ])
            coordenadas = (matriz @ projecao) / math.sqrt(self.dimensao)
            escala = float(np.max(np.abs(coordenadas))) or 1.0
            for registro, xyz in zip(registros, coordenadas / escala, strict=True):
                registro["xyz"] = [float(valor) for valor in xyz]

        # Consulta o índice HNSW em lotes para encontrar vizinhos próximos sem
        # comparar cada vetor a todos os outros em Python.
        indice_por_colecao_id: dict[str, dict[str, int]] = {nome: {} for nome in COLECOES}
        posicao_global = 0
        for nome in COLECOES:
            for ident in ids_por_colecao[nome]:
                indice_por_colecao_id[nome][ident] = posicao_global
                posicao_global += 1

        melhores: list[dict[int, float]] = [dict() for _ in registros]
        tamanho_lote = 256
        for origem_nome in COLECOES:
            origem_vetores = vetores_por_colecao[origem_nome]
            origem_ids = ids_por_colecao[origem_nome]
            for inicio in range(0, len(origem_vetores), tamanho_lote):
                lote = origem_vetores[inicio:inicio + tamanho_lote]
                for destino_nome in COLECOES:
                    destino = self._validar_colecao(destino_nome)
                    total_destino = totais[destino_nome]
                    if not total_destino:
                        continue
                    resultado = destino.query(
                        query_embeddings=lote,
                        n_results=min(3, total_destino),
                        include=["distances"],
                    )
                    for deslocamento, (ids_vizinhos, distancias) in enumerate(zip(
                        resultado["ids"], resultado["distances"], strict=True
                    )):
                        indice_origem = indice_por_colecao_id[origem_nome][origem_ids[inicio + deslocamento]]
                        for ident_vizinho, distancia in zip(ids_vizinhos, distancias, strict=True):
                            indice_destino = indice_por_colecao_id[destino_nome].get(str(ident_vizinho))
                            if indice_destino is None or indice_destino == indice_origem:
                                continue
                            similaridade = max(0.0, min(1.0, 1.0 - float(distancia)))
                            melhores[indice_origem][indice_destino] = max(
                                similaridade, melhores[indice_origem].get(indice_destino, 0.0)
                            )

        arestas: dict[tuple[int, int], float] = {}
        for indice, vizinhos in enumerate(melhores):
            for destino, similaridade in vizinhos.items():
                par = tuple(sorted((indice, destino)))
                arestas[par] = max(similaridade, arestas.get(par, 0.0))

        return {
            "available": True,
            "model": self.modelo_embeddings,
            "dimension": self.dimensao,
            "totals": totais,
            "nodes": registros,
            "edges": [
                {"source": origem, "target": destino, "similarity": round(similaridade, 4)}
                for (origem, destino), similaridade in arestas.items()
            ],
        }

    def reconciliar(
        self,
        colecao: ColecaoVetorial,
        ids_sqlite: Sequence[str],
        ids_indexados: Sequence[str],
        atualizar_indexado: Callable[[str, bool], object],
    ) -> ResultadoReconciliacao:
        self._validar_colecao(colecao)
        for identificador in ids_sqlite:
            self._validar_id(identificador)
        for identificador in ids_indexados:
            self._validar_id(identificador)
        sqlite_ids = set(ids_sqlite)
        indexados = set(ids_indexados)
        if not indexados.issubset(sqlite_ids):
            raise ErroRepositorioVetorial("Conjunto de IDs indexados inconsistente")
        vetoriais = set(self.listar_ids(colecao))
        orfaos = vetoriais - sqlite_ids
        if orfaos:
            self.remover(colecao, sorted(orfaos))
        faltantes = sqlite_ids - vetoriais
        corrigidos = 0
        for identificador in sorted(indexados - vetoriais):
            atualizar_indexado(identificador, False)
            corrigidos += 1
        for identificador in sorted((sqlite_ids - indexados) & vetoriais):
            atualizar_indexado(identificador, True)
            corrigidos += 1
        return ResultadoReconciliacao(
            textos_sem_vetor=len(faltantes),
            vetores_orfaos_removidos=len(orfaos),
            indexado_corrigidos=corrigidos,
        )

    def close(self) -> None:
        if getattr(self, "_fechado", False):
            return
        cliente = getattr(self, "_cliente", None)
        fechar = getattr(cliente, "close", None)
        if callable(fechar):
            fechar()
        self._fechado = True

    def __enter__(self) -> RepositorioVetorialChroma:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
