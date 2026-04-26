"""
agents/vision_agent.py — Agente de Visão Computacional do Alfred.

Responsabilidades:
    • Analisar imagens enviadas pelo usuário (upload ou drag-and-drop)
    • Capturar e analisar screenshots automáticos via pyautogui
    • Descrever, responder perguntas e extrair informações de imagens
    • Usar GPT-4o (visão) via LangChain para raciocínio multimodal

Segurança:
    • Imagens são recebidas como base64 — nenhum arquivo arbitrário é lido do disco
    • Screenshots só são tirados mediante solicitação explícita do usuário
    • Imagens são redimensionadas para limitar payload de API (max 1024px)
"""
from __future__ import annotations

import base64
import io
import logging
import re
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from core.config import get_settings


def _build_vision_llm():
    """Instancia o LLM com suporte a visão conforme o provider configurado."""
    settings = get_settings()
    provider = settings.llm_provider

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import]
        return ChatGoogleGenerativeAI(
            model=settings.model_name,
            google_api_key=settings.gemini_api_key,
            temperature=0.3,
            max_output_tokens=1024,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore[import]
        return ChatOllama(
            model=settings.model_name,
            base_url=settings.ollama_base_url,
            temperature=0.3,
        )
    # openai legacy fallback
    from langchain_openai import ChatOpenAI  # type: ignore[import]
    from pydantic import SecretStr
    return ChatOpenAI(
        model="gpt-4o",
        api_key=SecretStr(settings.openai_api_key),
        temperature=0.3,
        max_completion_tokens=1024,
    )

def _build_vision_fallback():
    """Retorna lista de LLMs de visão alternativos (Groq llama-3.2-11b-vision)."""
    fallbacks = []
    settings = get_settings()
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq  # type: ignore[import]
            from pydantic import SecretStr as _SecretStr
            fallbacks.append(
                ChatGroq(
                    model="llama-3.2-11b-vision-preview",
                    api_key=_SecretStr(settings.groq_api_key),
                    temperature=0.3,
                    max_tokens=1024,
                )
            )
        except Exception as exc:  # pragma: no cover
            logging.getLogger(__name__).warning("Groq vision não disponível: %s", exc)
    return fallbacks


logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Você é Alfred, um assistente de IA com capacidade de visão.
Ao analisar imagens:
- Descreva o conteúdo de forma clara e objetiva
- Responda perguntas específicas sobre o que você vê
- Identifique textos, interfaces, gráficos e objetos relevantes
- Seja conciso mas completo
- Responda sempre no mesmo idioma da pergunta do usuário"""


def _resize_image_base64(image_b64: str, max_px: int = 512) -> str:
    """
    Redimensiona a imagem (se necessário) para que o lado maior fique em max_px.
    Retorna base64 da imagem PNG resultante.
    """
    try:
        from PIL import Image

        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw)).convert("RGB")

        w, h = img.size
        if max(w, h) > max_px:
            ratio = max_px / max(w, h)
            # Pillow 10+ usa Image.Resampling.LANCZOS; versões anteriores usam Image.LANCZOS
            resample = getattr(Image, "Resampling", Image).LANCZOS  # type: ignore[attr-defined]
            img = img.resize((int(w * ratio), int(h * ratio)), resample)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as exc:
        logger.warning("Não foi possível redimensionar a imagem: %s", exc)
        return image_b64  # retorna original se Pillow falhar


def _take_screenshot() -> str:
    """
    Captura a tela completa e retorna como base64 PNG.

    Raises:
        RuntimeError: se pyautogui ou display não estiverem disponíveis.
    """
    try:
        import pyautogui  # type: ignore[import]

        screenshot = pyautogui.screenshot()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        raw_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return _resize_image_base64(raw_b64)
    except Exception as exc:
        raise RuntimeError(f"Não foi possível capturar a tela: {exc}") from exc


class VisionAgent(BaseAgent):
    """
    Agente multimodal que analisa imagens usando GPT-4o.

    O parâmetro `image_data` deve ser uma string base64 de uma imagem PNG/JPEG.
    Quando ausente, o agente tenta capturar um screenshot automaticamente
    se a mensagem indicar essa intenção.
    """

    def __init__(self) -> None:
        super().__init__(name="VisionAgent")
        self._llm = _build_vision_llm()
        self._fallback_chain = _build_vision_fallback()

    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
        image_data: Optional[str] = None,
    ) -> str:
        """
        Processa a mensagem junto com uma imagem (fornecida ou capturada).

        Args:
            message:    Pergunta ou instrução do usuário sobre a imagem.
            history:    Histórico da conversa (não utilizado na análise visual).
            session_id: ID da sessão para logging.
            rag_contexts: Ignorado — não aplicável para visão.
            image_data: Base64 da imagem. Se None, tenta tirar screenshot.

        Returns:
            Resposta textual do modelo sobre a imagem.
        """
        # ── Resolve imagem ────────────────────────────────────────────
        if image_data is None:
            screenshot_triggers = (
                "tela", "screen", "print", "screenshot", "captura",
                "o que está na tela", "what's on the screen",
            )
            msg_lower = message.lower()
            if any(t in msg_lower for t in screenshot_triggers):
                try:
                    image_data = _take_screenshot()
                    logger.info("VisionAgent | session=%s | screenshot capturado", session_id)
                except RuntimeError as exc:
                    return str(exc)
            else:
                return (
                    "Não recebi nenhuma imagem para analisar. "
                    "Você pode enviar uma imagem arrastando até o chat, "
                    "ou pedir para eu tirar um screenshot da sua tela."
                )

        # ── Redimensiona para economizar tokens ───────────────────────
        image_data = _resize_image_base64(image_data)

        logger.info(
            "VisionAgent | session=%s | analisando imagem (%.0f KB base64)",
            session_id,
            len(image_data) * 0.75 / 1024,
        )

        # ── Monta mensagem multimodal para GPT-4o ─────────────────────
        prompt_text = message if message.strip() else "Descreva detalhadamente o que você vê nesta imagem."
        human_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_data}",
                    "detail": "high",
                },
            },
            {
                "type": "text",
                "text": prompt_text,
            },
        ]

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=human_content),
        ]

        all_llms = [self._llm] + self._fallback_chain
        last_exc: Exception | None = None
        for llm in all_llms:
            try:
                response = llm.invoke(messages)
                return str(response.content)
            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                    match = re.search(r"retryDelay[^0-9]+([0-9]+)s", exc_str)
                    wait_s = min(int(match.group(1)) + 2 if match else 35, 40)
                    logger.warning(
                        "VisionAgent | session=%s | cota excedida, aguardando %ds...",
                        session_id, wait_s,
                    )
                    time.sleep(wait_s)
                    try:
                        response = llm.invoke(messages)
                        return str(response.content)
                    except Exception as retry_exc:
                        last_exc = retry_exc
                        continue
                last_exc = exc
                if llm is not all_llms[-1]:
                    logger.warning("VisionAgent | provider falhou, tentando fallback | erro=%s", exc)
                    continue
        logger.error(
            "VisionAgent | todos os providers falharam | session=%s | error=%s",
            session_id, last_exc,
        )
        return (
            "Não foi possível analisar a imagem no momento. "
            "A cota da API de visão foi excedida. Tente novamente em alguns minutos."
        )
