"""
agents/integration_agent.py — Agente de Integração com o Mundo Externo.

Responsabilidades:
    • Clima em tempo real via OpenWeatherMap API.
    • Notícias de tecnologia via RSS (feed do Hacker News / TechCrunch).
    • Calendário local a partir de data/calendar.json.
    • Briefing matinal: saudação + clima + status do sistema + agenda do dia.

Segurança:
    • Todas as requisições HTTP têm timeout de 8 s.
    • Nenhum dado do usuário é enviado para APIs externas — apenas leitura.
    • A chave da API OpenWeatherMap nunca é logada.

Uso via chat:
    "Bom dia, Alfred"         → morning_briefing
    "Como está o clima?"      → weather
    "Me dê as últimas notícias" → news
    "O que tenho hoje?"       → calendar
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_HTTP_TIMEOUT           = 8    # segundos
_NEWS_MAX               = 5    # máx. de notícias no briefing
_CALENDAR_PATH          = Path("data/calendar.json")
_WEATHER_ALERT_COOLDOWN = 600  # segundos entre alertas da mesma cidade (10 min)

# Ícones de condição climática (mapeados por código OWM)
_WEATHER_ICONS: Dict[str, str] = {
    "Clear":        "☀️",
    "Clouds":       "☁️",
    "Rain":         "🌧️",
    "Drizzle":      "🌦️",
    "Thunderstorm": "⛈️",
    "Snow":         "❄️",
    "Mist":         "🌫️",
    "Fog":          "🌫️",
    "Haze":         "🌫️",
    "Smoke":        "🌫️",
    "Dust":         "🌫️",
    "Tornado":      "🌪️",
}


# ---------------------------------------------------------------------------
# Weather helpers
# ---------------------------------------------------------------------------

def _fetch_weather(city: str, api_key: str) -> Dict[str, Any]:
    """
    Faz requisição síncrona à API OpenWeatherMap Current Weather.

    Returns:
        Dict com campos: city, temp, feels_like, humidity, description,
        main, icon, wind_speed.

    Raises:
        RuntimeError: se a requisição falhar ou a chave for inválida.
    """
    import urllib.request
    import urllib.parse

    if not api_key:
        raise RuntimeError(
            "OPENWEATHERMAP_API_KEY não configurada. "
            "Adicione a chave ao arquivo .env para usar previsão do tempo."
        )

    params = urllib.parse.urlencode({
        "q":     city,
        "appid": api_key,
        "units": "metric",
        "lang":  "pt_br",
    })
    url = f"https://api.openweathermap.org/data/2.5/weather?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Alfred-AI/1.0"},
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Falha ao obter clima para '{city}': {exc}") from exc

    main_block = data["main"]
    weather    = data["weather"][0]
    wind       = data.get("wind", {})

    return {
        "city":        data.get("name", city),
        "temp":        round(main_block["temp"]),
        "feels_like":  round(main_block["feels_like"]),
        "humidity":    main_block["humidity"],
        "description": weather["description"].capitalize(),
        "main":        weather["main"],
        "icon":        _WEATHER_ICONS.get(weather["main"], "🌡️"),
        "wind_speed":  round(wind.get("speed", 0)),
    }


def _format_weather(w: Dict[str, Any]) -> str:
    """Formata dados de clima como texto Markdown."""
    return (
        f"{w['icon']} **Clima em {w['city']}**\n"
        f"🌡️ {w['temp']}°C (sensação {w['feels_like']}°C)\n"
        f"💧 Umidade: {w['humidity']}%\n"
        f"💨 Vento: {w['wind_speed']} km/h\n"
        f"📋 Condição: {w['description']}"
    )


def _compare_temperatures(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    """
    Retorna frase comparando temperaturas de duas cidades.
    Usada no briefing matinal (voz) e no _weather_only.
    """
    t_a, t_b = a.get("temp", 0), b.get("temp", 0)
    if t_a == t_b:
        return None
    hotter = a if t_a > t_b else b
    cooler = b if t_a > t_b else a
    delta  = abs(t_a - t_b)
    return (
        f"🌡️ **Senhor, {hotter['city']} está mais quente que {cooler['city']} hoje, "
        f"com uma diferença de {delta}°C.**"
    )


# ---------------------------------------------------------------------------
# News helpers
# ---------------------------------------------------------------------------

_RSS_FEEDS = [
    ("Hacker News",   "https://news.ycombinator.com/rss"),
    ("TechCrunch",    "https://techcrunch.com/feed/"),
    ("Dev.to",        "https://dev.to/feed"),
]


def _fetch_news(max_items: int = _NEWS_MAX) -> List[Dict[str, str]]:
    """
    Busca as últimas notícias de tecnologia via RSS.

    Tenta os feeds em ordem e retorna ao primeiro que responder.
    Usa parser manual leve (sem feedparser) para evitar dependência extra…
    mas usa feedparser se disponível.
    """
    try:
        import feedparser  # type: ignore[import]
        _use_feedparser = True
    except ImportError:
        _use_feedparser = False

    for source_name, feed_url in _RSS_FEEDS:
        try:
            if _use_feedparser:
                items = _parse_with_feedparser(feed_url, source_name, max_items)
            else:
                items = _parse_rss_manual(feed_url, source_name, max_items)
            if items:
                return items
        except Exception as exc:
            logger.debug("Feed '%s' falhou: %s", source_name, exc)
            continue

    return []


def _parse_with_feedparser(
    url: str, source: str, limit: int
) -> List[Dict[str, str]]:
    import feedparser  # type: ignore[import]

    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:limit]:
        items.append({
            "title":  entry.get("title", "Sem título"),
            "link":   entry.get("link", ""),
            "source": source,
        })
    return items


def _parse_rss_manual(
    url: str, source: str, limit: int
) -> List[Dict[str, str]]:
    """Parser RSS mínimo sem dependências externas."""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Alfred-AI/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", errors="replace")

    titles = re.findall(r"<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>", raw, re.DOTALL)
    items = []
    for title, link in titles[:limit]:
        # Remove CDATA wrappers e entidades HTML básicas
        title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title).strip()
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        link  = link.strip()
        items.append({"title": title, "link": link, "source": source})
    return items


def _format_news(items: List[Dict[str, str]]) -> str:
    """Formata lista de notícias como Markdown."""
    if not items:
        return "📰 Não foi possível obter notícias no momento. Tente novamente mais tarde."

    source = items[0].get("source", "RSS")
    lines  = [f"📰 **Últimas Notícias de Tech** ({source})\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def _load_calendar() -> List[Dict[str, Any]]:
    """
    Carrega tarefas do arquivo calendar.json.

    Returns:
        Lista de tarefas não concluídas, ordenadas por datetime.
    """
    path = _CALENDAR_PATH
    if not path.exists():
        # Cria arquivo de exemplo se não existir
        _create_default_calendar(path)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        tasks = data.get("tasks", [])
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Erro ao ler calendar.json: %s", exc)
        return []

    now = datetime.now()
    result = []
    for task in tasks:
        if task.get("done", False):
            continue
        dt_str = task.get("datetime", "")
        try:
            dt = datetime.fromisoformat(dt_str)
            task["_dt"] = dt
        except ValueError:
            task["_dt"] = now
        result.append(task)

    result.sort(key=lambda t: t["_dt"])
    return result


def _create_default_calendar(path: Path) -> None:
    """Cria um calendar.json de exemplo se não existir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now()
    example: Dict[str, Any] = {
        "tasks": [
            {
                "id":       "1",
                "title":    "Revisar pull requests",
                "datetime": today.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
                "type":     "task",
                "done":     False,
            },
            {
                "id":       "2",
                "title":    "Reunião de planejamento da sprint",
                "datetime": today.replace(hour=14, minute=0, second=0, microsecond=0).isoformat(),
                "type":     "meeting",
                "done":     False,
            },
            {
                "id":       "3",
                "title":    "Entrega do relatório técnico",
                "datetime": (today.replace(hour=18, minute=0, second=0, microsecond=0)).isoformat(),
                "type":     "deadline",
                "done":     False,
            },
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(example, f, ensure_ascii=False, indent=2)
    logger.info("calendar.json de exemplo criado em '%s'.", path)


def _get_today_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    return [t for t in tasks if t["_dt"].date() == today]


def _get_next_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    now = datetime.now()
    upcoming = [t for t in tasks if t["_dt"] >= now]
    return upcoming[0] if upcoming else None


def _fmt_task_time(dt: datetime) -> str:
    return dt.strftime("%d/%m às %H:%M")


def _type_icon(ttype: str) -> str:
    return {"meeting": "📅", "deadline": "⏰", "task": "✅"}.get(ttype, "📝")


def _format_calendar(tasks: List[Dict[str, Any]]) -> str:
    """Formata agenda como Markdown."""
    today_tasks = _get_today_tasks(tasks)
    if not today_tasks:
        return "📅 Sua agenda está livre hoje. Sem tarefas ou reuniões pendentes."

    lines = [f"📅 **Agenda de Hoje** ({len(today_tasks)} itens)\n"]
    for task in today_tasks:
        icon  = _type_icon(task.get("type", "task"))
        time_ = _fmt_task_time(task["_dt"])
        lines.append(f"{icon} {time_} — {task['title']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System info mini (não importa o agent todo para evitar ciclos)
# ---------------------------------------------------------------------------

def _get_system_snapshot() -> str:
    """Retorna uma linha resumida de CPU + RAM para o briefing."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory().percent
        return f"⚙️ CPU: {cpu:.1f}%  |  🧠 RAM: {ram:.1f}%"
    except Exception:
        return "⚙️ Métricas do sistema indisponíveis."


# ---------------------------------------------------------------------------
# IntegrationAgent
# ---------------------------------------------------------------------------

class IntegrationAgent(BaseAgent):
    """
    Agente de integração com APIs e serviços externos.

    Ações disponíveis:
        morning_briefing — Saudação + clima + sistema + agenda
        weather          — Apenas clima
        news             — Apenas notícias de tech
        calendar         — Apenas agenda
    """

    def __init__(self) -> None:
        super().__init__(name="IntegrationAgent")
        self._settings = get_settings()
        # Cooldown por cidade para alertas climáticos (anti-spam)
        self._weather_alert_cooldowns: Dict[str, float] = {}

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
        action = self._extract_action(message)

        logger.info(
            "IntegrationAgent | session=%s | action=%s | preview=%.60s",
            session_id, action, message,
        )

        if action == "morning_briefing":
            return self._morning_briefing()
        if action == "weather":
            return self._weather_only()
        if action == "news":
            return self._news_only()
        if action == "calendar":
            return self._calendar_only()

        # Fallback: tenta inferir pelo conteúdo
        return self._morning_briefing()

    # ------------------------------------------------------------------
    # Ações individuais
    # ------------------------------------------------------------------

    def _weather_only(self) -> str:
        cities = self._get_cities()
        parts: List[str] = []
        results: List[Dict[str, Any]] = []

        for city in cities:
            try:
                w = _fetch_weather(city=city, api_key=self._settings.openweathermap_api_key)
                results.append(w)
                parts.append(_format_weather(w))
            except RuntimeError as exc:
                parts.append(f"⚠️ {exc}")

        # Comparação de temperatura entre as duas primeiras cidades
        if len(results) >= 2:
            cmp = _compare_temperatures(results[0], results[1])
            if cmp:
                parts.append(cmp)

        return "\n\n".join(parts) if parts else "⚠️ Sem dados climáticos disponíveis."

    def _news_only(self) -> str:
        try:
            items = _fetch_news()
            return _format_news(items)
        except Exception as exc:
            return f"⚠️ Erro ao buscar notícias: {exc}"

    def _calendar_only(self) -> str:
        tasks = _load_calendar()
        return _format_calendar(tasks)

    def _morning_briefing(self) -> str:
        """Monta o briefing completo: saudação + clima + sistema + agenda."""
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 12:
            greeting = "🌅 **Bom dia!**"
        elif 12 <= hour < 18:
            greeting = "☀️ **Boa tarde!**"
        else:
            greeting = "🌙 **Boa noite!**"

        date_str = now.strftime("%A, %d de %B de %Y").capitalize()
        sections: List[str] = [
            f"{greeting} Aqui está o seu briefing para {date_str}.\n",
        ]

        # ── Clima (multi-cidade + comparação) ─────────────────────────
        cities_setting = self._get_cities()
        weather_results: List[Dict[str, Any]] = []
        for city in cities_setting:
            try:
                w = _fetch_weather(city=city, api_key=self._settings.openweathermap_api_key)
                weather_results.append(w)
                sections.append(_format_weather(w) + "\n")
            except RuntimeError as exc:
                sections.append(f"⚠️ Clima indisponível para {city}: {exc}\n")

        if len(weather_results) >= 2:
            cmp = _compare_temperatures(weather_results[0], weather_results[1])
            if cmp:
                sections.append(cmp + "\n")

        # ── Status do sistema ─────────────────────────────────────────
        sections.append(_get_system_snapshot() + "\n")

        # ── Agenda ────────────────────────────────────────────────────
        tasks = _load_calendar()
        sections.append(_format_calendar(tasks))

        # ── Notícias ─────────────────────────────────────────────────
        try:
            items = _fetch_news(max_items=3)
            if items:
                sections.append("\n" + _format_news(items))
        except Exception:
            pass

        # ── Status do Lab (DevAgent) ──────────────────────────────────
        try:
            from main import _get_dev_agent  # importação local — evita ciclo no boot
            dev_agent = _get_dev_agent()
            if dev_agent is not None:
                sections.append("\n" + dev_agent.lab_status_line())
        except Exception as exc:
            logger.debug("morning_briefing: DevAgent indisponível: %s", exc)

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Widget data — usado pelo endpoint GET /widget/status
    # ------------------------------------------------------------------

    def get_widget_data(self) -> Dict[str, Any]:
        """
        Retorna dados estruturados para o widget da Sidebar.
        Inclui `cities` (lista multi-cidade) e `weather` (primeira cidade,
        mantido para retrocompatibilidade). Não lança exceções.
        """
        # Weather — multi-cidade
        cities_data: List[Dict[str, Any]] = []
        for city in self._get_cities():
            try:
                w = _fetch_weather(city=city, api_key=self._settings.openweathermap_api_key)
                cities_data.append(w)
            except RuntimeError as exc:
                cities_data.append({"error": str(exc), "city": city})

        # Retrocompatibilidade: `weather` aponta para a primeira cidade
        weather = cities_data[0] if cities_data else {"error": "Sem cidades configuradas", "city": ""}

        # Calendar
        tasks       = _load_calendar()
        today_tasks = _get_today_tasks(tasks)
        next_task   = _get_next_task(tasks)

        calendar_data: Dict[str, Any] = {
            "today_count": len(today_tasks),
            "next_task":   None,
        }
        if next_task:
            calendar_data["next_task"] = {
                "title":    next_task["title"],
                "datetime": next_task["_dt"].isoformat(),
                "type":     next_task.get("type", "task"),
            }

        return {
            "weather":    weather,
            "cities":     cities_data,
            "calendar":   calendar_data,
            "fetched_at": datetime.now().isoformat(),
        }

    def collect_weather_alerts(self, cities_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analisa dados climáticos e retorna alertas para cidades que excedem
        os limiares de alerta (temp > 32 °C ou Tempestade).

        Respeita um cooldown de 10 minutos por cidade para evitar spam.
        """
        now    = time.time()
        alerts: List[Dict[str, Any]] = []

        for w in cities_data:
            if w.get("error"):
                continue
            city  = w.get("city", "")
            temp  = w.get("temp", 0)
            main  = w.get("main", "")

            # Respeitar o cooldown por cidade
            if now - self._weather_alert_cooldowns.get(city, 0) < _WEATHER_ALERT_COOLDOWN:
                continue

            if temp > 32:
                alerts.append({
                    "type":     "warning",
                    "category": "weather",
                    "title":    "Alerta Climático 🌡️",
                    "message":  f"Calor excessivo detectado em {city}: {temp}°C",
                })
                self._weather_alert_cooldowns[city] = now
            elif main == "Thunderstorm":
                alerts.append({
                    "type":     "warning",
                    "category": "weather",
                    "title":    "Alerta Climático ⛈️",
                    "message":  f"Tempestade detectada em {city}! Tome precauções.",
                })
                self._weather_alert_cooldowns[city] = now

        return alerts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_cities(self) -> List[str]:
        """Retorna a lista de cidades configuradas (suporta multi-cidade)."""
        cities = getattr(self._settings, "weather_cities", None)
        if cities:
            return list(cities)
        return [self._settings.weather_city]

    @staticmethod
    def _extract_action(message: str) -> str:
        """Extrai ação da mensagem normalizada."""
        msg = message.lower()

        BRIEFING_TRIGGERS = (
            "bom dia", "good morning", "briefing", "resumo do dia",
            "resumo matinal", "morning briefing", "me dê o briefing",
        )
        if any(t in msg for t in BRIEFING_TRIGGERS):
            return "morning_briefing"

        WEATHER_TRIGGERS = (
            "clima", "temperatura", "tempo agora", "como está o tempo",
            "weather", "previsão do tempo", "chuva", "vai chover",
            "faz calor", "faz frio", "graus",
        )
        if any(t in msg for t in WEATHER_TRIGGERS):
            return "weather"

        NEWS_TRIGGERS = (
            "notícias", "noticias", "news", "últimas notícias", "novidades",
            "tech news", "novidades de tech", "novidades de programação",
        )
        if any(t in msg for t in NEWS_TRIGGERS):
            return "news"

        CALENDAR_TRIGGERS = (
            "agenda", "tarefas", "o que tenho hoje", "meus compromissos",
            "próxima reunião", "proxima reuniao", "calendar", "schedule",
            "deadline", "prazo", "compromisso",
        )
        if any(t in msg for t in CALENDAR_TRIGGERS):
            return "calendar"

        return "morning_briefing"
