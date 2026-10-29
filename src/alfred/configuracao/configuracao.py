"""Configuração da aplicação com caminhos independentes do diretório atual."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

RAIZ_PROJETO = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Configuracao:
    provedor_llm: str = "ollama"
    modelo: str = "qwen3.5:4b"
    url_llm: str = "http://localhost:11434"
    ollama_url: str = "http://localhost:11434"
    modelo_embeddings: str = "qwen3-embedding:0.6b"
    embeddings_tamanho_lote: int = 32
    embeddings_num_gpu: int = 0
    embeddings_num_thread: int = 4
    embeddings_keep_alive: str = "1m"
    pasta_perfil: Path = RAIZ_PROJETO / "dados" / "perfil"
    pasta_arquivos: Path = RAIZ_PROJETO / "dados" / "arquivos"
    pasta_pessoas: Path = RAIZ_PROJETO / "dados" / "perfil" / "pessoas"
    arquivos_limite_arquivos: int = 200
    arquivos_limite_bytes: int = 20 * 1024 * 1024
    arquivo_limite_bytes: int = 1_000_000
    pessoas_limite_total: int = 100
    pessoa_limite_palavras: int = 400
    janela_mensagens: int = 20
    tempo_limite_s: float = 120.0
    voz_taxa_amostragem: int = 16000
    voz_bloco_ms: int = 30
    voz_debug_dir: Path = RAIZ_PROJETO / "dados" / "debug_voz"
    voz_limite_historico: int = 6
    voz_ollama_keep_alive: str = "2m"
    voz_num_ctx: int = 8192
    voz_num_predict: int = 144
    voz_temperatura: float = 0.8
    voz_engine_stt: str = "parakeet"
    voz_modelo_stt: str = "base"
    voz_vocabulario_stt: tuple[str, ...] = ()
    voz_dispositivo_stt: str = "cpu"
    voz_compute_type: str = "int8"
    voz_perfil_stt: str = "equilibrado"
    voz_modelo_ativacao: str = "hey_jarvis"
    voz_palavra_ativacao: str = "Alfred"
    voz_modo: str = "apertar"
    voz_limiar_vad_inicio: float = 0.5
    voz_limiar_vad_fim: float = 0.35
    voz_vad_silencio_completo_ms: int = 300
    voz_vad_silencio_hesitacao_ms: int = 600
    voz_vad_limiar_interrupcao: float = 0.8
    voz_vad_interrupcao_minima_ms: int = 120
    voz_interromper_com_palavra: bool = False
    voz_caminho_modelo_voz: Path = RAIZ_PROJETO / "dados" / "modelos" / "pt_BR-faber-medium.onnx"
    voz_piper_length_scale: float = 1.25
    voz_motor_tts: str = "voicestudio"
    voicestudio_url: str = "http://127.0.0.1:3900/v1"
    voicestudio_motor: str = "omnivoice"
    voicestudio_voz: str = "66b001cc"
    voicestudio_velocidade: float = 1.0
    voicestudio_estabilidade_seed: int = 42
    voicestudio_estilo: str = (
        "Fale em português brasileiro com ritmo de conversa espontânea: entonação sutilmente "
        "variada, pausas breves entre ideias e um tom caloroso e tranquilo. Evite soar como "
        "locução, leitura de texto ou anúncio, sem exagerar emoções. Mantenha o mesmo timbre. "
        "Pronuncie termos técnicos comuns em inglês naturalmente, sem trocar de idioma."
    )
    voicestudio_formato: str = "pcm"
    voicestudio_taxa_amostragem: int = 24000
    voicestudio_timeout_conexao_s: float = 3.0
    voicestudio_timeout_leitura_s: float = 30.0
    tts_fallback: str = "piper"
    voz_debug: bool = False


def _inteiro_positivo(variavel: str, padrao: int) -> int:
    valor = os.getenv(variavel)
    if valor is None:
        return padrao
    try:
        numero = int(valor)
    except ValueError:
        raise ValueError(f"{variavel} deve ser um número inteiro") from None
    if numero < 1:
        raise ValueError(f"{variavel} deve ser maior que zero")
    return numero


def _inteiro_nao_negativo(variavel: str, padrao: int) -> int:
    valor = os.getenv(variavel)
    if valor is None:
        return padrao
    try:
        numero = int(valor)
    except ValueError:
        raise ValueError(f"{variavel} deve ser um número inteiro") from None
    if numero < 0:
        raise ValueError(f"{variavel} não pode ser negativo")
    return numero


def _url_ollama_local(variavel: str) -> str:
    valor = os.getenv(variavel, "http://localhost:11434").rstrip("/")
    endereco = urlparse(valor)
    if endereco.scheme != "http" or endereco.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError(f"{variavel} deve apontar para Ollama em localhost")
    return valor


def _url_llm_local(variavel: str, padrao: str) -> str:
    valor = os.getenv(variavel, padrao).rstrip("/")
    endereco = urlparse(valor)
    if (
        endereco.scheme != "http"
        or endereco.hostname not in {"localhost", "127.0.0.1", "::1"}
        or endereco.username is not None
        or endereco.password is not None
        or endereco.query
        or endereco.fragment
    ):
        raise ValueError(f"{variavel} deve apontar para um servidor HTTP local")
    return valor


def _url_voicestudio_local() -> str:
    valor = os.getenv("ALFRED_VOICESTUDIO_URL", "http://127.0.0.1:3900/v1").rstrip("/")
    endereco = urlparse(valor)
    if endereco.scheme not in {"http", "https"} or endereco.hostname not in {
        "localhost", "127.0.0.1", "::1"
    }:
        raise ValueError("ALFRED_VOICESTUDIO_URL deve usar somente localhost ou um endereço de loopback")
    if (
        endereco.username is not None
        or endereco.password is not None
        or endereco.query
        or endereco.fragment
        or not endereco.path.rstrip("/").endswith("/v1")
    ):
        raise ValueError("ALFRED_VOICESTUDIO_URL deve ser uma URL local terminada em /v1")
    try:
        porta = endereco.port or (443 if endereco.scheme == "https" else 80)
    except ValueError:
        raise ValueError("ALFRED_VOICESTUDIO_URL contém uma porta inválida") from None
    try:
        enderecos = socket.getaddrinfo(endereco.hostname, porta, type=socket.SOCK_STREAM)
        if not enderecos or any(
            not ipaddress.ip_address(item[4][0]).is_loopback
            for item in enderecos
        ):
            raise ValueError
    except (OSError, ValueError):
        raise ValueError("ALFRED_VOICESTUDIO_URL deve resolver somente para loopback") from None
    return valor


def _numero_positivo(variavel: str, padrao: float) -> float:
    try:
        numero = float(os.getenv(variavel, str(padrao)))
    except ValueError:
        raise ValueError(f"{variavel} deve ser um número") from None
    if not math.isfinite(numero) or numero <= 0:
        raise ValueError(f"{variavel} deve ser maior que zero")
    return numero


def _temperatura(variavel: str, padrao: float) -> float:
    try:
        numero = float(os.getenv(variavel, str(padrao)))
    except ValueError:
        raise ValueError(f"{variavel} deve ser um número entre zero e dois") from None
    if not math.isfinite(numero) or not 0 <= numero <= 2:
        raise ValueError(f"{variavel} deve ser um número entre zero e dois")
    return numero


def _carregar_preferencias_voicestudio() -> None:
    caminho_voz = RAIZ_PROJETO / "dados" / "perfil" / "voz_alfred.json"
    if not caminho_voz.is_file():
        return
    try:
        with caminho_voz.open("r", encoding="utf-8") as arquivo:
            preferencias = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        raise ValueError("Não foi possível ler dados/perfil/voz_alfred.json") from None
    if not isinstance(preferencias, dict):
        raise ValueError("dados/perfil/voz_alfred.json deve conter um objeto")

    variaveis_por_preferencia = {
        "model": "ALFRED_VOICESTUDIO_MOTOR",
        "voice_id": "ALFRED_VOICESTUDIO_VOZ",
        "speed": "ALFRED_VOICESTUDIO_VELOCIDADE",
        "seed": "ALFRED_VOICESTUDIO_SEED",
        "style": "ALFRED_VOICESTUDIO_ESTILO",
    }
    for preferencia, variavel in variaveis_por_preferencia.items():
        valor = preferencias.get(preferencia)
        # Preferências antigas podem ter gravado a string vazia apenas porque
        # não havia estilo padrão. Deixe o padrão conversacional do YAML valer.
        if preferencia == "style" and isinstance(valor, str) and not valor.strip():
            continue
        if isinstance(valor, (str, int, float)) and not isinstance(valor, bool):
            os.environ.setdefault(variavel, str(valor))


def _carregar_configuracao_yaml(caminho_yaml: Path) -> None:
    if not caminho_yaml.is_file():
        return
    try:
        with caminho_yaml.open("r", encoding="utf-8") as arquivo:
            documento = yaml.safe_load(arquivo) or {}
    except (OSError, yaml.YAMLError) as erro:
        raise ValueError(f"Não foi possível ler config.yaml: {erro}") from None
    if not isinstance(documento, dict):
        raise ValueError("config.yaml deve conter um objeto YAML")

    variaveis_por_caminho = {
        "llm.provider": "ALFRED_LLM_PROVIDER",
        "llm.model": "ALFRED_MODELO",
        "llm.url": "ALFRED_LLM_URL",
        "embeddings.url": "ALFRED_OLLAMA_URL",
        "llm.timeout_seconds": "ALFRED_TEMPO_LIMITE_S",
        "llm.history_turns": "ALFRED_VOZ_HISTORICO",
        "llm.context_tokens": "ALFRED_VOZ_NUM_CTX",
        "llm.max_tokens": "ALFRED_VOZ_NUM_PREDICT",
        "audio.block_ms": "ALFRED_AUDIO_BLOCO_MS",
        "vad.silence_ms": "ALFRED_VAD_SILENCIO_COMPLETO_MS",
        "vad.silence_hesitation_ms": "ALFRED_VAD_SILENCIO_HESITACAO_MS",
        "vad.start_threshold": "ALFRED_VAD_LIMIAR_INICIO",
        "vad.end_threshold": "ALFRED_VAD_LIMIAR_FIM",
        "vad.barge_in_threshold": "ALFRED_VAD_LIMIAR_INTERRUPCAO",
        "vad.barge_in_min_ms": "ALFRED_VAD_INTERRUPCAO_MINIMA_MS",
        "stt.engine": "ALFRED_STT_ENGINE",
        "stt.model": "ALFRED_STT_MODELO",
        "stt.device": "ALFRED_STT_DISPOSITIVO",
        "stt.compute_type": "ALFRED_STT_COMPUTE_TYPE",
        "stt.hotwords": "ALFRED_STT_VOCABULARIO",
        "stt.profile": "ALFRED_STT_PERFIL",
        "tts.provider": "ALFRED_TTS_MOTOR",
        "tts.url": "ALFRED_VOICESTUDIO_URL",
        "tts.model": "ALFRED_VOICESTUDIO_MOTOR",
        "tts.voice_id": "ALFRED_VOICESTUDIO_VOZ",
        "tts.speed": "ALFRED_VOICESTUDIO_VELOCIDADE",
        "tts.seed": "ALFRED_VOICESTUDIO_SEED",
        "tts.style": "ALFRED_VOICESTUDIO_ESTILO",
        "voice.mode": "ALFRED_VOZ_MODO",
        "voice.debug_dir": "ALFRED_DEBUG_DIR",
        "map.satellite_url": "ALFRED_MAPA_SATELITE_URL",
        "map.satellite_attribution": "ALFRED_MAPA_SATELITE_ATRIBUICAO",
    }
    for caminho, variavel in variaveis_por_caminho.items():
        valor = _obter_valor_aninhado(documento, caminho)
        if valor is not None:
            texto = ",".join(map(str, valor)) if isinstance(valor, list) else str(valor)
            os.environ.setdefault(variavel, texto)


def _obter_valor_aninhado(documento: dict, caminho: str) -> object | None:
    atual: object = documento
    for chave in caminho.split("."):
        atual = atual.get(chave) if isinstance(atual, dict) else None
    return atual


def carregar_configuracao() -> Configuracao:
    """Lê config.yaml como padrão; variáveis de ambiente continuam prevalecendo."""
    caminho_yaml = RAIZ_PROJETO / "config.yaml"
    _carregar_preferencias_voicestudio()
    _carregar_configuracao_yaml(caminho_yaml)
    pasta = Path(os.getenv("ALFRED_PASTA_PERFIL", "dados/perfil"))
    if not pasta.is_absolute():
        pasta = RAIZ_PROJETO / pasta
    pasta_arquivos = Path(os.getenv("ALFRED_PASTA_ARQUIVOS", "dados/arquivos"))
    if not pasta_arquivos.is_absolute():
        pasta_arquivos = RAIZ_PROJETO / pasta_arquivos
    pasta_pessoas = Path(os.getenv("ALFRED_PASTA_PESSOAS", "dados/perfil/pessoas"))
    if not pasta_pessoas.is_absolute():
        pasta_pessoas = RAIZ_PROJETO / pasta_pessoas
    try:
        tempo_limite = float(os.getenv("ALFRED_TEMPO_LIMITE_S", "120"))
    except ValueError:
        raise ValueError("ALFRED_TEMPO_LIMITE_S deve ser um número") from None
    if not math.isfinite(tempo_limite) or tempo_limite <= 0:
        raise ValueError("ALFRED_TEMPO_LIMITE_S deve ser maior que zero")

    try:
        vad_inicio = float(os.getenv("ALFRED_VAD_LIMIAR_INICIO", "0.5"))
        vad_fim = float(os.getenv("ALFRED_VAD_LIMIAR_FIM", "0.35"))
    except ValueError:
        raise ValueError("Os limiares VAD devem ser números entre zero e um") from None
    if not (0 < vad_fim <= vad_inicio <= 1):
        raise ValueError("Os limiares VAD devem obedecer 0 < fim <= início <= 1")
    vad_limiar_interrupcao = float(os.getenv("ALFRED_VAD_LIMIAR_INTERRUPCAO", "0.8"))
    if not 0 < vad_limiar_interrupcao <= 1:
        raise ValueError("ALFRED_VAD_LIMIAR_INTERRUPCAO deve estar entre zero e um")
    silencio_completo_ms = _inteiro_positivo("ALFRED_VAD_SILENCIO_COMPLETO_MS", 500)
    silencio_hesitacao_ms = _inteiro_positivo("ALFRED_VAD_SILENCIO_HESITACAO_MS", 600)
    interrupcao_minima_ms = _inteiro_positivo("ALFRED_VAD_INTERRUPCAO_MINIMA_MS", 120)
    if silencio_hesitacao_ms < silencio_completo_ms:
        raise ValueError("O silêncio de hesitação deve ser maior ou igual ao silêncio completo")
    caminho_voz = Path(os.getenv("ALFRED_PIPER_MODELO", "dados/modelos/pt_BR-faber-medium.onnx"))
    if not caminho_voz.is_absolute():
        caminho_voz = RAIZ_PROJETO / caminho_voz
    try:
        velocidade_voz = float(os.getenv("ALFRED_PIPER_LENGTH_SCALE", "1.25"))
    except ValueError:
        raise ValueError("ALFRED_PIPER_LENGTH_SCALE deve ser um número entre 0.5 e 3") from None
    if not math.isfinite(velocidade_voz) or not 0.5 <= velocidade_voz <= 3:
        raise ValueError("ALFRED_PIPER_LENGTH_SCALE deve estar entre 0.5 e 3")
    modo_voz = os.getenv("ALFRED_VOZ_MODO", "apertar").lower()
    if modo_voz not in {"apertar", "palavra", "conversa"}:
        raise ValueError("ALFRED_VOZ_MODO deve ser 'apertar', 'palavra' ou 'conversa'")
    keep_alive_voz = os.getenv("ALFRED_VOZ_OLLAMA_KEEP_ALIVE", "2m")
    if not keep_alive_voz.strip():
        raise ValueError("ALFRED_VOZ_OLLAMA_KEEP_ALIVE não pode ficar vazio")
    bloco_ms = int(os.getenv("ALFRED_AUDIO_BLOCO_MS", "30"))
    if not 20 <= bloco_ms <= 30:
        raise ValueError("ALFRED_AUDIO_BLOCO_MS deve ficar entre 20 e 30")
    debug_dir = Path(os.getenv("ALFRED_DEBUG_DIR", "dados/debug_voz"))
    if not debug_dir.is_absolute():
        debug_dir = RAIZ_PROJETO / debug_dir
    perfil_stt = os.getenv("ALFRED_STT_PERFIL", "equilibrado").lower()
    if perfil_stt not in {"rápido", "equilibrado", "preciso"}:
        raise ValueError("ALFRED_STT_PERFIL deve ser rápido, equilibrado ou preciso")
    vocabulario_stt = tuple(dict.fromkeys(
        termo.strip() for termo in os.getenv("ALFRED_STT_VOCABULARIO", "").split(",")
        if termo.strip()
    ))
    motor_tts = os.getenv("ALFRED_TTS_MOTOR", "voicestudio").strip().lower()
    if motor_tts != "voicestudio":
        raise ValueError("ALFRED_TTS_MOTOR deve ser 'voicestudio' para preservar a voz configurada")
    motor_voicestudio = os.getenv("ALFRED_VOICESTUDIO_MOTOR", "omnivoice").strip()
    voz_voicestudio = os.getenv("ALFRED_VOICESTUDIO_VOZ", "66b001cc").strip()
    if not motor_voicestudio or not voz_voicestudio:
        raise ValueError("ALFRED_VOICESTUDIO_MOTOR e ALFRED_VOICESTUDIO_VOZ não podem ficar vazios")
    velocidade_voicestudio = _numero_positivo("ALFRED_VOICESTUDIO_VELOCIDADE", 1.0)
    if not 0.25 <= velocidade_voicestudio <= 4:
        raise ValueError("ALFRED_VOICESTUDIO_VELOCIDADE deve estar entre 0.25 e 4")
    seed_voicestudio = _inteiro_nao_negativo("ALFRED_VOICESTUDIO_SEED", 42)
    formato_voicestudio = os.getenv("ALFRED_VOICESTUDIO_FORMAT", "pcm").strip().lower()
    if formato_voicestudio != "pcm":
        raise ValueError("ALFRED_VOICESTUDIO_FORMAT deve ser 'pcm'")
    taxa_voicestudio = _inteiro_positivo("ALFRED_VOICESTUDIO_TAXA", 24000)
    if taxa_voicestudio != 24000:
        raise ValueError("ALFRED_VOICESTUDIO_TAXA deve ser 24000 para PCM mono")
    fallback_tts = os.getenv("ALFRED_TTS_FALLBACK", "piper").strip().lower()
    if fallback_tts not in {"texto", "piper"}:
        raise ValueError("ALFRED_TTS_FALLBACK deve ser 'piper' ou 'texto'")
    return Configuracao(
        provedor_llm=_provedor_llm(),
        modelo=os.getenv("ALFRED_MODELO", "qwen3.5:4b"),
        url_llm=_url_llm_local(
            "ALFRED_LLM_URL",
            os.getenv("ALFRED_OLLAMA_URL", "http://localhost:11434")
            if os.getenv("ALFRED_LLM_PROVIDER", "ollama").strip().lower() == "ollama"
            else "http://127.0.0.1:8000/v1",
        ),
        ollama_url=_url_ollama_local("ALFRED_OLLAMA_URL"),
        modelo_embeddings=os.getenv(
            "ALFRED_MODELO_EMBEDDINGS", "qwen3-embedding:0.6b"
        ),
        embeddings_tamanho_lote=_inteiro_positivo(
            "ALFRED_EMBEDDINGS_LOTE", 32
        ),
        embeddings_num_gpu=_inteiro_nao_negativo(
            "ALFRED_EMBEDDINGS_NUM_GPU", 0
        ),
        embeddings_num_thread=_inteiro_positivo(
            "ALFRED_EMBEDDINGS_THREADS", 4
        ),
        embeddings_keep_alive=os.getenv("ALFRED_EMBEDDINGS_KEEP_ALIVE", "1m"),
        pasta_perfil=pasta.resolve(),
        pasta_arquivos=pasta_arquivos,
        pasta_pessoas=pasta_pessoas,
        arquivos_limite_arquivos=_inteiro_positivo("ALFRED_ARQUIVOS_LIMITE_ARQUIVOS", 200),
        arquivos_limite_bytes=_inteiro_positivo("ALFRED_ARQUIVOS_LIMITE_BYTES", 20 * 1024 * 1024),
        arquivo_limite_bytes=_inteiro_positivo("ALFRED_ARQUIVO_LIMITE_BYTES", 1_000_000),
        pessoas_limite_total=_inteiro_positivo("ALFRED_PESSOAS_LIMITE_TOTAL", 100),
        pessoa_limite_palavras=_inteiro_positivo("ALFRED_PESSOA_LIMITE_PALAVRAS", 400),
        janela_mensagens=_inteiro_positivo("ALFRED_JANELA_MENSAGENS", 20),
        tempo_limite_s=tempo_limite,
        voz_taxa_amostragem=16000,
        voz_bloco_ms=bloco_ms,
        voz_debug_dir=debug_dir.resolve(),
        voz_limite_historico=_inteiro_positivo("ALFRED_VOZ_HISTORICO", 6),
        voz_ollama_keep_alive=keep_alive_voz,
        voz_num_ctx=_inteiro_positivo("ALFRED_VOZ_NUM_CTX", 4096),
        voz_num_predict=_inteiro_positivo("ALFRED_VOZ_NUM_PREDICT", 192),
        voz_temperatura=_temperatura("ALFRED_VOZ_TEMPERATURA", 0.8),
        voz_engine_stt=os.getenv("ALFRED_STT_ENGINE", "parakeet"),
        voz_modelo_stt=os.getenv("ALFRED_STT_MODELO", "base"),
        voz_vocabulario_stt=vocabulario_stt,
        voz_dispositivo_stt=os.getenv("ALFRED_STT_DISPOSITIVO", "cpu"),
        voz_compute_type=os.getenv("ALFRED_STT_COMPUTE_TYPE", "int8"),
        voz_perfil_stt=perfil_stt,
        voz_modelo_ativacao=os.getenv("ALFRED_MODELO_ATIVACAO", "hey_jarvis"),
        voz_palavra_ativacao=os.getenv("ALFRED_PALAVRA_ATIVACAO", "Alfred"),
        voz_modo=modo_voz,
        voz_limiar_vad_inicio=vad_inicio,
        voz_limiar_vad_fim=vad_fim,
        voz_vad_silencio_completo_ms=silencio_completo_ms,
        voz_vad_silencio_hesitacao_ms=silencio_hesitacao_ms,
        voz_vad_limiar_interrupcao=vad_limiar_interrupcao,
        voz_vad_interrupcao_minima_ms=interrupcao_minima_ms,
        voz_interromper_com_palavra=os.getenv("ALFRED_BARGE_IN_PALAVRA", "false").lower() in {"1", "true", "sim"},
        voz_caminho_modelo_voz=caminho_voz.resolve(),
        voz_piper_length_scale=velocidade_voz,
        voz_motor_tts=motor_tts,
        voicestudio_url=_url_voicestudio_local(),
        voicestudio_motor=motor_voicestudio,
        voicestudio_voz=voz_voicestudio,
        voicestudio_velocidade=velocidade_voicestudio,
        voicestudio_estabilidade_seed=seed_voicestudio,
        voicestudio_estilo=os.getenv(
            "ALFRED_VOICESTUDIO_ESTILO",
            "Fale em português brasileiro com ritmo de conversa espontânea: entonação sutilmente "
            "variada, pausas breves entre ideias e um tom caloroso e tranquilo. Evite soar como "
            "locução, leitura de texto ou anúncio, sem exagerar emoções. Mantenha o mesmo timbre. "
            "Pronuncie termos técnicos comuns em inglês naturalmente, sem trocar de idioma.",
        ),
        voicestudio_formato=formato_voicestudio,
        voicestudio_taxa_amostragem=taxa_voicestudio,
        voicestudio_timeout_conexao_s=_numero_positivo(
            "ALFRED_VOICESTUDIO_TIMEOUT_CONEXAO", 3.0
        ),
        voicestudio_timeout_leitura_s=_numero_positivo(
            "ALFRED_VOICESTUDIO_TIMEOUT_LEITURA", 30.0
        ),
        tts_fallback=fallback_tts,
        voz_debug=os.getenv("ALFRED_DEBUG", "false").lower() in {"1", "true", "sim"},
    )


def _provedor_llm() -> str:
    provedor = os.getenv("ALFRED_LLM_PROVIDER", "ollama").strip().lower()
    if provedor not in {"ollama", "colibri"}:
        raise ValueError("ALFRED_LLM_PROVIDER deve ser 'ollama' ou 'colibri'")
    return provedor
