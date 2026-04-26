"""
core/voice_engine.py — Motor de Voz do Alfred (TTS + STT).

TTS (Text-to-Speech):
    Primário:  edge-tts — voz neural Microsoft Azure (pt-BR-AntonioNeural)
    Fallback:  gTTS     — Google TTS online, saída MP3 natural
    Fallback2: pyttsx3  — motor offline, saída WAV

STT (Speech-to-Text) — lado servidor:
    Primário:  SpeechRecognition + Google Web Speech API
    Fallback:  OpenAI Whisper (local, se instalado)

Nota:
    A captura de microfone padrão é feita no NAVEGADOR via Web Speech API.
    O endpoint /transcribe serve como alternativa para clientes que enviem
    um blob de áudio diretamente (webm, wav, mp3).
"""
from __future__ import annotations

import base64
import io
import logging
import os
import re
import tempfile
from typing import Literal

logger = logging.getLogger(__name__)

# Tamanho de chunk para processamento progressivo (1-2 frases)
# Usado apenas para streaming - o texto completo SEMPRE é processado
_CHUNK_SIZE = 150

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove AGRESSIVAMENTE formatação Markdown e artefatos para TTS natural."""
    # Blocos de código (multiline e inline)
    text = re.sub(r"```[\s\S]*?```", " [arquivo de código] ", text)
    text = re.sub(r"`[^`]+`", "", text)  # Remove código inline completamente
    
    # URLs — substituir por descrição breve
    text = re.sub(r"https?://\S+", "", text)  # Remove URLs completamente
    
    # Markdown de links/imagens — manter apenas o texto
    text = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", text)  # Remove imagens
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)  # Mantém só o texto do link
    
    # Negrito / itálico / riscado
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
    text = re.sub(r"~{2}([^~]+)~{2}", r"\1", text)
    
    # Headers — remove # mas mantém o texto
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    
    # Linhas horizontais
    text = re.sub(r"^[-_*]{3,}\s*$", "", text, flags=re.MULTILINE)
    
    # ═══ CONVERSÃO DE LISTAS EM NARRATIVA FLUIDA ═══
    # Transforma listas numeradas em narrativa natural
    # "1. Ovos" → "Primeiro, você vai precisar de ovos."
    
    markers = {
        1: "Primeiro", 2: "Segundo", 3: "Terceiro", 4: "Quarto", 5: "Quinto",
        6: "Sexto", 7: "Sétimo", 8: "Oitavo", 9: "Nono", 10: "Décimo"
    }
    
    lines = text.split('\n')
    new_lines = []
    current_num = 1
    
    for line in lines:
        # Lista numerada: "1. Item" ou "1) Item"
        match = re.match(r'^\s*(\d+)[.)\s]+(.+)$', line)
        if match:
            num = int(match.group(1))
            content = match.group(2).strip()
            marker = markers.get(num, f"Em {num}º lugar")
            new_lines.append(f"{marker}, {content}.")
            current_num = num + 1
        # Bullet list: "- Item" ou "* Item"
        elif re.match(r'^\s*[-*+]\s+(.+)$', line):
            content = re.sub(r'^\s*[-*+]\s+', '', line).strip()
            if current_num == 1:
                new_lines.append(f"Primeiro, {content}.")
                current_num += 1
            else:
                new_lines.append(f"Depois, {content}.")
        else:
            new_lines.append(line)
            current_num = 1  # Reset counter quando não é lista
    
    text = '\n'.join(new_lines)
    
    # Remove marcadores remanescentes de listas (fallback)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # listas numeradas
    
    # Emojis e símbolos Unicode não falados
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u26FF\u2700-\u27BF]", "", text)
    
    # Símbolos problemáticos para TTS
    text = re.sub(r"[>|\\#~^@$%&+={}\[\]<>]{1,}", "", text)  # Remove símbolos especiais
    text = re.sub(r"[\(\)]", "", text)  # Remove parênteses
    
    # Normaliza espaços e quebras de linha
    text = re.sub(r"\n{3,}", ". ", text)  # Múltiplas quebras = pausa
    text = re.sub(r"\n", ". ", text)  # Quebra de linha = pausa
    text = re.sub(r"\s+", " ", text)  # Múltiplos espaços = 1 espaço
    text = re.sub(r"\.{2,}", ".", text)  # Múltiplos pontos = 1 ponto
    
    return text.strip()


def _detect_lang(text: str) -> str:
    """Heurística rápida: detecta se o texto é pt-BR ou en."""
    _PT_INDICATORS = {
        "o", "a", "de", "que", "e", "do", "da", "em", "um", "para",
        "com", "não", "uma", "os", "se", "na", "por", "mais", "as",
        "dos", "como", "mas", "foi", "ao", "ele", "das", "à",
        "seu", "sua", "ou", "ser", "quando", "muito", "há", "nos",
        "já", "está", "eu", "também", "só", "pelo", "pela", "até",
        "isso", "ela", "entre", "era", "depois", "sem", "mesmo",
        "certo", "então", "aqui", "posso", "você", "esse", "essa",
    }
    words = re.findall(r"\b\w+\b", text.lower())
    if not words:
        return "pt"
    pt_count = sum(1 for w in words if w in _PT_INDICATORS)
    return "pt" if (pt_count / len(words)) >= 0.07 else "en"


def _convert_numbers_to_words(text: str, lang: str = "pt") -> str:
    """Converte números e símbolos para texto por extenso para TTS natural."""
    # Temperaturas
    text = re.sub(r'(\d+)\s*°C', lambda m: f"{m.group(1)} graus Celsius", text)
    text = re.sub(r'(\d+)\s*°F', lambda m: f"{m.group(1)} graus Fahrenheit", text)
    text = re.sub(r'(\d+)°', lambda m: f"{m.group(1)} graus", text)
    
    # Porcentagens
    text = re.sub(r'(\d+)\s*%', lambda m: f"{m.group(1)} por cento", text)
    
    # Unidades de medida comuns
    text = re.sub(r'(\d+)\s*kg', lambda m: f"{m.group(1)} quilogramas", text)
    text = re.sub(r'(\d+)\s*g\b', lambda m: f"{m.group(1)} gramas", text)
    text = re.sub(r'(\d+)\s*mg', lambda m: f"{m.group(1)} miligramas", text)
    text = re.sub(r'(\d+)\s*ml', lambda m: f"{m.group(1)} mililitros", text)
    text = re.sub(r'(\d+)\s*l\b', lambda m: f"{m.group(1)} litros", text)
    text = re.sub(r'(\d+)\s*km', lambda m: f"{m.group(1)} quilômetros", text)
    text = re.sub(r'(\d+)\s*m\b', lambda m: f"{m.group(1)} metros", text)
    text = re.sub(r'(\d+)\s*cm', lambda m: f"{m.group(1)} centímetros", text)
    
    # Símbolos matemáticos/moeda
    text = text.replace("$", "dólares")
    text = text.replace("R$", "reais")
    text = text.replace("€", "euros")
    text = text.replace("=", "igual a")
    text = text.replace("+", "mais")
    text = text.replace("-", "menos")
    text = text.replace("x", "vezes")
    text = text.replace("×", "vezes")
    text = text.replace("/", "dividido por")
    
    return text


def clean_for_speech(text: str) -> str:
    """Limpeza AGRESSIVA para conversão de texto em fala natural.
    
    Remove TODO Markdown, converte números/símbolos para texto por extenso.
    Esta é a função definitiva para preparar texto para TTS.
    """
    # 1. Strip markdown primeiro
    text = _strip_markdown(text)
    
    # 2. Converte números e símbolos para palavras
    text = _convert_numbers_to_words(text)
    
    # 3. Remove qualquer resíduo de formatação
    text = re.sub(r'\*+', '', text)  # asteriscos remanescentes
    text = re.sub(r'#+', '', text)   # hashtags remanescentes
    text = re.sub(r'`+', '', text)   # backticks remanescentes
    text = re.sub(r'_+', '', text)   # underscores remanescentes
    
    # 4. Normalização final
    text = re.sub(r'\s+', ' ', text)  # múltiplos espaços
    text = re.sub(r'\.{2,}', '.', text)  # múltiplos pontos
    
    return text.strip()


def _prepare_tts_text(text: str) -> str:
    """Limpa o texto para TTS - usa clean_for_speech para conversão completa."""
    return clean_for_speech(text)


def _split_sentences(text: str, max_chunk_size: int = _CHUNK_SIZE) -> list[str]:
    """
    Divide texto em sentenças para processamento progressivo.
    Retorna lista de chunks, cada um com no máximo max_chunk_size caracteres.
    """
    # Usa clean_for_speech para limpeza completa (markdown + números + símbolos)
    clean = clean_for_speech(text)
    
    # Divide em sentenças (pontos, exclamações, interrogações)
    sentences = re.split(r'([.!?]+)', clean)
    
    chunks: list[str] = []
    current_chunk = ""
    
    for i in range(0, len(sentences), 2):
        sentence = sentences[i].strip()
        if not sentence:
            continue
        separator = sentences[i + 1] if i + 1 < len(sentences) else "."
        full_sentence = sentence + separator + " "
        
        if len(current_chunk) + len(full_sentence) > max_chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = full_sentence
        else:
            current_chunk += full_sentence
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [clean[:max_chunk_size]]


# ---------------------------------------------------------------------------
# VoiceEngine
# ---------------------------------------------------------------------------

class VoiceEngine:
    """
    Motor de TTS e STT com estratégia primary/fallback.

    Uso:
        engine = VoiceEngine()
        b64, mime = engine.text_to_speech("Olá!")
        text      = engine.speech_to_text(audio_bytes, fmt="wav")
    """

    def __init__(self) -> None:
        self._tts_engine: Literal["edge_tts", "gtts", "pyttsx3", "unavailable"] = self._probe_tts()
        self._stt_engine: Literal["whisper", "google", "unavailable"] = self._probe_stt()
        logger.info(
            "VoiceEngine iniciado | TTS=%s | STT=%s",
            self._tts_engine,
            self._stt_engine,
        )

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_tts() -> Literal["edge_tts", "gtts", "pyttsx3", "unavailable"]:
        # edge-tts primeiro: voz neural Microsoft, qualidade superior
        try:
            import edge_tts  # type: ignore[import]  # noqa: F401
            return "edge_tts"
        except ImportError:
            pass
        # pyttsx3: offline-first, sem dependência de rede
        try:
            import pyttsx3  # noqa: F401
            return "pyttsx3"
        except ImportError:
            pass
        try:
            import gtts  # noqa: F401
            return "gtts"
        except ImportError:
            pass
        logger.warning("VoiceEngine: nenhum motor TTS disponível.")
        return "unavailable"

    @staticmethod
    def _probe_stt() -> Literal["whisper", "google", "unavailable"]:
        # SpeechRecognition primeiro: Google Web Speech API gratuita
        try:
            import speech_recognition  # noqa: F401
            return "google"
        except ImportError:
            pass
        try:
            import whisper  # type: ignore[import]  # noqa: F401
            return "whisper"
        except ImportError:
            pass
        logger.warning("VoiceEngine: nenhum motor STT disponível.")
        return "unavailable"

    # ------------------------------------------------------------------
    # TTS — Public
    # ------------------------------------------------------------------

    def text_to_speech(self, text: str, lang: str | None = None) -> tuple[str, str]:
        """
        Converte texto em fala.

        Args:
            text: Texto a sintetizar (markdown será removido).
            lang: Código ISO 639-1 ('pt', 'en', …). Se None, auto-detecta.

        Returns:
            (base64_audio, mime_type)  —  e.g. ("AAA...", "audio/mpeg")

        Raises:
            RuntimeError: se nenhum motor TTS estiver disponível.
        """
        prepared = _prepare_tts_text(text)
        detected_lang = lang or _detect_lang(prepared)

        if self._tts_engine == "edge_tts":
            return self._tts_edge(prepared)
        if self._tts_engine == "gtts":
            return self._tts_gtts(prepared, detected_lang)
        if self._tts_engine == "pyttsx3":
            return self._tts_pyttsx3(prepared)

        raise RuntimeError(
            "Nenhum motor TTS disponível. "
            "Instale edge-tts com: pip install edge-tts"
        )

    async def text_to_speech_streaming(
        self, text: str, lang: str | None = None
    ) -> list[tuple[str, str]]:
        """
        Converte texto em fala de forma progressiva (streaming).
        Divide o texto em chunks e processa cada um, permitindo reprodução
        mais rápida da primeira parte enquanto o resto é gerado.

        Args:
            text: Texto a sintetizar (markdown será removido).
            lang: Código ISO 639-1 ('pt', 'en', …). Se None, auto-detecta.

        Returns:
            Lista de tuplas (base64_audio, mime_type) para cada chunk.
            O frontend pode reproduzir cada chunk sequencialmente.

        Raises:
            RuntimeError: se nenhum motor TTS estiver disponível.
        """
        import asyncio
        
        # Divide texto em sentenças para processamento progressivo
        chunks = _split_sentences(text, max_chunk_size=_CHUNK_SIZE)
        detected_lang = lang or _detect_lang(text)
        
        # Processa todos os chunks para leitura completa
        results: list[tuple[str, str]] = []
        
        for chunk in chunks:  # Processa TODOS os chunks para leitura completa
            if self._tts_engine == "edge_tts":
                audio_chunk = await asyncio.to_thread(self._tts_edge, chunk)
            elif self._tts_engine == "gtts":
                audio_chunk = await asyncio.to_thread(self._tts_gtts, chunk, detected_lang)
            elif self._tts_engine == "pyttsx3":
                audio_chunk = await asyncio.to_thread(self._tts_pyttsx3, chunk)
            else:
                raise RuntimeError(
                    "Nenhum motor TTS disponível. "
                    "Instale edge-tts com: pip install edge-tts"
                )
            results.append(audio_chunk)
        
        return results

    async def text_to_speech_progressive(
        self, text: str, lang: str | None = None
    ) -> tuple[str, str]:
        """
        Converte APENAS a primeira sentença em áudio para reprodução imediata.
        Otimizado para latência mínima (~1-2s até primeira reprodução).

        Args:
            text: Texto a sintetizar (markdown será removido).
            lang: Código ISO 639-1 ('pt', 'en', …). Se None, auto-detecta.

        Returns:
            Tupla (base64_audio, mime_type) da primeira sentença apenas.
            Para texto completo, use text_to_speech() ou text_to_speech_streaming().

        Raises:
            RuntimeError: se nenhum motor TTS estiver disponível.
        """
        import asyncio
        
        # Divide texto e pega apenas a primeira sentença (latência mínima)
        chunks = _split_sentences(text, max_chunk_size=_CHUNK_SIZE)
        if not chunks:
            raise RuntimeError("Texto vazio após processamento.")
        
        first_chunk = chunks[0]
        detected_lang = lang or _detect_lang(first_chunk)
        
        # Gera apenas o primeiro chunk (resposta < 2s)
        if self._tts_engine == "edge_tts":
            return await asyncio.to_thread(self._tts_edge, first_chunk)
        elif self._tts_engine == "gtts":
            return await asyncio.to_thread(self._tts_gtts, first_chunk, detected_lang)
        elif self._tts_engine == "pyttsx3":
            return await asyncio.to_thread(self._tts_pyttsx3, first_chunk)
        else:
            raise RuntimeError(
                "Nenhum motor TTS disponível. "
                "Instale edge-tts com: pip install edge-tts"
            )

    # ------------------------------------------------------------------
    # TTS — Engines
    # ------------------------------------------------------------------

    def _tts_edge(self, text: str) -> tuple[str, str]:
        """
        Síntese via Microsoft Edge TTS (voz neural pt-BR-AntonioNeural).
        Gera MP3 otimizado e retorna base64 para o frontend.
        Velocidade otimizada: +10% mais rápido para menor latência.
        """
        import asyncio
        import edge_tts  # type: ignore[import]

        _VOICE = "pt-BR-AntonioNeural"
        _RATE = "+10%"  # 10% mais rápido para reduzir latência total

        async def _generate(path: str) -> None:
            communicate = edge_tts.Communicate(text, _VOICE, rate=_RATE)
            await communicate.save(path)

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            # Novo event loop isolado — safe dentro de thread síncrona do FastAPI
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_generate(tmp.name))
            finally:
                loop.close()

            # Áudio é entregue ao browser via base64 — playback é responsabilidade do frontend
            with open(tmp.name, "rb") as f:
                data = f.read()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        return base64.b64encode(data).decode("utf-8"), "audio/mpeg"

    def _tts_gtts(self, text: str, lang: str) -> tuple[str, str]:
        from gtts import gTTS  # type: ignore[import]

        # gTTS aceita "pt" e "en"; normaliza
        lang_code = "pt" if lang.startswith("pt") else lang[:2]
        tts = gTTS(text=text, lang=lang_code, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8"), "audio/mpeg"

    def _tts_pyttsx3(self, text: str) -> tuple[str, str]:
        import pyttsx3  # type: ignore[import]

        engine = pyttsx3.init()
        # Tenta selecionar voz em português
        for voice in list(engine.getProperty("voices") or []):  # type: ignore[arg-type]
            vid = voice.id.lower()
            if "pt" in vid or "brazil" in vid or "portuguese" in vid:
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 165)
        engine.setProperty("volume", 0.95)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            engine.save_to_file(text, tmp.name)
            engine.runAndWait()
            with open(tmp.name, "rb") as f:
                data = f.read()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        return base64.b64encode(data).decode("utf-8"), "audio/wav"

    # ------------------------------------------------------------------
    # STT — Public
    # ------------------------------------------------------------------

    def speech_to_text(self, audio_data: bytes, audio_format: str = "wav") -> str:
        """
        Transcreve bytes de áudio para texto.

        Args:
            audio_data:   Bytes do arquivo de áudio.
            audio_format: Formato ('wav', 'webm', 'mp3', 'ogg', …).

        Returns:
            Texto transcrito.

        Raises:
            RuntimeError: se a transcrição falhar.
        """
        if self._stt_engine == "whisper":
            return self._stt_whisper(audio_data, audio_format)
        if self._stt_engine == "google":
            return self._stt_google(audio_data)

        raise RuntimeError(
            "Nenhum motor STT disponível. "
            "Instale SpeechRecognition com: pip install SpeechRecognition"
        )

    # ------------------------------------------------------------------
    # STT — Engines
    # ------------------------------------------------------------------

    def _stt_google(self, audio_data: bytes) -> str:
        import speech_recognition as sr  # type: ignore[import]

        recognizer = sr.Recognizer()
        audio_file = io.BytesIO(audio_data)

        try:
            with sr.AudioFile(audio_file) as source:
                audio = recognizer.record(source)
        except Exception as exc:
            raise RuntimeError(f"Erro ao ler arquivo de áudio: {exc}") from exc

        # Tenta pt-BR, fallback para en-US
        for lang in ("pt-BR", "en-US"):
            try:
                return recognizer.recognize_google(audio, language=lang)  # type: ignore[attr-defined]
            except sr.UnknownValueError:  # type: ignore[attr-defined]
                continue
            except sr.RequestError as exc:  # type: ignore[attr-defined]
                raise RuntimeError(f"Erro na API Google Speech: {exc}") from exc

        raise RuntimeError("Não foi possível reconhecer a fala no áudio enviado.")

    def _stt_whisper(self, audio_data: bytes, audio_format: str) -> str:
        import whisper  # type: ignore[import]

        suffix = f".{audio_format}" if not audio_format.startswith(".") else audio_format
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(audio_data)
        tmp.close()

        try:
            model = whisper.load_model("base")
            result = model.transcribe(tmp.name)
            return str(result.get("text", "")).strip()
        except Exception as exc:
            raise RuntimeError(f"Whisper falhou: {exc}") from exc
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> dict:
        """Retorna o estado atual dos motores TTS/STT."""
        return {
            "tts_engine":    self._tts_engine,
            "stt_engine":    self._stt_engine,
            "tts_available": self._tts_engine != "unavailable",
            "stt_available": self._stt_engine != "unavailable",
        }
