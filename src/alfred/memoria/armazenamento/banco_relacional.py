"""Acesso relacional tipado a textos, histórico e metadados sensíveis."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.identificadores import gerar_uuid7
from alfred.seguranca.chaves.derivacao import derivar_subchave


class BancoRelacional:
    """Operações SQL pequenas; regras de memória pertencem a outro serviço."""

    def __init__(self, caminho: str | Path, chave_mestra: bytes) -> None:
        if len(chave_mestra) != 32:
            raise ValueError("A chave-mestra deve conter exatamente 32 bytes")
        self.caminho = Path(caminho)
        self._chave_banco = derivar_subchave(chave_mestra, "alfred.db")

    def criar_sessao(
        self,
        interface: str,
        iniciada_em: int,
        modelo_llm: str | None = None,
        *,
        id_sessao: str | None = None,
    ) -> str:
        identificador = id_sessao or gerar_uuid7()
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            conexao.execute(
                "INSERT INTO sessoes(id, iniciada_em, interface, modelo_llm) "
                "VALUES(?, ?, ?, ?)",
                (identificador, iniciada_em, interface, modelo_llm),
            )
            conexao.commit()
        return identificador

    def encerrar_sessao(self, id_sessao: str, encerrada_em: int) -> bool:
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            cursor = conexao.execute(
                "UPDATE sessoes SET encerrada_em=? WHERE id=?",
                (encerrada_em, id_sessao),
            )
            conexao.commit()
            return cursor.rowcount == 1

    def inserir_evento(
        self,
        *,
        tipo: str,
        criado_em: int,
        origem: str,
        hash_texto: str,
        papel: str | None = None,
        texto: str | None = None,
        sessao_id: str | None = None,
        importancia: int = 50,
        fixada: bool = False,
        estado: str = "ativa",
        indexado: bool = False,
        id_resumo_pai: str | None = None,
        id_evento: str | None = None,
    ) -> str:
        identificador = id_evento or gerar_uuid7()
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            conexao.execute(
                "INSERT INTO eventos(id, tipo, papel, texto, criado_em, sessao_id, origem, "
                "importancia, fixada, estado, indexado, hash_texto, id_resumo_pai) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identificador,
                    tipo,
                    papel,
                    texto,
                    criado_em,
                    sessao_id,
                    origem,
                    importancia,
                    int(fixada),
                    estado,
                    int(indexado),
                    hash_texto,
                    id_resumo_pai,
                ),
            )
            conexao.commit()
        return identificador

    def marcar_indexado(self, id_evento: str, indexado: bool = True) -> bool:
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            cursor = conexao.execute(
                "UPDATE eventos SET indexado=? WHERE id=?",
                (int(indexado), id_evento),
            )
            conexao.commit()
            return cursor.rowcount == 1

    def registrar_acessos(self, ids: Iterable[str], acessado_em: int) -> int:
        """Incrementa acessos só dos eventos efetivamente usados no contexto."""
        lista_ids = list(dict.fromkeys(ids))
        if not lista_ids:
            return 0
        marcadores = ",".join("?" for _ in lista_ids)
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            cursor = conexao.execute(
                f"UPDATE eventos SET acessos=acessos+1, ultimo_acesso_em=? "
                f"WHERE id IN ({marcadores})",
                (acessado_em, *lista_ids),
            )
            conexao.commit()
            return cursor.rowcount

    def buscar_eventos_por_ids(self, ids: Iterable[str]) -> list[object]:
        lista_ids = list(ids)
        if not lista_ids:
            return []
        marcadores = ",".join("?" for _ in lista_ids)
        with abrir_conexao(
            self.caminho, self._chave_banco, escritor=False
        ) as conexao:
            return list(
                conexao.execute(
                    f"SELECT id, tipo, papel, texto, criado_em, sessao_id, origem, "
                    f"importancia, fixada, estado, indexado, hash_texto, acessos, "
                    f"ultimo_acesso_em, id_resumo_pai FROM eventos WHERE id IN ({marcadores})",
                    lista_ids,
                ).fetchall()
            )

    def buscar_eventos_por_assunto(self, consulta: str) -> list[object]:
        """Busca eventos ativos por palavras do assunto para atender pedidos de esquecimento."""
        import unicodedata

        normalizada = unicodedata.normalize("NFKD", consulta.casefold())
        normalizada = "".join(c for c in normalizada if not unicodedata.combining(c))
        termos = list(dict.fromkeys(
            t for t in re.findall(r"[a-z0-9]+", normalizada)
            if len(t) >= 3 and t not in {
                "apague", "apagar", "apaga", "exclua", "excluir", "esqueca",
                "esquecer", "remova", "remover", "dados", "informacoes",
                "informacao", "sobre", "acerca", "tudo", "todas", "todos",
                "memoria", "memorias", "por", "favor", "do", "da", "dos", "das",
            }
        ))
        if not termos:
            return []
        with abrir_conexao(self.caminho, self._chave_banco, escritor=False) as conexao:
            linhas = conexao.execute(
                "SELECT id, texto FROM eventos WHERE estado!='arquivada' AND texto IS NOT NULL"
            ).fetchall()
        pontuadas = []
        for linha in linhas:
            texto = unicodedata.normalize("NFKD", str(linha["texto"]).casefold())
            texto = "".join(c for c in texto if not unicodedata.combining(c))
            encontrados = sum(t in texto for t in termos)
            if encontrados == len(termos):
                pontuadas.append(linha)
        return pontuadas

    def buscar_conversas_recentes(self, limite: int = 12) -> list[object]:
        """Retorna as falas mais recentes de todas as sessões, sem depender do índice vetorial."""
        if not 1 <= limite <= 100:
            raise ValueError("O limite deve estar entre 1 e 100")
        with abrir_conexao(self.caminho, self._chave_banco, escritor=False) as conexao:
            linhas = conexao.execute(
                "SELECT id, papel, texto, criado_em FROM eventos "
                "WHERE tipo='conversa' AND estado='ativa' AND texto IS NOT NULL "
                "ORDER BY criado_em DESC, id DESC LIMIT ?", (limite,)
            ).fetchall()
        return list(reversed(linhas))

    def buscar_conversas_historico(self, consulta: str, limite: int = 8) -> list[object]:
        """Busca em todo o histórico cifrado por termos, sem limitar por idade ou índice."""
        import re
        import unicodedata

        if not 1 <= limite <= 50:
            raise ValueError("O limite deve estar entre 1 e 50")
        normalizada = unicodedata.normalize("NFKD", consulta.casefold())
        normalizada = "".join(c for c in normalizada if not unicodedata.combining(c))
        termos = list(dict.fromkeys(
            termo for termo in re.findall(r"[a-z0-9]+", normalizada)
            if len(termo) >= 3 and termo not in {
                "alfred", "antes", "agora", "ainda", "alguma", "algumas",
                "algum", "alguns", "como", "conversa", "conversamos",
                "conversas", "das", "dessa", "deste", "disso", "falei", "falamos",
                "historico", "minha", "meu", "nossa", "nosso", "sobre",
                "resumo", "resumos", "ultima", "ultimas", "ultimo", "ultimos",
                "recentes", "voce",
            }
        ))
        if not termos:
            return []
        with abrir_conexao(self.caminho, self._chave_banco, escritor=False) as conexao:
            linhas = conexao.execute(
                "SELECT id, papel, texto, criado_em FROM eventos "
                "WHERE tipo='conversa' AND estado='ativa' AND texto IS NOT NULL "
                "ORDER BY criado_em DESC, id DESC"
            ).fetchall()
        pontuadas = []
        for linha in linhas:
            texto = unicodedata.normalize("NFKD", str(linha["texto"]).casefold())
            texto = "".join(c for c in texto if not unicodedata.combining(c))
            correspondencias = sum(texto.count(termo) for termo in termos)
            if correspondencias:
                pontuadas.append((correspondencias, int(linha["criado_em"]), str(linha["id"]), linha))
        pontuadas.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [item[3] for item in pontuadas[:limite]]

    def contagens(self) -> dict[str, int]:
        tabelas = ("sessoes", "resumos", "eventos", "padroes", "lembretes", "avisos")
        with abrir_conexao(
            self.caminho, self._chave_banco, escritor=False
        ) as conexao:
            return {
                tabela: int(conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0])
                for tabela in tabelas
            }

    def atualizar_estado_evento(self, id_evento: str, estado: str) -> bool:
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            cursor = conexao.execute(
                "UPDATE eventos SET estado=? WHERE id=?", (estado, id_evento)
            )
            conexao.commit()
            return cursor.rowcount == 1

    def apagar_eventos(self, ids: Iterable[str]) -> int:
        lista_ids = list(ids)
        if not lista_ids:
            return 0
        marcadores = ",".join("?" for _ in lista_ids)
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            cursor = conexao.execute(
                f"DELETE FROM eventos WHERE id IN ({marcadores})", lista_ids
            )
            conexao.commit()
            return cursor.rowcount

    def registrar_ocorrencia_padrao(
        self,
        id_padrao: str,
        ocorrido_em: int,
    ) -> None:
        with abrir_conexao(self.caminho, self._chave_banco) as conexao:
            conexao.execute(
                "INSERT INTO padroes_ocorrencias(id_padrao, ocorrido_em) VALUES(?, ?)",
                (id_padrao, ocorrido_em),
            )
            conexao.execute(
                "UPDATE padroes SET ultima_em=?, ocorrencias=ocorrencias+1 WHERE id=?",
                (ocorrido_em, id_padrao),
            )
            conexao.commit()
