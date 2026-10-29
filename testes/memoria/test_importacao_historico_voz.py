from __future__ import annotations

import hashlib
import json
from datetime import datetime

from alfred.memoria.armazenamento.conexao import abrir_conexao
from alfred.memoria.armazenamento.importacao_historico_voz import importar_historico_voz


def _linha(data: str, campo: str, texto: str) -> str:
    return (
        f"{data} INFO alfred.voz conversa {campo}="
        f"{json.dumps(texto, ensure_ascii=False)} resultado=transcrito"
    )


def test_importa_transcricoes_locais_e_eh_idempotente(armazenamento_memoria, tmp_path) -> None:
    armazenamento = armazenamento_memoria
    caminho_log = tmp_path / "voz.log"
    caminho_log.write_text(
        "\n".join((
            _linha("2021-05-04 13:12:10,123", "frase_input", "O projeto se chama Orion."),
            _linha("2021-05-04 13:12:15,456", "frase_output", "Entendi, Orion."),
            _linha("2021-05-04 13:13:00,100", "frase_input", 'Ele disse "Orion".'),
            "linha sem conversa",
        )),
        encoding="utf-8",
    )

    primeira = importar_historico_voz(caminho_log, armazenamento.banco)
    segunda = importar_historico_voz(caminho_log, armazenamento.banco)

    assert primeira == 3
    assert segunda == 0
    with abrir_conexao(
        armazenamento.caminho_alfred,
        armazenamento.banco._chave_banco,
        escritor=False,
    ) as db:
        linhas = db.execute(
            "SELECT papel, texto, criado_em, origem FROM eventos "
            "WHERE tipo='conversa' ORDER BY criado_em, id"
        ).fetchall()
        sessoes = db.execute("SELECT count(*) FROM sessoes").fetchone()[0]
    assert [linha["papel"] for linha in linhas] == ["usuario", "alfred", "usuario"]
    assert linhas[2]["texto"] == 'Ele disse "Orion".'
    assert linhas[0]["criado_em"] == int(
        datetime.strptime("2021-05-04 13:12:10,123", "%Y-%m-%d %H:%M:%S,%f")
        .astimezone().timestamp() * 1000
    )
    assert all(linha["origem"] == "importacao" for linha in linhas)
    assert sessoes == 1


def test_nao_duplica_fala_que_ja_esta_no_banco(armazenamento_memoria, tmp_path) -> None:
    armazenamento = armazenamento_memoria
    caminho_log = tmp_path / "voz.log"
    texto = "O projeto se chama Orion."
    data = "2021-05-04 13:12:10,123"
    instante = int(
        datetime.strptime(data, "%Y-%m-%d %H:%M:%S,%f").astimezone().timestamp() * 1000
    )
    sessao = armazenamento.banco.criar_sessao("voz", instante)
    armazenamento.banco.inserir_evento(
        tipo="conversa", criado_em=instante + 500, origem="usuario",
        hash_texto=hashlib.sha256(texto.encode()).hexdigest(), papel="usuario",
        texto=texto, sessao_id=sessao,
    )
    caminho_log.write_text(
        _linha(data, "frase_input", texto) + "\n"
        + _linha("2021-05-04 13:12:15,456", "frase_output", "Anotado."),
        encoding="utf-8",
    )

    assert importar_historico_voz(caminho_log, armazenamento.banco) == 1

