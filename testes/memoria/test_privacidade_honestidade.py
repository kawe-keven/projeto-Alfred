from __future__ import annotations

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.nucleo.politicas.honestidade import INSTRUCOES_HONESTIDADE
from alfred.seguranca.chaves.derivacao import derivar_subchave

import pytest


def _arquivos(raiz):
    return [arquivo for arquivo in raiz.rglob("*") if arquivo.is_file()]


def test_texto_ficticio_fica_cifrado_no_sqlcipher_incluindo_sidecars(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    sentinela = "SENTINELA_DISCO_SQLCIPHER_3917"
    armazenamento.banco.inserir_evento(
        tipo="conversa",
        criado_em=armazenamento.relogio(),
        origem="usuario",
        hash_texto="hash-sentinela-ficticia",
        texto=sentinela,
        id_evento="evento-sentinela-disco",
    )
    arquivos = _arquivos(armazenamento.raiz)
    assert armazenamento.caminho_alfred.read_bytes()[:16] != b"SQLite format 3\x00"
    assert all(sentinela.encode("utf-8") not in arquivo.read_bytes() for arquivo in arquivos)


def test_metricas_e_auditoria_guardam_metadados_sem_conteudo(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    sentinela = "SENTINELA_NAO_E_METRICA_8472"
    armazenamento.banco.inserir_evento(
        tipo="memoria",
        criado_em=armazenamento.relogio(),
        origem="usuario",
        hash_texto="hash-sentinela-metrica-auditoria",
        texto=sentinela,
        id_evento="evento-sentinela-metrica-auditoria",
    )
    armazenamento.metricas.inserir_latencia_turno(
        ts_ms=armazenamento.relogio(),
        interface="cli",
        perfil_desempenho="teste",
        modelo_llm="llm-falso-v1",
        ms_total=123,
    )
    armazenamento.auditoria.registrar(
        "memoria",
        "gravar",
        "ok",
        "alfred",
        quantidade=1,
        modo="escrita",
        componente="banco",
        origem="usuario",
    )
    assert armazenamento.auditoria.verificar_cadeia().valida
    arquivos = _arquivos(armazenamento.raiz)
    assert all(sentinela.encode("utf-8") not in arquivo.read_bytes() for arquivo in arquivos)
    chave_auditoria = derivar_subchave(
        armazenamento.chave_mestra, "auditoria.db"
    )
    with abrir_conexao(
        armazenamento.caminho_auditoria,
        chave_auditoria,
        finalidade="auditoria",
        escritor=False,
    ) as conexao:
        meta_json = str(conexao.execute("SELECT meta_json FROM auditoria").fetchone()[0])
    assert sentinela not in meta_json
    assert "quantidade" in meta_json


def test_auditoria_detecta_adulteracao_na_sequencia_correta(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    armazenamento.auditoria.registrar(
        "memoria", "indexar", "ok", "alfred", quantidade=1, componente="chroma"
    )
    assert armazenamento.auditoria.verificar_cadeia().valida
    chave_auditoria = derivar_subchave(
        armazenamento.chave_mestra, "auditoria.db"
    )
    with abrir_conexao(
        armazenamento.caminho_auditoria,
        chave_auditoria,
        finalidade="auditoria",
    ) as conexao:
        conexao.execute("DROP TRIGGER auditoria_sem_update")
        conexao.execute("UPDATE auditoria SET acao=? WHERE seq=?", ("alterado", 1))
        conexao.commit()
    resultado = armazenamento.auditoria.verificar_cadeia()
    assert not resultado.valida
    assert resultado.seq_inconsistente == 1


def test_politica_de_honestidade_esta_no_nucleo_do_prompt() -> None:
    assert "Não invente fatos, memórias, fontes, capacidades, ações ou resultados." in INSTRUCOES_HONESTIDADE
    assert "diga que não sabe" in INSTRUCOES_HONESTIDADE


def test_todas_operacoes_de_memoria_geram_auditoria_de_metadados(armazenamento_memoria, llm_falso) -> None:
    from alfred.memoria.armazenamento.ciclo import CicloMemoria
    a = armazenamento_memoria
    a.banco.inserir_evento(tipo="conversa", criado_em=10, origem="usuario", papel="usuario", texto="Prefiro respostas fictícias curtas", hash_texto="audit-src")
    ciclo = CicloMemoria(a.banco, a.relogio, llm=llm_falso, auditoria=a.auditoria)
    ciclo.extrair_fatos()
    ciclo.resumir_periodo("dia", 0, 20)
    ident, proposto = ciclo.registrar_padrao("Preferência fictícia curta", "evidencia-1")
    a.relogio.avancar(1)
    _, proposto = ciclo.registrar_padrao("Preferência fictícia curta", "evidencia-2")
    if proposto:
        ciclo.decidir_padrao(ident, confirmar=True)
    ciclo.ciclo_vida(idade_resumida_ms=1, idade_arquivada_ms=1)
    assert a.auditoria.verificar_cadeia().valida
    chave = derivar_subchave(a.chave_mestra, "auditoria.db")
    with abrir_conexao(a.caminho_auditoria, chave, finalidade="auditoria", escritor=False) as db:
        linhas = db.execute("SELECT acao,meta_json FROM auditoria").fetchall()
    assert {r["acao"] for r in linhas} >= {"extrair_fatos", "resumir_periodo", "registrar_padrao", "ciclo_vida"}
    assert all("Preferência fictícia curta" not in r["meta_json"] for r in linhas)


def test_memoria_vazia_insere_marcador_e_impede_alegacao_de_lembranca(llm_falso, tmp_path) -> None:
    from types import SimpleNamespace
    from alfred.interfaces.cli.app import SessaoConversa
    from alfred.ferramentas.registro import RegistroDeFerramentas
    class Provedor:
        def conversar(self, mensagens, *, sistema):
            self.sistema = sistema
            yield "Não encontrei essa informação."
    provedor = Provedor()
    sessao = object.__new__(SessaoConversa)
    sessao.provedor = provedor
    sessao.configuracao = SimpleNamespace(pasta_pessoas=tmp_path, pessoas_limite_total=3, pessoa_limite_palavras=100, janela_mensagens=5)
    sessao.perfil = SimpleNamespace(fatores_estaveis=SimpleNamespace(corpo=""), conhecimento_abrangente=SimpleNamespace(corpo=""))
    sessao.prompt_sistema = "Política fictícia"
    sessao.historico = []
    sessao.registro_ferramentas = RegistroDeFerramentas()
    sessao.rag = SimpleNamespace(recuperar=lambda _: "", ultima_fontes=[], ultima_busca_disponivel=True)
    sessao.id_sessao = None
    resposta = "".join(sessao.responder("O que você sabe sobre mim?"))
    assert "resultado_memoria status=\"sem_correspondencia\"" in provedor.sistema
    assert "Não afirme que se lembra" in provedor.sistema
    assert resposta == "Não encontrei essa informação."


def test_alegacao_de_lembranca_exige_memoria_gravada() -> None:
    from alfred.ferramentas.resultado import ResultadoFerramenta
    from alfred.nucleo.politicas.verificador_alegacoes import alegacao_confirmada, ferramenta_da_alegacao
    frase = "Vou lembrar dessa preferência."
    assert ferramenta_da_alegacao(frase) == "lembrar_memoria"
    assert not alegacao_confirmada(frase, [])
    assert not alegacao_confirmada(frase, [ResultadoFerramenta("lembrar_memoria", "falha", "erro")])
    assert alegacao_confirmada(frase, [ResultadoFerramenta("lembrar_memoria", "sucesso", "id fictício")])
