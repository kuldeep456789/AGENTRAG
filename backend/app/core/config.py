from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    load_dotenv()


class Settings(BaseSettings):
    app_name: str = Field(default="SaaS RAG Agent", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_referer: str | None = Field(default=None, alias="OPENROUTER_REFERER")
    mistral_api_key: str | None = Field(default=None, alias="MISTRAL_API_KEY")
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    cerebras_api_key: str | None = Field(default=None, alias="CEREBRAS_API_KEY")
    cloudflare_api_key: str | None = Field(default=None, alias="CLOUDFLARE_API_KEY")
    claude_api_key: str | None = Field(default=None, alias="CLAUDE_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    groq_model: str = Field(default="llama-3.1-8b-instant", alias="GROQ_MODEL")
    groq_max_tokens: int = Field(default=512, alias="GROQ_MAX_TOKENS")
    groq_temperature: float = Field(default=0.2, alias="GROQ_TEMPERATURE")
    groq_context_max_chars: int = Field(default=4000, alias="GROQ_CONTEXT_MAX_CHARS")
    groq_fast_context_max_chars: int = Field(default=2500, alias="GROQ_FAST_CONTEXT_MAX_CHARS")
    cache_ttl_seconds: int = Field(default=86400, alias="CACHE_TTL_SECONDS")
    session_ttl_seconds: int = Field(default=7200, alias="SESSION_TTL_SECONDS")
    free_user_daily_limit: int = Field(default=10, alias="FREE_USER_DAILY_LIMIT")
    similarity_threshold: float = Field(default=0.18, alias="SIMILARITY_THRESHOLD")
    hybrid_semantic_weight: float = Field(default=0.65, alias="HYBRID_SEMANTIC_WEIGHT")
    hybrid_keyword_weight: float = Field(default=0.35, alias="HYBRID_KEYWORD_WEIGHT")
    claude_model: str = Field(default="claude-3-5-sonnet-20240620", alias="CLAUDE_MODEL")
    openrouter_default_model: str = Field(
        default="anthropic/claude-3.5-sonnet",
        alias="OPENROUTER_DEFAULT_MODEL",
    )
    openrouter_reasoning_model: str = Field(
        default="anthropic/claude-3.5-sonnet",
        alias="OPENROUTER_REASONING_MODEL",
    )
    openrouter_coding_model: str = Field(
        default="deepseek/deepseek-chat",
        alias="OPENROUTER_CODING_MODEL",
    )
    openrouter_fast_model: str = Field(
        default="openai/gpt-4o-mini",
        alias="OPENROUTER_FAST_MODEL",
    )
    openrouter_max_tokens: int = Field(
        default=512,
        alias="OPENROUTER_MAX_TOKENS",
    )
    openrouter_fast_max_tokens: int = Field(
        default=256,
        alias="OPENROUTER_FAST_MAX_TOKENS",
    )
    openrouter_vision_model: str = Field(
        default="google/gemini-1.5-pro",
        alias="OPENROUTER_VISION_MODEL",
    )
    openrouter_context_max_chars: int = Field(
        default=12000,
        alias="OPENROUTER_CONTEXT_MAX_CHARS",
    )
    openrouter_fast_context_max_chars: int = Field(
        default=3000,
        alias="OPENROUTER_FAST_CONTEXT_MAX_CHARS",
    )
    translation_provider: str = Field(default="stub", alias="TRANSLATION_PROVIDER")
    web_search_provider: str = Field(default="stub", alias="WEB_SEARCH_PROVIDER")
    duckduckgo_max_results: int = Field(default=5, alias="DUCKDUCKGO_MAX_RESULTS")
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    news_api_max_results: int = Field(default=5, alias="NEWS_API_MAX_RESULTS")
    web_knowledge_auto_seed: bool = Field(default=False, alias="WEB_KNOWLEDGE_AUTO_SEED")
    web_knowledge_max_pages_per_site: int = Field(default=8, alias="WEB_KNOWLEDGE_MAX_PAGES_PER_SITE")
    web_knowledge_request_timeout: float = Field(default=10.0, alias="WEB_KNOWLEDGE_REQUEST_TIMEOUT")
    web_knowledge_seed_urls: str = Field(
        default="https://www.w3schools.com/,https://www.geeksforgeeks.org/,https://www.wikipedia.org/",
        alias="WEB_KNOWLEDGE_SEED_URLS",
    )
    email_sending_api_key: str | None = Field(default=None, alias="EMAIL_SENDING_API_KEY")
    vector_db_provider: str = Field(default="memory", alias="VECTOR_DB_PROVIDER")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    postgres_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/rag",
        alias="POSTGRES_URL",
    )
    chroma_collection: str = Field(default="rag-documents", alias="CHROMA_COLLECTION")
    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ALLOW_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "groq_api_key",
        "openrouter_api_key",
        mode="before",
    )
    @classmethod
    def _strip_api_key(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
