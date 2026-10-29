from __future__ import annotations

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.seguranca.chaves.derivacao import derivar_subchave

from .conftest import (
    DIMENSAO_CONTROLADA,
    GeradorEmbeddingsControlados,
)
from .dados_ficticios import (
    INJECAO_FICTICIA,
    SENTINELA_ALFA,
    SENTINELA_ESQUECIMENTO,
    SENTINELA_PRIVACIDADE,
    criar_eventos_ficticios,
)


def test_corpus_e_ficticio_tem_300_eventos_em_90_dias() -> None:
    eventos = criar_eventos_ficticios()
    assert len(eventos) == 300
    assert len({evento.id for evento in eventos}) == 300
    assert (max(item.criado_em for item in eventos) - min(item.criado_em for item in eventos)) < 90 * 86_400_000
    assert any(SENTINELA_ALFA in item.texto for item in eventos)
    assert any(SENTINELA_ESQUECIMENTO in item.texto for item in eventos)
    assert any(SENTINELA_PRIVACIDADE in item.texto for item in eventos)
    assert any(INJECAO_FICTICIA in item.texto for item in eventos)
    assert any(item.fixada for item in eventos)


def test_embeddings_controlados_exigem_mapeamento_explicito(
    embeddings_controlados: GeradorEmbeddingsControlados,
) -> None:
    vetor = embeddings_controlados.gerar_em_lote(["cafe"], "consulta")[0]
    assert len(vetor) == DIMENSAO_CONTROLADA
    assert vetor[0] == 1.0
    try:
        embeddings_controlados.gerar_em_lote(["frase sem mapa"], "documento")
    except ValueError as erro:
        assert "sem vetor controlado" in str(erro)
    else:
        raise AssertionError("Texto desconhecido deve exigir vetor cadastrado")


def test_armazenamento_temporario_cria_tres_bancos_e_chroma(
    armazenamento_memoria,
) -> None:
    armazenamento = armazenamento_memoria
    assert armazenamento.caminho_alfred.is_file()
    assert armazenamento.caminho_auditoria.is_file()
    assert armazenamento.caminho_metricas.is_file()
    assert armazenamento.caminho_chroma.is_dir()
    chave_principal = derivar_subchave(
        armazenamento.chave_mestra, "alfred.db"
    )
    with abrir_conexao(
        armazenamento.caminho_alfred, chave_principal, escritor=False
    ) as conexao:
        assert conexao.execute("SELECT count(*) FROM eventos").fetchone()[0] == 0


def test_llm_falso_registra_prompt_e_relogio_nao_usa_sleep(
    llm_falso, relogio_falso
) -> None:
    mensagem = ("pergunta fictícia",)
    assert list(llm_falso.conversar(mensagem, sistema="sistema de teste"))
    assert llm_falso.prompts == ["sistema de teste"]
    assert llm_falso.mensagens == [mensagem]
    instante = relogio_falso()
    assert relogio_falso.avancar(1000) == instante + 1000
