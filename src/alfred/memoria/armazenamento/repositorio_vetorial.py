"""Contrato vetorial sem texto pessoal."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict


ColecaoVetorial = Literal["memorias", "conversas", "conhecimento", "resumos"]


class MetadadosVetoriais(TypedDict):
    tipo: str
    data: int
    importancia: int
    estado: str


@dataclass(frozen=True)
class ResultadoReconciliacao:
    textos_sem_vetor: int
    vetores_orfaos_removidos: int
    indexado_corrigidos: int


class RepositorioVetorial(Protocol):
    """Operações de domínio independentes do motor vetorial."""

    def adicionar(
        self,
        colecao: ColecaoVetorial,
        id_vetor: str,
        vetor: Sequence[float],
        metadados: MetadadosVetoriais,
        *,
        modelo_embeddings: str,
    ) -> None: ...

    def buscar(
        self,
        colecao: ColecaoVetorial,
        vetor: Sequence[float],
        k: int = 10,
        filtros: Mapping[str, str | int] | None = None,
        *,
        modelo_embeddings: str,
    ) -> list[str]: ...

    def remover(self, colecao: ColecaoVetorial, ids: Sequence[str]) -> None: ...

    def existe(self, colecao: ColecaoVetorial, id_vetor: str) -> bool: ...

    def contar(self, colecao: ColecaoVetorial) -> int: ...

    def listar_ids(self, colecao: ColecaoVetorial) -> list[str]: ...

    def reconciliar(
        self,
        colecao: ColecaoVetorial,
        ids_sqlite: Sequence[str],
        ids_indexados: Sequence[str],
        atualizar_indexado: Callable[[str, bool], object],
    ) -> ResultadoReconciliacao: ...
