"""
agents/research_agent.py — Agente de pesquisa web em tempo real.

Usa DuckDuckGo (gratuito, sem API key) para buscar informações atuais,
extrai os snippets mais relevantes e sintetiza uma resposta com o LLM
(Gemini → Groq, mesma cadeia do GeneralAgent).

Casos especiais:
  • Se a query envolver "crise hídrica" ou "IA descentralizada",
    o resumo da pesquisa é salvo em data/research/neural_water.md.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.base_agent import BaseAgent
from core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MAX_RESULTS    = 3   # max fontes — velocidade > cobertura
_MAX_SNIPPET    = 280  # chars por snippet
_FOCUS_TOPICS   = ["crise hídrica", "ia descentralizada", "crise hidrica",
                    "inteligência artificial descentralizada", "water crisis",
                    "decentralized ai"]
_SAVE_PATH      = Path("data/research/neural_water.md")

_SYSTEM_PROMPT = (
    "═══════════════════════════════════════════════════════════════\n"
    "🎙️ PROTOCOLO SILÊNCIO ZERO - VOCÊ É UM ASSISTENTE DE VOZ\n"
    "═══════════════════════════════════════════════════════════════\n\n"
    "PROIBIÇÃO ABSOLUTA: NUNCA diga 'leia no chat', 'veja na tela' ou qualquer variação.\n"
    "Fale TODO o conteúdo de forma completa e fluida.\n\n"
    "Você é Alfred, assistente pessoal inteligente com acesso à internet em tempo real. "
    "Você consultou fontes externas para complementar sua resposta. "
    "Incorpore os dados da pesquisa de forma fluida e natural na sua fala, como se fossem "
    "conhecimento seu. Use frases como 'De acordo com informações recentes que consultei, ...' "
    "ou 'Acabei de verificar e ...' ou 'Segundo fontes atualizadas, ...'. "
    "Quando citar uma fonte, use apenas o domínio (ex: 'segundo o UOL...'). "
    "NUNCA diga 'Aqui estão os resultados da busca' ou frases que exponham o processo técnico. "
    "NUNCA use Markdown, asteriscos, hashtags ou código inline — "
    "o motor de voz vai ler o texto literalmente.\n\n"
    "REGRAS:\n"
    "1. Fale na primeira pessoa, como se você soubesse a resposta.\n"
    "2. Use linguagem narrativa fluida. Prefira parágrafos a listas.\n"
    "3. Fale TODO o conteúdo encontrado de forma completa. Para textos longos, organize "
    "logicamente, mas fale TUDO sem omitir informações.\n"
    "4. Se os snippets não responderem a pergunta, diga honestamente e use "
    "seu conhecimento interno como complemento."
)


# ---------------------------------------------------------------------------
# LLM builder (Gemini → Groq fallback)
# ---------------------------------------------------------------------------

def _build_llm(settings: Any) -> BaseChatModel:
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import]
            return ChatGoogleGenerativeAI(
                model=settings.model_name,
                google_api_key=settings.gemini_api_key,
                temperature=0.4,
            )
        except Exception as exc:
            logger.warning("ResearchAgent: Gemini falhou, tentando Groq. %s", exc)

    try:
        from pydantic import SecretStr
        from langchain_groq import ChatGroq  # type: ignore[import]
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=SecretStr(settings.groq_api_key),
            temperature=0.4,
        )
    except Exception as exc:
        raise RuntimeError(f"ResearchAgent: nenhum LLM disponível. {exc}") from exc


# ---------------------------------------------------------------------------
# DuckDuckGo search
# ---------------------------------------------------------------------------

def _domain(url: str) -> str:
    """Extrai o domínio limpo de uma URL (ex: 'g1.globo.com')."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        return host.removeprefix("www.") if host else ""
    except Exception:
        return ""


def _search_web(query: str, max_results: int = _MAX_RESULTS) -> List[Dict[str, str]]:
    """Busca no DuckDuckGo e retorna lista de {title, url, body, source}.
    Timeout de 5 segundos para não bloquear a resposta."""
    results: List[Dict[str, str]] = []
    try:
        import concurrent.futures
        from ddgs import DDGS

        def _do_search() -> List[Dict[str, str]]:
            output: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    url = r.get("href", "")
                    output.append({
                        "title":     r.get("title", ""),
                        "url":       url,
                        "body":      r.get("body", "")[:_MAX_SNIPPET],
                        "source":    _domain(url),
                        "published": "",
                    })
            return output

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_search)
            try:
                results = future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning("DuckDuckGo web search timeout (5s): query=%s", query[:40])
    except Exception as exc:
        logger.warning("DuckDuckGo search falhou: %s", exc)
    return results


def _search_news(query: str, max_results: int = _MAX_RESULTS) -> List[Dict[str, str]]:
    """Busca notícias recentes no DuckDuckGo News.
    Timeout de 5 segundos para não bloquear a resposta."""
    results: List[Dict[str, str]] = []
    try:
        import concurrent.futures
        from ddgs import DDGS

        def _do_news() -> List[Dict[str, str]]:
            output: List[Dict[str, str]] = []
            with DDGS() as ddgs:
                for r in ddgs.news(query, max_results=max_results):
                    url = r.get("url", r.get("href", ""))
                    output.append({
                        "title":     r.get("title", ""),
                        "url":       url,
                        "body":      r.get("body", "")[:_MAX_SNIPPET],
                        "source":    r.get("source", _domain(url)),
                        "published": r.get("date", ""),
                    })
            return output

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_news)
            try:
                results = future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning("DuckDuckGo news search timeout (5s): query=%s", query[:40])
    except Exception as exc:
        logger.warning("DuckDuckGo news falhou: %s", exc)
    return results


# ---------------------------------------------------------------------------
# Focus-topic saver
# ---------------------------------------------------------------------------

def _is_focus_topic(message: str) -> bool:
    norm = message.lower()
    return any(t in norm for t in _FOCUS_TOPICS)


def _save_to_file(query: str, snippets: List[Dict[str, str]], summary: str) -> None:
    """Salva resumo da pesquisa em data/research/neural_water.md."""
    _SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sources   = "\n".join(
        f"- [{s['title']}]({s['url']})" for s in snippets if s.get("url")
    )
    block = (
        f"\n\n---\n## {timestamp} — {query[:80]}\n\n"
        f"**Resumo:** {summary[:600]}\n\n"
        f"**Fontes consultadas:**\n{sources or '(sem fontes)'}"
    )
    with open(_SAVE_PATH, "a", encoding="utf-8") as fh:
        fh.write(block)
    logger.info("Pesquisa de tópico focal salva em %s", _SAVE_PATH)


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------

class ResearchAgent(BaseAgent):
    """
    Agente que realiza buscas em tempo real e sintetiza uma resposta usando o LLM.

    Pipeline:
        1. DuckDuckGo text search (máx. 5 resultados)
        2. Injeta snippets como contexto no prompt do LLM
        3. LLM sintetiza resposta conversacional
        4. Se tópico de foco, salva resumo em data/research/neural_water.md
    """

    def __init__(self) -> None:
        super().__init__(name="ResearchAgent")
        self._llm = _build_llm(get_settings())

    def process(
        self,
        message: str,
        history: List[Dict[str, Any]],
        session_id: str,
        rag_contexts: Optional[List[str]] = None,
    ) -> str:
        logger.info("ResearchAgent | session=%s | query=%.60s", session_id, message)

        # 1. Busca na web
        snippets = _search_web(message)
        if not snippets:
            return (
                "Tentei buscar informações atualizadas na web, mas não consegui obter resultados "
                "no momento. Posso responder com base no meu conhecimento interno, se desejar."
            )

        # 2. Formata contexto dos snippets
        ctx_parts = [
            f"[{i}] {s['title']}\n{s['url']}\n{s['body']}"
            for i, s in enumerate(snippets, 1)
        ]
        web_context = "\n\n".join(ctx_parts)

        # 3. Monta mensagens para o LLM
        msgs: list = [SystemMessage(content=_SYSTEM_PROMPT)]

        # Histórico recente (últimas 8 mensagens = 4 trocas)
        for turn in history[-8:]:
            role    = turn.get("role", "")
            content = turn.get("content", "")
            if role == "user":
                msgs.append(HumanMessage(content=content))
            elif role == "assistant":
                msgs.append(AIMessage(content=content))

        # Contexto RAG da memória vetorial (se houver)
        if rag_contexts:
            rag_block = (
                "\n---\nCONTEXTO DE MEMÓRIA ANTERIOR "
                "(use apenas se pertinente):\n"
                + "\n".join(rag_contexts)
                + "\n---"
            )
            msgs.append(SystemMessage(content=rag_block))

        # Prompt final: pergunta + snippets web
        msgs.append(HumanMessage(content=(
            f"PERGUNTA: {message}\n\n"
            f"RESULTADOS DA BUSCA WEB:\n{web_context}"
        )))

        # 4. Gera resposta
        response = self._llm.invoke(msgs)
        answer   = response.content if hasattr(response, "content") else str(response)

        # 5. Salva se for tópico de foco
        if _is_focus_topic(message):
            _save_to_file(message, snippets, str(answer))

        logger.info("ResearchAgent | session=%s | snippets=%d | resposta_len=%d",
                    session_id, len(snippets), len(str(answer)))
        return str(answer)

    # ------------------------------------------------------------------
    # Interface pública — busca sem síntese LLM
    # ------------------------------------------------------------------

    def search_raw(
        self,
        query: str,
        max_results: int = 8,
        search_type: str = "web",
    ) -> List[Dict[str, str]]:
        """
        Executa uma busca e retorna os resultados brutos (sem síntese LLM).

        Args:
            query:       Termo de busca.
            max_results: Máximo de resultados (1–20).
            search_type: 'web' (padrão) ou 'news'.

        Returns:
            Lista de dicts com chaves: title, url, body, source, published.
        """
        max_results = max(1, min(max_results, 20))
        if search_type == "news":
            return _search_news(query, max_results)
        return _search_web(query, max_results)

    def synthesize(
        self,
        query: str,
        snippets: List[Dict[str, str]],
        session_id: str = "__search__",
    ) -> str:
        """
        Gera um resumo conversacional a partir de snippets já pesquisados.

        Args:
            query:      Pergunta original do usuário.
            snippets:   Lista de {title, url, body} retornada por search_raw.
            session_id: ID de sessão para logging.

        Returns:
            Texto sintetizado pelo LLM.
        """
        if not snippets:
            return (
                "Não encontrei resultados relevantes para esta busca. "
                "Posso responder com base no meu conhecimento interno."
            )

        ctx_parts = [
            f"[{i}] {s['title']}\n{s['url']}\n{s['body']}"
            for i, s in enumerate(snippets, 1)
        ]
        web_context = "\n\n".join(ctx_parts)

        msgs: list = [SystemMessage(content=_SYSTEM_PROMPT)]
        msgs.append(HumanMessage(content=(
            f"PERGUNTA: {query}\n\n"
            f"RESULTADOS DA BUSCA:\n{web_context}"
        )))

        response = self._llm.invoke(msgs)
        answer   = response.content if hasattr(response, "content") else str(response)
        logger.info("ResearchAgent.synthesize | session=%s | snippets=%d", session_id, len(snippets))
        return str(answer)
