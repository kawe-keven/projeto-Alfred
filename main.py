"""
main.py — Ponto de entrada da API Alfred.

Endpoints:
    GET  /health                    — health check
    POST /chat                      — enviar mensagem ao Alfred
    GET  /session/{session_id}      — consultar histórico da sessão
    DELETE /session/{session_id}    — limpar histórico da sessão

Para iniciar:
    uvicorn main:app --reload
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Literal

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Path, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.config import get_settings
from core.monitor_service import monitor_service
from core.orchestrator import AlfredOrchestrator
from core.voice_engine import VoiceEngine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger("alfred.main")

# ---------------------------------------------------------------------------
# Lifespan — inicialização e encerramento da aplicação
# ---------------------------------------------------------------------------
_orchestrator: AlfredOrchestrator | None = None
_voice_engine: VoiceEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _orchestrator, _voice_engine
    settings = get_settings()
    logger.info("Iniciando %s v%s", settings.app_name, settings.app_version)
    _orchestrator = AlfredOrchestrator()
    _voice_engine = VoiceEngine()
    await monitor_service.start()
    yield
    await monitor_service.stop()
    logger.info("Encerrando Alfred.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "Sistema de IA modular e multi-agente. "
        "Envie mensagens pelo endpoint /chat e o orquestrador decidirá qual agente responder."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_orchestrator() -> AlfredOrchestrator:
    if _orchestrator is None:  # pragma: no cover
        raise RuntimeError("Orquestrador não inicializado.")
    return _orchestrator


def _get_voice_engine() -> VoiceEngine:
    if _voice_engine is None:  # pragma: no cover
        raise RuntimeError("VoiceEngine não inicializado.")
    return _voice_engine


def _get_dev_agent():
    """Retorna o DevAgent do orquestrador, ou None se não inicializado."""
    if _orchestrator is None:
        return None
    return _orchestrator.get_dev_agent()


# ---------------------------------------------------------------------------
# Schemas Pydantic
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Identificador único da sessão do usuário.",
        examples=["user_42"],
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Mensagem enviada pelo usuário.",
        examples=["Olá, Alfred! O que você pode fazer?"],
    )
    image_data: str | None = Field(
        default=None,
        description="Imagem em base64 (PNG/JPEG) opcional para análise pelo VisionAgent.",
    )
    audio_response: bool = Field(
        default=False,
        description="Se True, gera áudio TTS da resposta e retorna em base64.",
    )


class ScreenshotResponse(BaseModel):
    image_data: str = Field(description="Imagem capturada em base64 PNG.")
    width: int
    height: int


class IntentInfo(BaseModel):
    agent:      str
    action:     str
    confidence: float


class ChatResponse(BaseModel):
    session_id: str
    message: str
    response: str
    agent_used: str
    rag_contexts_used: int = Field(
        default=0,
        description="Número de contextos de memória de longo prazo recuperados via RAG.",
    )
    rag_contexts: List[str] = Field(
        default_factory=list,
        description="Fragmentos de memória recuperados pelo sistema RAG.",
    )
    intent: IntentInfo = Field(
        default_factory=lambda: IntentInfo(agent="general", action="", confidence=1.0),
        description="Classificação de intenção detectada pelo orquestrador.",
    )
    audio_data: str | None = Field(
        default=None,
        description="Áudio da resposta em base64 (gerado pelo TTS), se audio_response=True. DEPRECATED: use audio_chunks.",
    )
    audio_mime: str | None = Field(
        default=None,
        description="MIME type do áudio: audio/mpeg (MP3) ou audio/wav. DEPRECATED: use audio_chunks.",
    )
    audio_chunks: List[dict] | None = Field(
        default=None,
        description="Array de chunks de áudio [{data: base64, mime: string}] para reprodução sequencial.",
    )


class TranscribeRequest(BaseModel):
    audio_data: str = Field(description="Bytes do áudio em base64.")
    audio_format: str = Field(default="wav", description="Formato do áudio (wav, webm, mp3, ogg).")


class TranscribeResponse(BaseModel):
    text: str = Field(description="Texto transcrito do áudio.")
    engine: str = Field(description="Motor STT utilizado.")


class VoiceStatusResponse(BaseModel):
    tts_engine: str
    stt_engine: str
    tts_available: bool
    stt_available: bool


class HistoryEntry(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    timestamp: str
    metadata: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# ---------------------------------------------------------------------------
# Helpers de roteamento
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["Sistema"],
)
def health_check() -> HealthResponse:
    """Verifica se o serviço está operacional."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Enviar mensagem ao Alfred",
    tags=["Chat"],
)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Envia uma mensagem ao Alfred.

    O orquestrador seleciona o agente adequado, busca o histórico da
    sessão na memória e retorna a resposta gerada.
    """
    orchestrator = _get_orchestrator()

    # Se a query envolver dados em tempo real, notifica os clientes WS antes de iniciar
    if orchestrator.needs_research(request.message):
        await monitor_service.broadcast({
            "type":      "info",
            "category":  "research",
            "title":     "Alfred está pesquisando",
            "message":   "Consultando fontes atualizadas antes de responder...",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "value":     request.message[:80],
        })

    # Callback de streaming — transmite cada token via WS (aura azul → texto progressivo)
    async def _on_token(token: str) -> None:
        try:
            await monitor_service.broadcast({
                "type":       "info",
                "category":   "stream_token",
                "title":      "",
                "message":    token,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "value":      token,
                "session_id": request.session_id,
                "done":       False,
            })
        except Exception:
            pass  # nunca deixa o streaming quebrar o fluxo principal

    try:
        result = await orchestrator.async_chat(
            request.session_id,
            request.message,
            request.image_data,
            on_token=_on_token if not request.image_data else None,
        )
    except Exception as exc:
        logger.exception("Erro ao processar /chat | session=%s", request.session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Sinaliza fim do stream ao frontend
    try:
        await monitor_service.broadcast({
            "type":       "info",
            "category":   "stream_token",
            "title":      "",
            "message":    "",
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "value":      "",
            "session_id": request.session_id,
            "done":       True,
        })
    except Exception:
        pass

    response_text = result["response"]

    # ── TTS — FILA DE ÁUDIO (Audio Queue System) ────────────────────────────
    # Retorna chunks individuais para reprodução sequencial no frontend
    # Isso elimina cortes em textos longos e permite início instantâneo
    audio_data: str | None = None
    audio_mime: str | None = None
    audio_chunks_list: List[dict] | None = None
    
    if request.audio_response:
        response_len = len(response_text)
        logger.info("🎙️ TTS AUDIO QUEUE iniciado | %d chars | session=%s", response_len, request.session_id)
        
        try:
            voice = _get_voice_engine()
            
            # GERA CHUNKS INDIVIDUAIS (não concatena) — frontend toca sequencialmente
            logger.info("➡️ Gerando chunks de áudio para fila sequencial")
            chunks_results = await voice.text_to_speech_streaming(response_text)
            
            if chunks_results:
                # Converte para formato frontend-friendly
                audio_chunks_list = [
                    {"data": chunk_data, "mime": chunk_mime}
                    for chunk_data, chunk_mime in chunks_results
                ]
                
                # Mantém backward compatibility: primeiro chunk como áudio principal
                audio_data = chunks_results[0][0]
                audio_mime = chunks_results[0][1]
                
                logger.info(
                    "✅ TTS audio queue pronto | %d chunks | ~%.1fs cada | session=%s",
                    len(audio_chunks_list),
                    len(response_text) / len(audio_chunks_list) / 15,  # ~15 chars/s reading speed
                    request.session_id
                )
            else:
                logger.warning("⚠️ TTS retornou 0 chunks")
                
        except Exception as tts_exc:
            logger.error("❌ TTS audio queue falhou: %s", tts_exc)
            
            # PROTOCOLO: Nunca ficar mudo - fallback para método tradicional
            try:
                logger.info("🔄 Tentando TTS tradicional como fallback...")
                audio_data, audio_mime = await asyncio.to_thread(
                    voice.text_to_speech, response_text
                )
                # Cria um único chunk para compatibilidade
                audio_chunks_list = [{"data": audio_data, "mime": audio_mime}]
                logger.info("✅ TTS fallback concluído | session=%s", request.session_id)
            except Exception as tts_fallback_exc:
                logger.error("❌ TTS fallback falhou: %s", tts_fallback_exc)
                
                # Última tentativa: mensagem de erro amigável
                error_message = (
                    "Senhor, tive um problema com meu sintetizador de voz. "
                    "Estou tentando novamente. A resposta completa está disponível no chat."
                )
                try:
                    audio_data, audio_mime = await asyncio.to_thread(
                        voice.text_to_speech, error_message
                    )
                    audio_chunks_list = [{"data": audio_data, "mime": audio_mime}]
                    logger.warning("⚠️ TTS retornou mensagem de erro amigável")
                except Exception:
                    logger.error("❌ Falha crítica: até mensagem de erro falhou no TTS")

    return ChatResponse(
        session_id=request.session_id,
        message=request.message,
        response=response_text,
        agent_used=result["agent_used"],
        rag_contexts_used=result.get("rag_contexts_used", 0),
        rag_contexts=result.get("rag_contexts", []),
        intent=IntentInfo(**result.get("intent", {"agent": "general", "action": "", "confidence": 1.0})),
        audio_data=audio_data,
        audio_mime=audio_mime,
        audio_chunks=audio_chunks_list,
    )


@app.post(
    "/screenshot",
    response_model=ScreenshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Capturar screenshot da tela",
    tags=["Visão"],
)
def take_screenshot() -> ScreenshotResponse:
    """
    Captura um screenshot da tela atual e retorna como base64 PNG.
    Usado pelo frontend para o botão de câmera/screenshot.
    """
    try:
        import base64
        import io
        import pyautogui  # type: ignore[import]

        screenshot = pyautogui.screenshot()
        width, height = screenshot.size
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return ScreenshotResponse(image_data=b64, width=width, height=height)
    except Exception as exc:
        logger.exception("Erro ao capturar screenshot")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Não foi possível capturar a tela: {exc}",
        ) from exc


@app.get(
    "/session/{session_id}",
    response_model=List[HistoryEntry],
    summary="Consultar histórico da sessão",
    tags=["Sessão"],
)
def get_session_history(
    session_id: str = Path(..., min_length=1, max_length=128),
    limit: int = 20,
) -> List[HistoryEntry]:
    """Retorna as últimas mensagens de uma sessão."""
    orchestrator = _get_orchestrator()
    history = orchestrator.get_history(session_id=session_id, limit=limit)
    return [HistoryEntry(**entry) for entry in history]


@app.delete(
    "/session/{session_id}",
    status_code=status.HTTP_200_OK,
    summary="Limpar histórico da sessão",
    tags=["Sessão"],
)
def clear_session(
    session_id: str = Path(..., min_length=1, max_length=128),
) -> Dict[str, str]:
    """Remove todo o histórico de conversa de uma sessão."""
    try:
        orchestrator = _get_orchestrator()
        orchestrator.clear_session(session_id=session_id)
        return {"message": f"Sessão '{session_id}' limpa com sucesso."}
    except Exception as exc:
        logger.exception("Erro ao limpar sessão %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao limpar sessão: {str(exc)}",
        ) from exc


@app.post(
    "/transcribe",
    response_model=TranscribeResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcrever áudio para texto (STT)",
    tags=["Voz"],
)
def transcribe_audio(request: TranscribeRequest) -> TranscribeResponse:
    """
    Transcreve um arquivo de áudio (base64) para texto.

    Útil para clientes que não suportam Web Speech API,
    ou que desejam STT de alta precisão via Whisper no servidor.
    """
    try:
        import base64 as _b64
        audio_bytes = _b64.b64decode(request.audio_data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"audio_data não é um base64 válido: {exc}",
        ) from exc

    voice = _get_voice_engine()
    try:
        text = voice.speech_to_text(audio_bytes, audio_format=request.audio_format)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return TranscribeResponse(text=text, engine=voice.status["stt_engine"])


@app.get(
    "/voice/status",
    response_model=VoiceStatusResponse,
    summary="Status dos motores de voz (TTS/STT)",
    tags=["Voz"],
)
def voice_status() -> VoiceStatusResponse:
    """Retorna quais motores TTS e STT estão disponíveis no servidor."""
    return VoiceStatusResponse(**_get_voice_engine().status)


# ---------------------------------------------------------------------------
# Widget & Briefing — IntegrationAgent
# ---------------------------------------------------------------------------

@app.get(
    "/widget/status",
    summary="Dados do widget de clima e calendário",
    tags=["Integração"],
)
async def widget_status() -> Dict[str, Any]:
    """
    Retorna dados estruturados para o widget da Sidebar:
    clima atual (multi-cidade) + próxima tarefa do calendário.

    Também verifica alertas climáticos (temp > 32 °C ou Tempestade)
    e os envia via WebSocket para o frontend.
    """
    orchestrator = _get_orchestrator()
    agent = orchestrator._agents.get("integration")
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IntegrationAgent não está disponível.",
        )
    from agents.integration_agent import IntegrationAgent
    if isinstance(agent, IntegrationAgent):
        data   = agent.get_widget_data()
        alerts = agent.collect_weather_alerts(data.get("cities", []))
        for alert in alerts:
            await monitor_service.broadcast(alert)
        return data
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="IntegrationAgent tipo inesperado.",
    )


# ---------------------------------------------------------------------------
# Briefing proativo
# ---------------------------------------------------------------------------

# Cache em memória: (dados_do_briefing, timestamp_unix)
_briefing_cache: tuple[dict, float] | None = None
_BRIEFING_CACHE_TTL = 1800.0  # 30 minutos
# Flag: se o sinal de "briefing_ready" já foi enviado nesta sessão do servidor
_briefing_signal_sent = False


class BriefingResponse(BaseModel):
    text:         str
    topics:       List[str]
    weather_city: str
    cpu:          float
    ram:          float
    audio_data:   str | None = None
    audio_mime:   str | None = None


@app.get(
    "/briefing",
    response_model=BriefingResponse,
    summary="Briefing matinal proativo",
    tags=["Chat"],
)
async def get_briefing() -> BriefingResponse:
    """
    Coleta dados de hardware, clima e pesquisas recentes,
    sintetiza um briefing via GeneralAgent e gera áudio TTS.
    Cache de 30 minutos para evitar chamadas repetidas.
    """
    import time as _time

    global _briefing_cache

    now = _time.monotonic()
    if _briefing_cache is not None:
        cached_data, cached_at = _briefing_cache
        if now - cached_at < _BRIEFING_CACHE_TTL:
            return BriefingResponse(**cached_data)

    orchestrator = _get_orchestrator()
    data = await asyncio.to_thread(orchestrator.get_morning_briefing)

    audio_data: str | None = None
    audio_mime: str | None = None
    try:
        voice = _get_voice_engine()
        audio_data, audio_mime = await asyncio.to_thread(voice.text_to_speech, data["text"])
    except Exception as exc:
        logger.warning("Briefing: TTS falhou: %s", exc)

    result = {**data, "audio_data": audio_data, "audio_mime": audio_mime}
    _briefing_cache = (result, now)
    return BriefingResponse(**result)


# ---------------------------------------------------------------------------
# WebSocket — notificações proativas do monitor
# ---------------------------------------------------------------------------
# Pesquisa Web — endpoint dedicado
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    title:     str
    url:       str
    body:      str
    source:    str = ""
    published: str | None = None


class SearchRequest(BaseModel):
    query:          str  = Field(..., min_length=1, max_length=512,
                                description="Termo de busca.")
    max_results:    int  = Field(default=8, ge=1, le=20,
                                description="Número máximo de resultados (1–20).")
    search_type:    Literal["web", "news"] = Field(
                                default="web",
                                description="'web' para sites, 'news' para notícias recentes.")
    synthesize:     bool = Field(default=True,
                                description="Se True, retorna síntese do LLM além dos resultados.")
    audio_response: bool = Field(default=False,
                                description="Se True, gera TTS da síntese.")


class SearchResponse(BaseModel):
    query:          str
    search_type:    str
    results:        List[SearchResult]
    result_count:   int
    synthesis:      str | None       = None
    audio_data:     str | None       = None
    audio_mime:     str | None       = None
    search_time_ms: int              = 0


@app.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Busca web / notícias em tempo real",
    tags=["Pesquisa"],
)
async def search(request: SearchRequest) -> SearchResponse:
    """
    Executa uma busca DuckDuckGo e, opcionalmente, sintetiza os resultados
    com o LLM do ResearchAgent.

    - **search_type** ``web``   — busca geral (sites, artigos, wikis)
    - **search_type** ``news``  — notícias recentes (filtradas por data)
    - **synthesize**  ``true``  — gera resposta conversacional com citações
    - **audio_response** ``true`` — retorna TTS da síntese em base64
    """
    import time as _time
    t_start = _time.monotonic()

    # Notifica clientes WS que uma pesquisa está em andamento
    await monitor_service.broadcast({
        "type":      "info",
        "category":  "research",
        "title":     "Alfred está pesquisando",
        "message":   f"Buscando: {request.query[:80]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "value":     request.query[:80],
    })

    orchestrator = _get_orchestrator()
    research_agent = orchestrator._agents.get("research")

    from agents.research_agent import ResearchAgent as _RA
    if not isinstance(research_agent, _RA):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ResearchAgent não está disponível.",
        )

    # 1. Busca bruta em thread separada
    raw_results: list = await asyncio.to_thread(
        research_agent.search_raw,
        request.query,
        request.max_results,
        request.search_type,
    )

    results = [
        SearchResult(
            title=r.get("title", ""),
            url=r.get("url", ""),
            body=r.get("body", ""),
            source=r.get("source", ""),
            published=r.get("published") or None,
        )
        for r in raw_results
    ]

    # 2. Síntese LLM (opcional)
    synthesis:  str | None = None
    audio_data: str | None = None
    audio_mime: str | None = None

    if request.synthesize and raw_results:
        try:
            synthesis = await asyncio.to_thread(
                research_agent.synthesize,
                request.query,
                raw_results,
                "__search__",
            )
        except Exception as exc:
            logger.warning("Search: síntese LLM falhou: %s", exc)

    # 3. TTS da síntese (opcional)
    if request.audio_response and synthesis:
        try:
            voice = _get_voice_engine()
            audio_data, audio_mime = await asyncio.to_thread(
                voice.text_to_speech, synthesis
            )
        except Exception as exc:
            logger.warning("Search: TTS falhou: %s", exc)

    search_time_ms = int((_time.monotonic() - t_start) * 1000)

    return SearchResponse(
        query=request.query,
        search_type=request.search_type,
        results=results,
        result_count=len(results),
        synthesis=synthesis,
        audio_data=audio_data,
        audio_mime=audio_mime,
        search_time_ms=search_time_ms,
    )


# ---------------------------------------------------------------------------
# WebSocket — notificações proativas do monitor
# ---------------------------------------------------------------------------
    """
    Endpoint WebSocket para notificações proativas em tempo real.

    O MonitorService envia alertas por este canal sempre que:
    • Uso de CPU ultrapassa 90 %
    • RAM ultrapassa 90 % de utilização
    • Bateria cai abaixo de 20 % sem carregador
    • Um novo arquivo importante chega em Downloads

    Formato de mensagem (JSON):
        {
            "type":      "error" | "warning" | "info",
            "category":  "cpu" | "ram" | "battery" | "file",
            "title":     "...",
            "message":   "...",
            "timestamp": "ISO-8601",
            "value":     <number | string>
        }
    """
    await websocket.accept()
    monitor_service.connect(websocket)
    logger.info("WebSocket /ws/notifications conectado.")

    # Envia sinal de briefing apenas na primeira conexão desde que o
    # servidor foi iniciado (evita re-trigger em reconexões do frontend).
    global _briefing_signal_sent
    if not _briefing_signal_sent:
        _briefing_signal_sent = True
        try:
            await websocket.send_json({
                "type":      "info",
                "category":  "briefing_ready",
                "title":     "Briefing Matinal",
                "message":   "Alfred está preparando seu briefing...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "value":     "",
            })
        except Exception as exc:
            logger.warning("Briefing: falha ao enviar sinal: %s", exc)

    try:
        # Mantém a conexão viva; o cliente pode enviar "ping" a qualquer momento
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/notifications desconectado.")
    finally:
        monitor_service.disconnect(websocket)


@app.get(
    "/monitor/logs",
    summary="Histórico de alertas do monitor",
    tags=["Monitor"],
)
def monitor_logs(limit: int = 20) -> List[Dict[str, Any]]:
    """Retorna os alertas mais recentes registrados pelo MonitorService."""
    return monitor_service.get_recent_logs(limit=min(limit, 100))


# ---------------------------------------------------------------------------
# WebSocket — telemetria de hardware em tempo real
# ---------------------------------------------------------------------------

@app.websocket("/ws/hardware")
async def ws_hardware(websocket: WebSocket) -> None:
    """
    Endpoint WebSocket que transmite métricas de hardware a cada 2 segundos.

    Formato de mensagem (JSON):
        {
            "cpu":          <float>,   // % de uso
            "ram":          <float>,   // % de uso
            "ram_used_gb":  <float>,
            "ram_total_gb": <float>,
            "disk":         <float>,   // % de uso (raiz)
            "disk_used_gb": <float>,
            "disk_total_gb":<float>,
            "cpu_temp":     <float|null>  // °C, null se indisponível
        }
    """
    await websocket.accept()
    logger.info("WebSocket /ws/hardware conectado.")
    try:
        while True:
            cpu = psutil.cpu_percent(interval=None)

            vm = psutil.virtual_memory()
            ram_pct   = vm.percent
            ram_used  = round(vm.used  / 1_073_741_824, 1)
            ram_total = round(vm.total / 1_073_741_824, 1)

            disk = psutil.disk_usage("/")
            disk_pct   = disk.percent
            disk_used  = round(disk.used  / 1_073_741_824, 1)
            disk_total = round(disk.total / 1_073_741_824, 1)

            cpu_temp: float | None = None
            try:
                get_temps = getattr(psutil, "sensors_temperatures", None)
                if get_temps is not None:
                    sensors = get_temps()
                    if sensors:
                        entries = next(iter(sensors.values()))
                        if entries:
                            cpu_temp = round(entries[0].current, 1)
            except Exception:
                pass

            await websocket.send_json({
                "cpu":          cpu,
                "ram":          ram_pct,
                "ram_used_gb":  ram_used,
                "ram_total_gb": ram_total,
                "disk":         disk_pct,
                "disk_used_gb": disk_used,
                "disk_total_gb":disk_total,
                "cpu_temp":     cpu_temp,
            })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("WebSocket /ws/hardware desconectado.")


# ---------------------------------------------------------------------------
# Entrypoint direto
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
