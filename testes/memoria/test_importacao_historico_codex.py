from __future__ import annotations

import json

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.importacao_historico_codex import importar_historico_codex


def _registro(tipo: str, instante: str, carga: dict) -> str:
    return json.dumps({"type": tipo, "timestamp": instante, "payload": carga})


def test_importa_historico_codex_completo_e_idempotente(armazenamento_memoria, tmp_path) -> None:
    pasta = tmp_path / ".codex"
    sessoes = pasta / "sessions" / "2026" / "10" / "25"
    sessoes.mkdir(parents=True)
    arquivo = sessoes / "conversa-1.jsonl"
    arquivo.write_text("\n".join((
        _registro("session_meta", "2021-04-03T10:00:00Z", {
            "id": "sessao-antiga", "cwd": "C:/projetos/Alfred",
        }),
        _registro("response_item", "2021-04-03T10:01:00Z", {
            "type": "message", "id": "msg-user", "role": "user",
            "content": [{"type": "input_text", "text": "Como estava o projeto Orion?"}],
        }),
        _registro("response_item", "2021-04-03T10:02:00Z", {
            "type": "message", "id": "msg-assistant", "role": "assistant",
            "content": [{"type": "output_text", "text": "Estava na fase de testes."}],
        }),
        _registro("response_item", "2021-04-03T10:03:00Z", {
            "type": "message", "id": "msg-tool", "role": "developer",
            "content": [{"type": "input_text", "text": "segredo interno"}],
        }),
        _registro("response_item", "2021-04-03T10:04:00Z", {
            "type": "function_call", "name": "tool", "arguments": "não importar",
        }),
    )), encoding="utf-8")

    banco = armazenamento_memoria.banco
    assert importar_historico_codex(pasta, banco) == 2
    assert importar_historico_codex(pasta, banco) == 0
    assert banco.buscar_conversas_historico("projeto Orion", limite=5)[0]["texto"] == (
        "Como estava o projeto Orion?"
    )
    with abrir_conexao(banco.caminho, banco._chave_banco, escritor=False) as db:
        eventos = db.execute(
            "SELECT papel, texto, criado_em, origem FROM eventos "
            "WHERE tipo='conversa' ORDER BY criado_em"
        ).fetchall()
        sessoes_importadas = db.execute(
            "SELECT count(*) FROM sessoes WHERE modelo_llm='codex_importado'"
        ).fetchone()[0]
    assert [(evento["papel"], evento["texto"]) for evento in eventos] == [
        ("usuario", "Como estava o projeto Orion?"),
        ("alfred", "Estava na fase de testes."),
    ]
    assert [evento["criado_em"] for evento in eventos] == [1617444060000, 1617444120000]
    assert all(evento["origem"] == "importacao" for evento in eventos)
    assert sessoes_importadas == 1


def test_sessao_codex_em_atualizacao_importa_so_mensagens_novas(armazenamento_memoria, tmp_path) -> None:
    pasta = tmp_path / ".codex"
    sessoes = pasta / "sessions"
    sessoes.mkdir(parents=True)
    arquivo = sessoes / "conversa-2.jsonl"
    meta = _registro("session_meta", "2024-01-01T00:00:00Z", {"id": "sessao-mutavel"})
    primeira = _registro("response_item", "2024-01-01T00:01:00Z", {
        "type": "message", "id": "msg-1", "role": "user",
        "content": [{"type": "input_text", "text": "Primeira parte antiga."}],
    })
    arquivo.write_text(meta + "\n" + primeira + "\n", encoding="utf-8")
    banco = armazenamento_memoria.banco
    assert importar_historico_codex(pasta, banco) == 1
    nova = _registro("response_item", "2024-01-01T00:02:00Z", {
        "type": "message", "id": "msg-2", "role": "assistant",
        "content": [{"type": "output_text", "text": "Resposta posterior."}],
    })
    arquivo.write_text(meta + "\n" + primeira + "\n" + nova + "\n", encoding="utf-8")
    assert importar_historico_codex(pasta, banco) == 1
    assert len(banco.buscar_conversas_recentes(limite=10)) == 2


def test_importa_sessao_codex_arquivada_compactada(armazenamento_memoria, tmp_path) -> None:
    try:
        from compression import zstd
        compactar = zstd.compress
    except ImportError:
        import zstandard
        compactar = zstandard.ZstdCompressor().compress
    pasta = tmp_path / ".codex"
    arquivo = pasta / "archived_sessions" / "antiga.jsonl.zst"
    arquivo.parent.mkdir(parents=True)
    conteudo = "\n".join((
        _registro("session_meta", "2020-01-01T00:00:00Z", {"id": "sessao-arquivada"}),
        _registro("response_item", "2020-01-01T00:01:00Z", {
            "type": "message", "id": "msg-arquivada", "role": "user",
            "content": [{"type": "input_text", "text": "Lembre da decisão do projeto antigo."}],
        }),
    )).encode("utf-8")
    arquivo.write_bytes(compactar(conteudo))

    banco = armazenamento_memoria.banco
    assert importar_historico_codex(pasta, banco) == 1
    assert importar_historico_codex(pasta, banco) == 0
    assert banco.buscar_conversas_historico("decisão projeto antigo", limite=1)[0]["texto"] == (
        "Lembre da decisão do projeto antigo."
    )
