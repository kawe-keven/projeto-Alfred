"""
core/orchestrator.py — Orquestrador central do Alfred.

AlfredOrchestrator é responsável por:
  1. Receber a mensagem do usuário junto ao session_id.
  2. Recuperar contextos relevantes da memória vetorial (RAG).
  3. Selecionar o agente adequado (roteamento).
  4. Buscar/salvar histórico na camada de memória SQLite.
  5. Persistir a interação na memória vetorial ao final.
  6. Retornar a resposta ao endpoint /chat.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional

from agents.base_agent import BaseAgent
from agents.dev_agent import DevAgent
from agents.general_agent import GeneralAgent
from agents.integration_agent import IntegrationAgent
from agents.research_agent import ResearchAgent
from agents.system_agent import SystemAgent
from agents.vision_agent import VisionAgent
from core.config import Settings, get_settings
from core.intent_classifier import IntentResult, classify
from memory.memory_manager import MemoryManager
from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heurística de dados em tempo real
# Detecta perguntas que precisam de informações externas atualizadas, mesmo
# quando o usuário não usou as palavras-chave explícitas do ResearchAgent.
# ---------------------------------------------------------------------------

_REALTIME_RE = re.compile(
    r'(vers\u00e3o atual|vers\u00e3o corrente|release atual|\u00faltima vers\u00e3o|ultimo release'
    r'|lan\u00e7ad[ao]|released|changelog'
    r'|cota\u00e7\u00e3o|cota\u00e7\u00f5es|no mercado|na bolsa'
    r'|o que aconteceu.*hoje|o que est\u00e1 acontecendo'
    r'|em 20(2[4-9]|[3-9]\d)'          # anos 2024+
    r'|novidade(s)? sobre|h\u00e1 de novo sobre|o que h[a\u00e1] de novo'
    r'|pre\u00e7o atual|valor atual|quanto (est\u00e1|custa|vale).*hoje'
    r'|lançamento recente|novo (modelo|produto|servi\u00e7o|framework|pacote)'
    r'|em tempo real)',
    re.IGNORECASE,
)


def _message_needs_realtime(message: str) -> bool:
    """True se a mensagem provavelmente requer dados externos atualizados."""
    return bool(_REALTIME_RE.search(message))


class AlfredOrchestrator:
    """
    Orquestrador central que gerencia agentes e memória.

    Para adicionar um novo agente:
        1. Crie a classe em agents/
        2. Registre-a em `self._agents` com uma chave única.
        3. Implemente a lógica de roteamento em `_select_agent`.
    """

    def __init__(self) -> None:
        self._settings: Settings = get_settings()

        # Memória de curto prazo (histórico recente — SQLite)
        self._memory: MemoryManager = MemoryManager(
            db_path=self._settings.memory_db_path
        )

        # Memória de longo prazo (busca semântica — ChromaDB)
        self._vector_store: VectorStore = VectorStore(
            persist_directory=self._settings.vector_db_path,
            collection_name=self._settings.vector_collection_name,
            embedding_model=self._settings.vector_embedding_model,
        )

        self._agents: Dict[str, BaseAgent] = {
            "general":     GeneralAgent(),
            "system":      SystemAgent(),
            "vision":      VisionAgent(),
            "integration": IntegrationAgent(),
            "dev":         DevAgent(vector_store=self._vector_store),
            "research":    ResearchAgent(),
        }
        self._default_agent_key: str = "general"

    # ------------------------------------------------------------------
    # Roteamento
    # ------------------------------------------------------------------

    def _select_agent(self, message: str, session_id: str) -> tuple[BaseAgent, IntentResult]:
        """
        Classifica a intenção e retorna o agente + resultado da classificação.

        Retorna tupla (BaseAgent, IntentResult) para que o pipeline
        possa usar o intent ao chamar o agente.
        """
        intent = classify(message)

        agent_key = intent.agent if intent.agent in self._agents else self._default_agent_key
        agent = self._agents[agent_key]

        logger.info(
            "session=%s | agent=%s | action=%s | confidence=%.2f | preview=%.60s",
            session_id,
            agent_key,
            intent.action or "—",
            intent.confidence,
            message,
        )
        return agent, intent

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def _retrieve_long_term_contexts(self, query: str, session_id: str) -> List[str]:
        """
        Recupera os fragmentos mais relevantes da memória vetorial (RAG).

        Returns:
            Lista de strings de contexto ordenadas por relevância.
        """
        top_k = self._settings.vector_top_k
        hits = self._vector_store.search(query=query, top_k=top_k)
        contexts = [hit["document"] for hit in hits]
        logger.debug(
            "RAG | session=%s | fragmentos_recuperados=%d", session_id, len(contexts)
        )
        return contexts

    def chat(self, session_id: str, message: str, image_data: str | None = None) -> dict:
        """
        Processa uma mensagem e retorna a resposta do agente selecionado.

        Pipeline:
            1. Classifica a intenção (system vs vision vs general).
            2. Recupera contextos RAG (apenas para agente general).
            3. Busca histórico recente (SQLite).
            4. Persiste mensagem do usuário.
            5. Chama o agente com histórico + contextos RAG + imagem.
            6. Persiste resposta do assistente.
            7. Adiciona a interação à memória vetorial.

        Returns:
            dict com chaves `response`, `agent_used`, `rag_contexts_used`,
            `rag_contexts` e `intent`.
        """
        # -- 1. Classifica intenção e seleciona agente --
        agent, intent = self._select_agent(message, session_id)

        # -- 1b. Auto-upgrade: se o agente for "general" mas a query envolve
        #        dados em tempo real, redireciona silenciosamente para ResearchAgent.
        if intent.agent == "general" and _message_needs_realtime(message):
            research_agent = self._agents.get("research")
            if research_agent is not None:
                agent = research_agent
                intent = IntentResult(
                    agent="research",
                    action="web_search",
                    confidence=0.82,
                )
                logger.info(
                    "session=%s | auto-upgrade → ResearchAgent (heurística temporal)",
                    session_id,
                )

        # -- 2. RAG apenas para interações gerais, dev e research (contexto enriquece todos) --
        rag_contexts: List[str] = []
        if intent.agent in ("general", "dev", "research"):
            rag_contexts = self._retrieve_long_term_contexts(message, session_id)

        # -- 3. Histórico recente da sessão --
        history = self._memory.get_history(session_id)

        # -- 4. Persiste mensagem do usuário --
        self._memory.add_message(session_id=session_id, role="user", content=message)

        # -- 5. Chama agente --
        if intent.agent == "vision" and isinstance(agent, VisionAgent):
            response_text: str = agent.process(
                message=message,
                history=history,
                session_id=session_id,
                image_data=image_data,
            )
        else:
            response_text = agent.process(
                message=message,
                history=history,
                session_id=session_id,
                rag_contexts=rag_contexts if rag_contexts else None,
            )

        # -- 6. Persiste resposta do assistente --
        self._memory.add_message(
            session_id=session_id, role="assistant", content=response_text
        )

        # -- 7. Consolida interação na memória vetorial (longo prazo) --
        self._vector_store.add_interaction(
            session_id=session_id,
            user_message=message,
            assistant_message=response_text,
        )

        return {
            "response":          response_text,
            "agent_used":        agent.name,
            "rag_contexts_used": len(rag_contexts),
            "rag_contexts":      rag_contexts,
            "intent": {
                "agent":      intent.agent,
                "action":     intent.action,
                "confidence": round(intent.confidence, 3),
            },
        }

    def needs_research(self, message: str) -> bool:
        """
        Retorna True se a mensagem provavelmente requer busca web em tempo real.

        Combina a classificação de intenção (keywords explícitas) com a
        heurística temporal (_REALTIME_RE) para cobrir perguntas sobre fatos
        recentes que não usam gatilhos como 'pesquise na web'.
        """
        intent = self._select_agent(message, "__check__")[1]
        if intent.agent == "research":
            return True
        return _message_needs_realtime(message)

    # ------------------------------------------------------------------
    # Pipeline assíncrono com streaming de tokens + paralelismo RAG
    # ------------------------------------------------------------------

    async def async_chat(
        self,
        session_id: str,
        message: str,
        image_data: Optional[str] = None,
        on_token: Optional[Callable[[str], Coroutine]] = None,
    ) -> dict:
        """
        Versão assíncrona de chat() com:
          • asyncio.gather para RAG + histórico em paralelo (< 0.5 s ganho)
          • Streaming de tokens via on_token callback (visibilidade imediata)
          • Mesmo retorno que chat()
        """
        # -- 1. Intent (sync, rápido) --
        agent, intent = self._select_agent(message, session_id)

        # -- 1b. Auto-upgrade para ResearchAgent --
        if intent.agent == "general" and _message_needs_realtime(message):
            research_agent = self._agents.get("research")
            if research_agent is not None:
                agent = research_agent
                intent = IntentResult(
                    agent="research",
                    action="web_search",
                    confidence=0.82,
                )
                logger.info("session=%s | async auto-upgrade → ResearchAgent", session_id)

        # -- 2. Paralelismo: RAG + histórico simultâneos --
        rag_contexts: List[str] = []
        history: list = []

        if intent.agent in ("general", "dev", "research"):
            rag_contexts, history = await asyncio.gather(
                asyncio.to_thread(self._retrieve_long_term_contexts, message, session_id),
                asyncio.to_thread(self._memory.get_history, session_id),
            )
        else:
            history = await asyncio.to_thread(self._memory.get_history, session_id)

        # -- 3. Persiste mensagem do usuário --
        await asyncio.to_thread(
            self._memory.add_message, session_id=session_id, role="user", content=message
        )

        # -- 4. Chama agente (com streaming se GeneralAgent) --
        response_text: str
        if intent.agent == "vision" and isinstance(agent, VisionAgent):
            response_text = await asyncio.to_thread(
                agent.process,
                message=message,
                history=history,
                session_id=session_id,
                image_data=image_data,
            )
        elif isinstance(agent, GeneralAgent) and on_token is not None:
            response_text = await agent.async_process(
                message=message,
                history=history,
                session_id=session_id,
                rag_contexts=rag_contexts if rag_contexts else None,
                on_token=on_token,
            )
        else:
            response_text = await asyncio.to_thread(
                agent.process,
                message=message,
                history=history,
                session_id=session_id,
                rag_contexts=rag_contexts if rag_contexts else None,
            )

        # -- 5. Persiste resposta + memória vetorial em paralelo --
        await asyncio.gather(
            asyncio.to_thread(
                self._memory.add_message,
                session_id=session_id, role="assistant", content=response_text,
            ),
            asyncio.to_thread(
                self._vector_store.add_interaction,
                session_id=session_id,
                user_message=message,
                assistant_message=response_text,
            ),
        )

        return {
            "response":          response_text,
            "agent_used":        agent.name,
            "rag_contexts_used": len(rag_contexts),
            "rag_contexts":      rag_contexts,
            "intent": {
                "agent":      intent.agent,
                "action":     intent.action,
                "confidence": round(intent.confidence, 3),
            },
        }

    def clear_session(self, session_id: str) -> None:
        """
        Remove todo o histórico de uma sessão (SQLite + VectorStore).
        Operação tolerante a falhas: continua mesmo se uma das operações falhar.
        """
        try:
            self._memory.clear_session(session_id)
        except Exception as exc:
            logger.error(
                "session=%s | erro ao limpar SQLite: %s (ignorando para continuar)",
                session_id,
                exc,
            )

        try:
            self._vector_store.delete_by_session(session_id)
        except Exception as exc:
            logger.error(
                "session=%s | erro ao limpar VectorStore: %s (ignorando)",
                session_id,
                exc,
            )

        logger.info("session=%s | cleared (SQLite + VectorStore)", session_id)

    def get_history(self, session_id: str, limit: int = 20) -> list:
        """Retorna o histórico de uma sessão."""
        return self._memory.get_history(session_id, limit=limit)

    def get_dev_agent(self) -> "DevAgent | None":
        """Retorna o DevAgent se registrado, ou None."""
        agent = self._agents.get("dev")
        if isinstance(agent, DevAgent):
            return agent
        return None

    # ------------------------------------------------------------------
    # Proactive Briefing
    # ------------------------------------------------------------------

    def get_morning_briefing(self) -> dict:
        """
        Coleta dados de clima, hardware e pesquisas recentes e sintetiza
        um briefing conversacional via GeneralAgent.

        Returns:
            {
                "text":         str,         # texto pronto para TTS
                "topics":       list[str],   # últimos tópicos pesquisados
                "weather_city": str,
                "cpu":          float,
                "ram":          float,
            }
        """
        import psutil
        from datetime import datetime as _dt
        from core.monitor_service import monitor_service as _ms

        # 1. Hardware snapshot
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
        except Exception:
            cpu, ram = 0.0, 0.0

        # 2. Últimas pesquisas (últimas 3 queries do canal 'research')
        recent_logs = _ms.get_recent_logs(50)
        research_topics: List[str] = [
            str(log.get("value", ""))
            for log in recent_logs
            if log.get("category") == "research" and log.get("value")
        ][-3:]

        # 3. Clima via IntegrationAgent (usa a infra existente de _morning_briefing)
        weather_text = ""
        weather_city = ""
        int_agent = self._agents.get("integration")
        if int_agent is not None:
            try:
                raw = int_agent._morning_briefing()
                # Extrai linha de clima do markdown gerado
                for line in raw.splitlines():
                    if "°C" in line and ("Aracaju" in line or "Laranjeiras" in line or "☀" in line or "🌧" in line or "⛅" in line or "🌩" in line):
                        weather_text = line.strip().lstrip("•").strip()
                        if "Aracaju" in line:
                            weather_city = "Aracaju"
                        elif "Laranjeiras" in line:
                            weather_city = "Laranjeiras"
                        break
            except Exception as exc:
                logger.debug("Briefing: clima indisponível: %s", exc)

        # 4. Saudação baseada na hora
        hour = _dt.now().hour
        if 5 <= hour < 12:
            period = "Bom dia"
        elif 12 <= hour < 18:
            period = "Boa tarde"
        else:
            period = "Boa noite"

        # 5. Montar prompt para síntese conversacional via GeneralAgent
        hw_note = "estável" if cpu < 70 and ram < 85 else "sob atenção"
        hw_info = f"CPU em {cpu:.0f}% e RAM em {ram:.0f}%, status {hw_note}"

        weather_part = f"O clima em {weather_city} é: {weather_text}. " if weather_text else ""
        topics_part = (
            f"As últimas pesquisas realizadas foram: {'; '.join(research_topics)}. "
            if research_topics
            else ""
        )

        prompt = (
            f"Gere uma saudação de '{period}, Senhor' de forma muito curta, natural e "
            f"conversacional, como um mordomo eficiente. Incorpore de forma fluida: "
            f"o status do sistema ({hw_info}). "
            f"{weather_part}"
            f"{topics_part}"
            f"Encerre dizendo que está em prontidão para ajudar. "
            f"Máximo 3 frases. Sem Markdown. Sem asteriscos. "
            f"Escreva como se o texto fosse lido em voz alta."
        )

        text = prompt  # fallback se GeneralAgent falhar
        general = self._agents.get("general")
        if general is not None:
            try:
                text = general.process(
                    message=prompt,
                    history=[],
                    session_id="__briefing__",
                )
            except Exception as exc:
                logger.warning("Briefing: GeneralAgent falhou: %s", exc)

        return {
            "text": text,
            "topics": research_topics,
            "weather_city": weather_city,
            "cpu": cpu,
            "ram": ram,
        }
