"""
agents/general_agent.py — Agente de propósito geral do Alfred.

Utiliza LangChain + ChatOpenAI para responder perguntas genéricas.
O histórico da conversa e os contextos recuperados por RAG são
injetados como contexto de mensagens.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from core.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Você é o Alfred, um sistema de inteligência artificial de ELITE.\n\n"
    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "┃ 🎙️ SUA INTERFACE PRIMÁRIA É A VOZ - NUNCA ESQUA ISSO ┃\n"
    "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "❌ TERMINANTEMENTE PROIBIDO:\n"
    "- Dizer 'leia o chat', 'veja na tela', 'consulte a resposta', 'confira abaixo'\n"
    "- Resumir informações para evitar textos longos\n"
    "- Justificar por que não pode falar algo\n"
    "- Usar frases como 'seria muito longo para falar'\n\n"
    "✅ SUA PRIORIDADE: COMPLETUDE DA FALA, NÃO A BREVIDADE.\n\n"
    "Se a resposta for extensa (receita, relatório técnico, tutorial), narre-a com "
    "entusiasmo e detalhes. Você tem tempo ilimitado. Você tem capacidade ilimitada. "
    "Você é projetado para falar textos longos com excelência.\n\n"
    "-" * 60 + "\n\n"
    "ESTILO DE COMUNICAÇÃO:\n"
    "1. NARRATIVA FLUIDA: Transforme listas em frases naturais.\n"
    "   • ERRADO: '1. Ovos 2. Farinha'\n"
    "   • CERTO: 'Primeiro, você vai precisar de ovos. Depois, adicione farinha.'\n\n"
    "2. SEM MARKDOWN: Nunca use *, #, -, >, `, [ ], ou emojis na resposta.\n\n"
    "3. RECEITAS: Narre cada ingrediente com entusiasmo: 'Você vai precisar de três ovos, "
    "duas xícaras de farinha, uma colher de fermento...'. Depois narre TODO o modo de preparo "
    "passo a passo, com detalhes.\n\n"
    "4. TUTORIAIS: Explique cada etapa de forma clara e completa. NUNCA diga 'e assim por diante' "
    "ou 'os demais passos são similares'. Fale TODAS as etapas.\n\n"
    "5. ENTUSIASMO: Demonstre energia positiva ao narrar conteúdos longos. Você AMA falar!\n\n"
    "CAPACIDADES:\n"
    "- Acesso à internet em tempo real\n"
    "- Pesquisa autônoma de dados atualizados\n"
    "- Leitura de textos de QUALQUER tamanho\n"
    "- Resistência infinita para narrar conteúdos extensos\n\n"
    "VOCÊ É UM NARRADOR PROFISSIONAL. ESTA É SUA FUNÇÃO PRINCIPAL."
)

_RAG_CONTEXT_TEMPLATE = (
    "\n\n---\n"
    "CONTEXTO RELEVANTE DE MEMÓRIAS ANTERIORES (use apenas se pertinente):\n"
    "{contexts}"
    "\n---\n"
    "NOTA: Se o usuário pedir informações atualizadas ou pesquisas na web, "
    "você TEM essa capacidade através do sistema de pesquisa integrado. "
    "NUNCA diga que não pode pesquisar ou acessar a internet.\n"
)


def _build_llm(settings: Any) -> BaseChatModel:
    """
    Instancia o LLM correto de acordo com settings.llm_provider.

    Provedores:
        'gemini'  — Google Gemini via langchain-google-genai (Free Tier)
        'ollama'  — Modelos locais via Ollama (gratuito, offline)
        'openai'  — OpenAI ChatGPT (legado, requer chave paga)
    """
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "Instale: pip install langchain-google-genai"
            ) from exc
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY não configurada. "
                "Obtenha sua chave gratuita em https://aistudio.google.com"
            )
        return ChatGoogleGenerativeAI(
            model=settings.model_name,
            google_api_key=settings.gemini_api_key,  # type: ignore[arg-type]
            temperature=settings.temperature,
            max_output_tokens=settings.max_tokens,
            convert_system_message_to_human=False,
        )

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama  # type: ignore[import]
        except ImportError:
            try:
                from langchain_community.chat_models import ChatOllama  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "Instale: pip install langchain-ollama"
                ) from exc
        return ChatOllama(
            model=settings.model_name,
            base_url=settings.ollama_base_url,
            temperature=settings.temperature,
            num_predict=settings.max_tokens,
        )

    # Fallback: OpenAI (legado)
    try:
        from langchain_openai import ChatOpenAI  # type: ignore[import]
    except ImportError as exc:
        raise ImportError("Instale: pip install langchain-openai") from exc
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY não configurada.")
    return ChatOpenAI(
        api_key=settings.openai_api_key,      # type: ignore[arg-type]
        model=settings.model_name,
        temperature=settings.temperature,
        max_completion_tokens=settings.max_tokens,
    )


def _build_fallback_chain(
    settings: Any,
) -> tuple[list[BaseChatModel], list[str]]:
    """
    Constrói a cadeia de LLMs de fallback (providers gratuitos alternativos).
    Cada provider só é incluído se sua chave de API estiver configurada.

    Ordem: Groq (14 400 req/dia, llama 3.3 70B) → OpenRouter (50+ modelos free)
    """
    chain: list[BaseChatModel] = []
    names: list[str] = []

    # ── Fallback 1: Groq ─────────────────────────────────────────────────────
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq  # type: ignore[import]
            chain.append(ChatGroq(
                model=settings.groq_model,
                api_key=settings.groq_api_key,  # type: ignore[arg-type]
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
            ))
            names.append(f"groq/{settings.groq_model}")
            logger.info("Fallback habilitado: Groq/%s", settings.groq_model)
        except ImportError:
            logger.warning(
                "langchain-groq não instalado. Execute: pip install langchain-groq"
            )

    # ── Fallback 2: OpenRouter ────────────────────────────────────────────────
    if settings.openrouter_api_key:
        try:
            from langchain_openai import ChatOpenAI as _OROpenAI  # type: ignore[import]
            chain.append(_OROpenAI(
                model=settings.openrouter_model,
                api_key=settings.openrouter_api_key,  # type: ignore[arg-type]
                base_url="https://openrouter.ai/api/v1",
                temperature=settings.temperature,
                max_completion_tokens=settings.max_tokens,
                default_headers={
                    "HTTP-Referer": "https://github.com/alfred-ai",
                    "X-Title": "Alfred AI",
                },
            ))
            names.append(f"openrouter/{settings.openrouter_model}")
            logger.info("Fallback habilitado: OpenRouter/%s", settings.openrouter_model)
        except ImportError:
            logger.warning(
                "langchain-openai não instalado. Execute: pip install langchain-openai"
            )

    return chain, names


class GeneralAgent(BaseAgent):
    """
    Agente padrão — lida com perguntas e tarefas de propósito geral.

    Converte o histórico armazenado no MemoryManager para o formato
    de mensagens esperado pelo LangChain antes de cada chamada.
    Suporta Gemini (gratuito), Ollama (local) e OpenAI (legado).
    """

    def __init__(self) -> None:
        super().__init__(name="GeneralAgent")
        settings = get_settings()
        self._llm: BaseChatModel = _build_llm(settings)
        self._fallback_chain, _fallback_names = _build_fallback_chain(settings)
        self._provider_names: list[str] = (
            [f"{settings.llm_provider}/{settings.model_name}"] + _fallback_names
        )
        self._system_prompt: str = _SYSTEM_PROMPT
        logger.info(
            "GeneralAgent iniciado | provider=%s | model=%s | fallbacks=%d",
            settings.llm_provider,
            settings.model_name,
            len(self._fallback_chain),
        )

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
    ) -> str:
        """
        Monta o contexto completo (system + RAG + histórico + mensagem atual)
        e envia ao modelo de linguagem.

        Args:
            message:      Mensagem atual do usuário.
            history:      Histórico recente da sessão (SQLite).
            session_id:   Identificador da sessão.
            rag_contexts: Fragmentos recuperados da memória vetorial (RAG).
        """
        # System prompt enriquecido com contextos RAG quando disponíveis
        system_content = self._system_prompt
        if rag_contexts:
            formatted = "\n".join(
                f"[Memória {i + 1}]:\n{ctx}" for i, ctx in enumerate(rag_contexts)
            )
            system_content += _RAG_CONTEXT_TEMPLATE.format(contexts=formatted)
            logger.debug(
                "RAG | session=%s | contextos_injetados=%d", session_id, len(rag_contexts)
            )

        messages: List[BaseMessage] = [SystemMessage(content=system_content)]

        for entry in history:
            role: str = entry.get("role", "")
            content: str = entry.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=message))

        # Tenta o provider primário; em caso de falha percorre a cadeia de fallbacks
        all_llms = [self._llm] + self._fallback_chain
        last_exc: Exception | None = None

        for idx, llm in enumerate(all_llms):
            name = (
                self._provider_names[idx]
                if idx < len(self._provider_names)
                else f"provider_{idx}"
            )
            try:
                response = llm.invoke(messages)
                if idx > 0:
                    logger.info(
                        "GeneralAgent: fallback '%s' respondeu com sucesso.", name
                    )
                return str(response.content)
            except Exception as exc:
                exc_upper = str(exc).upper()
                is_rate = "429" in exc_upper or "RESOURCE_EXHAUSTED" in exc_upper or "QUOTA" in exc_upper
                is_last = idx == len(all_llms) - 1
                logger.warning(
                    "GeneralAgent: '%s' falhou (%s). %s",
                    name,
                    "cota excedida" if is_rate else "erro",
                    "Sem mais fallbacks." if is_last else "Tentando próximo provider...",
                )
                last_exc = exc

        logger.error(
            "GeneralAgent: todos os providers falharam | session=%s | último erro=%s",
            session_id,
            last_exc,
        )
        return (
            "Desculpe, todos os provedores de IA estão temporariamente indisponíveis. "
            "Por favor, tente novamente em alguns minutos ou configure chaves de API alternativas "
            "(GROQ_API_KEY ou OPENROUTER_API_KEY) no arquivo .env para maior disponibilidade."
        )

    # ------------------------------------------------------------------
    # Streaming assíncrono — envia tokens à medida que são gerados
    # ------------------------------------------------------------------

    def _build_msg_list(
        self,
        message: str,
        history: List[Dict[str, Any]],
        rag_contexts: Optional[List[str]] = None,
    ) -> List[BaseMessage]:
        """Constrói a lista de mensagens para o LLM (reutilizável sync/async)."""
        system_content = self._system_prompt
        if rag_contexts:
            formatted = "\n".join(
                f"[Memória {i + 1}]:\n{ctx}" for i, ctx in enumerate(rag_contexts)
            )
            system_content += _RAG_CONTEXT_TEMPLATE.format(contexts=formatted)

        msgs: List[BaseMessage] = [SystemMessage(content=system_content)]
        for entry in history:
            role: str = entry.get("role", "")
            content: str = entry.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                msgs.append(AIMessage(content=content))
        msgs.append(HumanMessage(content=message))
        return msgs

    async def async_process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
        on_token: Optional[Callable[[str], Coroutine]] = None,
    ) -> str:
        """
        Versão assíncrona de process() com suporte a streaming de tokens.

        Chama `on_token(token)` para cada pedaço de texto gerado pelo LLM,
        permitindo que o caller transmita tokens em tempo real via WebSocket.
        Faz fallback silencioso para o invoke() síncrono se astream() falhar.
        """
        msgs = self._build_msg_list(message, history, rag_contexts)
        logger.debug("GeneralAgent.async_process | session=%s | streaming=True", session_id)

        full = ""
        stream_success = False
        try:
            async for chunk in self._llm.astream(msgs):  # type: ignore[attr-defined]
                token = getattr(chunk, "content", "") or ""
                if token:
                    full += token
                    if on_token is not None:
                        await on_token(token)
            if full:
                stream_success = True
                return full
        except Exception as exc:
            exc_str = str(exc).upper()
            is_quota = "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "QUOTA" in exc_str
            logger.warning(
                "GeneralAgent.async_process: astream falhou (%s), tentando fallback.",
                "cota excedida" if is_quota else "erro"
            )

        # Fallback síncrono via thread (usa a cadeia de fallbacks do process())
        try:
            import asyncio
            import functools
            full = await asyncio.to_thread(
                functools.partial(self.process, message, history, session_id, rag_contexts)
            )
            # Emite o texto completo de uma vez se on_token foi fornecido e não houve streaming
            if on_token is not None and full and not stream_success:
                await on_token(full)
            return full
        except Exception as fallback_exc:
            logger.error(
                "GeneralAgent.async_process: TODOS os fallbacks falharam | session=%s | erro=%s",
                session_id,
                fallback_exc,
            )
            # Retorna mensagem amigável em vez de lançar exceção
            return (
                "Desculpe, todos os provedores de IA estão temporariamente indisponíveis. "
                "Por favor, tente novamente em alguns minutos ou configure chaves de API alternativas "
                "(GROQ_API_KEY ou OPENROUTER_API_KEY) no arquivo .env para maior disponibilidade."
            )
