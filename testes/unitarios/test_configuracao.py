from pathlib import Path

import pytest

from alfred.configuracao.configuracao import RAIZ_PROJETO, carregar_configuracao


def test_carrega_padroes_e_resolve_perfil_na_raiz(monkeypatch):
    for nome in (
        "ALFRED_MODELO",
        "ALFRED_OLLAMA_URL",
        "ALFRED_MODELO_EMBEDDINGS",
        "ALFRED_EMBEDDINGS_LOTE",
        "ALFRED_EMBEDDINGS_NUM_GPU",
        "ALFRED_EMBEDDINGS_THREADS",
        "ALFRED_EMBEDDINGS_KEEP_ALIVE",
        "ALFRED_PASTA_PERFIL",
        "ALFRED_PASTA_ARQUIVOS",
        "ALFRED_PASTA_PESSOAS",
        "ALFRED_ARQUIVOS_LIMITE_ARQUIVOS",
        "ALFRED_ARQUIVOS_LIMITE_BYTES",
        "ALFRED_ARQUIVO_LIMITE_BYTES",
        "ALFRED_PESSOAS_LIMITE_TOTAL",
        "ALFRED_PESSOA_LIMITE_PALAVRAS",
        "ALFRED_JANELA_MENSAGENS",
        "ALFRED_TEMPO_LIMITE_S",
        "ALFRED_VOZ_OLLAMA_KEEP_ALIVE",
        "ALFRED_VOZ_NUM_CTX",
        "ALFRED_VOZ_NUM_PREDICT",
        "ALFRED_VAD_SILENCIO_COMPLETO_MS",
        "ALFRED_VAD_SILENCIO_HESITACAO_MS",
        "ALFRED_VAD_LIMIAR_INTERRUPCAO",
        "ALFRED_VAD_INTERRUPCAO_MINIMA_MS",
        "ALFRED_STT_PERFIL",
        "ALFRED_VOZ_MODO",
        "ALFRED_PIPER_LENGTH_SCALE",
        "ALFRED_TTS_MOTOR",
        "ALFRED_VOICESTUDIO_URL",
        "ALFRED_VOICESTUDIO_MOTOR",
        "ALFRED_VOICESTUDIO_VOZ",
        "ALFRED_VOICESTUDIO_FORMAT",
        "ALFRED_VOICESTUDIO_TAXA",
        "ALFRED_VOICESTUDIO_TIMEOUT_CONEXAO",
        "ALFRED_VOICESTUDIO_TIMEOUT_LEITURA",
        "ALFRED_TTS_FALLBACK",
    ):
        monkeypatch.delenv(nome, raising=False)

    configuracao = carregar_configuracao()

    assert configuracao.modelo == "qwen3.6-colibri"
    assert configuracao.ollama_url == "http://localhost:11434"
    assert configuracao.modelo_embeddings == "qwen3-embedding:0.6b"
    assert configuracao.embeddings_tamanho_lote == 32
    assert configuracao.embeddings_num_gpu == 0
    assert configuracao.embeddings_num_thread == 4
    assert configuracao.embeddings_keep_alive == "1m"
    assert configuracao.pasta_perfil == RAIZ_PROJETO / "dados" / "perfil"
    assert configuracao.pasta_arquivos == RAIZ_PROJETO / "dados" / "arquivos"
    assert configuracao.pasta_pessoas == RAIZ_PROJETO / "dados" / "perfil" / "pessoas"
    assert configuracao.arquivos_limite_arquivos == 200
    assert configuracao.arquivos_limite_bytes == 20 * 1024 * 1024
    assert configuracao.arquivo_limite_bytes == 1_000_000
    assert configuracao.pessoas_limite_total == 100
    assert configuracao.pessoa_limite_palavras == 400
    assert configuracao.janela_mensagens == 20
    assert configuracao.tempo_limite_s == 120
    assert configuracao.voz_ollama_keep_alive == "2m"
    assert configuracao.voz_num_ctx == 4096
    assert configuracao.voz_num_predict == 192
    assert configuracao.voz_vad_silencio_completo_ms == 500
    assert configuracao.voz_vad_silencio_hesitacao_ms == 600
    assert configuracao.voz_vad_limiar_interrupcao == 0.8
    assert configuracao.voz_vad_interrupcao_minima_ms == 120
    assert configuracao.voz_perfil_stt == "equilibrado"
    assert configuracao.voz_bloco_ms == 30
    assert configuracao.voz_engine_stt == "parakeet"
    assert configuracao.voz_modelo_stt == "nvidia/parakeet-tdt-0.6b-v3"
    assert configuracao.voz_dispositivo_stt == "cpu"
    assert configuracao.voz_motor_tts == "voicestudio"
    assert configuracao.voicestudio_url == "http://127.0.0.1:3900/v1"
    assert configuracao.voicestudio_motor == "omnivoice"
    assert configuracao.voicestudio_voz == "66b001cc"
    assert configuracao.voicestudio_formato == "pcm"
    assert configuracao.voicestudio_taxa_amostragem == 24000
    assert configuracao.voicestudio_timeout_conexao_s == 3
    assert configuracao.voicestudio_timeout_leitura_s == 30
    assert configuracao.tts_fallback == "piper"


def test_variaveis_sobrescrevem_padroes_e_caminho_relativo(monkeypatch):
    monkeypatch.setenv("ALFRED_MODELO", "outro-modelo")
    monkeypatch.setenv("ALFRED_OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("ALFRED_MODELO_EMBEDDINGS", "outro-embedding")
    monkeypatch.setenv("ALFRED_EMBEDDINGS_LOTE", "12")
    monkeypatch.setenv("ALFRED_EMBEDDINGS_NUM_GPU", "2")
    monkeypatch.setenv("ALFRED_EMBEDDINGS_THREADS", "6")
    monkeypatch.setenv("ALFRED_EMBEDDINGS_KEEP_ALIVE", "30s")
    monkeypatch.setenv("ALFRED_PASTA_PERFIL", "meus_dados/perfil")
    monkeypatch.setenv("ALFRED_PASTA_ARQUIVOS", "meus_dados/arquivos")
    monkeypatch.setenv("ALFRED_PASTA_PESSOAS", "meus_dados/perfil/pessoas")
    monkeypatch.setenv("ALFRED_ARQUIVOS_LIMITE_ARQUIVOS", "17")
    monkeypatch.setenv("ALFRED_ARQUIVOS_LIMITE_BYTES", "9000")
    monkeypatch.setenv("ALFRED_ARQUIVO_LIMITE_BYTES", "800")
    monkeypatch.setenv("ALFRED_PESSOAS_LIMITE_TOTAL", "12")
    monkeypatch.setenv("ALFRED_PESSOA_LIMITE_PALAVRAS", "100")
    monkeypatch.setenv("ALFRED_JANELA_MENSAGENS", "8")
    monkeypatch.setenv("ALFRED_TEMPO_LIMITE_S", "45.5")

    configuracao = carregar_configuracao()

    assert configuracao.modelo == "outro-modelo"
    assert configuracao.ollama_url == "http://127.0.0.1:11434"
    assert configuracao.modelo_embeddings == "outro-embedding"
    assert configuracao.embeddings_tamanho_lote == 12
    assert configuracao.embeddings_num_gpu == 2
    assert configuracao.embeddings_num_thread == 6
    assert configuracao.embeddings_keep_alive == "30s"
    assert configuracao.pasta_perfil == (RAIZ_PROJETO / "meus_dados/perfil").resolve()
    assert configuracao.pasta_arquivos == RAIZ_PROJETO / "meus_dados/arquivos"
    assert configuracao.pasta_pessoas == RAIZ_PROJETO / "meus_dados/perfil/pessoas"
    assert configuracao.arquivos_limite_arquivos == 17
    assert configuracao.arquivos_limite_bytes == 9000
    assert configuracao.arquivo_limite_bytes == 800
    assert configuracao.pessoas_limite_total == 12
    assert configuracao.pessoa_limite_palavras == 100
    assert configuracao.janela_mensagens == 8
    assert configuracao.tempo_limite_s == 45.5


@pytest.mark.parametrize(
    ("variavel", "valor", "mensagem"),
    [
        ("ALFRED_JANELA_MENSAGENS", "abc", "inteiro"),
        ("ALFRED_JANELA_MENSAGENS", "0", "maior que zero"),
        ("ALFRED_TEMPO_LIMITE_S", "abc", "número"),
        ("ALFRED_TEMPO_LIMITE_S", "0", "maior que zero"),
        ("ALFRED_EMBEDDINGS_LOTE", "0", "maior que zero"),
        ("ALFRED_EMBEDDINGS_NUM_GPU", "-1", "negativo"),
        ("ALFRED_EMBEDDINGS_THREADS", "0", "maior que zero"),
    ],
)
def test_rejeita_configuracao_numerica_invalida(monkeypatch, variavel, valor, mensagem):
    monkeypatch.setenv(variavel, valor)
    with pytest.raises(ValueError, match=mensagem):
        carregar_configuracao()


def test_rejeita_ollama_fora_da_propria_maquina(monkeypatch):
    monkeypatch.setenv("ALFRED_OLLAMA_URL", "http://ollama:11434")

    with pytest.raises(ValueError, match="localhost"):
        carregar_configuracao()


@pytest.mark.parametrize("valor", ["0.49", "3.01", "nan", "inf", "abc"])
def test_rejeita_velocidade_piper_invalida(monkeypatch, valor):
    monkeypatch.setenv("ALFRED_PIPER_LENGTH_SCALE", valor)
    with pytest.raises(ValueError, match="ALFRED_PIPER_LENGTH_SCALE"):
        carregar_configuracao()


def test_configura_velocidade_piper_mais_lenta(monkeypatch):
    monkeypatch.setenv("ALFRED_PIPER_LENGTH_SCALE", "1.4")
    assert carregar_configuracao().voz_piper_length_scale == 1.4


def test_configura_modo_conversa_continua(monkeypatch):
    monkeypatch.setenv("ALFRED_VOZ_MODO", "conversa")
    assert carregar_configuracao().voz_modo == "conversa"


def test_rejeita_modo_de_voz_desconhecido(monkeypatch):
    monkeypatch.setenv("ALFRED_VOZ_MODO", "sempre_ouvindo_sem_controle")
    with pytest.raises(ValueError, match="ALFRED_VOZ_MODO"):
        carregar_configuracao()


@pytest.mark.parametrize(
    ("variavel", "valor", "mensagem"),
    [
        ("ALFRED_TTS_MOTOR", "cloud", "ALFRED_TTS_MOTOR"),
        ("ALFRED_TTS_MOTOR", "piper", "preservar a voz"),
        ("ALFRED_VOICESTUDIO_URL", "http://192.168.1.8:3900/v1", "loopback"),
        ("ALFRED_VOICESTUDIO_URL", "http://localhost:3900/api", "terminada em /v1"),
        ("ALFRED_VOICESTUDIO_FORMAT", "mp3", "deve ser 'pcm'"),
        ("ALFRED_VOICESTUDIO_TAXA", "16000", "deve ser 24000"),
        ("ALFRED_VOICESTUDIO_TIMEOUT_CONEXAO", "nan", "maior que zero"),
        ("ALFRED_VOICESTUDIO_TIMEOUT_LEITURA", "-1", "maior que zero"),
        ("ALFRED_TTS_FALLBACK", "cloud", "ALFRED_TTS_FALLBACK"),
    ],
)
def test_rejeita_configuracao_voicestudio_invalida(monkeypatch, variavel, valor, mensagem):
    monkeypatch.setenv(variavel, valor)
    with pytest.raises(ValueError, match=mensagem):
        carregar_configuracao()
