"""
core/config.py — Configurações centralizadas via variáveis de ambiente.
Utiliza pydantic-settings para parsing e validação automáticos.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação carregadas do arquivo .env."""

    # Identidade
    app_name: str = "Alfred AI"
    app_version: str = "0.1.0"

    # LLM — provedor ativo
    llm_provider: str = "gemini"          # "gemini" | "ollama" | "openai"
    model_name: str = "gemini-1.5-flash"
    gemini_model: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 1000

    # Google Gemini (Free Tier — https://aistudio.google.com)
    gemini_api_key: str = ""

    # Groq (Free Tier — https://console.groq.com | 14 400 req/dia)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # OpenRouter (Free Tier — https://openrouter.ai | 50+ modelos gratuitos)
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Ollama (modelos locais — https://ollama.ai)
    ollama_base_url: str = "http://localhost:11434"

    # OpenAI (legado — pago)
    openai_api_key: str = ""

    # Memória SQLite
    memory_db_path: str = "memory/alfred_memory.db"

    # Memória Vetorial (ChromaDB + Sentence-Transformers)
    vector_db_path: str = "memory/vector_db"
    vector_collection_name: str = "alfred_memory"
    vector_embedding_model: str = "all-MiniLM-L6-v2"
    vector_top_k: int = 3

    # Integração externa — Clima (OpenWeatherMap)
    openweathermap_api_key: str = ""
    weather_city: str = "Aracaju"                            # legátero: cidade única
    weather_cities: list[str] = ["Aracaju", "Laranjeiras"]  # monitoramento multi-cidade

    # Integração externa — Calendário local
    calendar_path: str = "data/calendar.json"

    # DevAgent — repositório monitorado
    project_path: str = ""   # caminho absoluto ou relativo; vazio = CWD
    project_name: str = ""   # nome exibido no briefing; vazio = nome da pasta

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações (singleton)."""
    return Settings()
