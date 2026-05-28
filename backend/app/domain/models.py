from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    admin = "admin"
    pro_user = "pro_user"
    free_user = "free_user"
    guest = "guest"


class ResponseSource(str, Enum):
    cache = "cache"
    database = "database"
    llm = "llm"
    web_search = "web_search"
    none = "none"


class Feature(str, Enum):
    rag = "rag"
    upload = "upload"
    summarize = "summarize"
    vision = "vision"
    voice = "voice"
    dashboard = "dashboard"
    admin = "admin"


ROLE_FEATURES: dict[UserRole, set[Feature]] = {
    UserRole.admin: {
        Feature.rag,
        Feature.upload,
        Feature.summarize,
        Feature.vision,
        Feature.voice,
        Feature.dashboard,
        Feature.admin,
    },
    UserRole.pro_user: {
        Feature.rag,
        Feature.upload,
        Feature.summarize,
        Feature.vision,
        Feature.voice,
        Feature.dashboard,
    },
    UserRole.free_user: {
        Feature.rag,
        Feature.dashboard,
    },
    UserRole.guest: {
        Feature.rag,
    },
}


SUPPORTED_LANGUAGE_CODES = {
    "en": "English",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "ar": "Arabic",
    "pt": "Portuguese",
    "de": "German",
    "ja": "Japanese",
    "zh-cn": "Chinese (Simplified)",
}


class AuthContext(BaseModel):
    user_id: str
    role: UserRole
    session_id: str
    plan: str | None = None
    raw_claims: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)


class QueryResponse(BaseModel):
    answer: str
    source: ResponseSource
    detected_language: str
    translated_language: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    answer_style: str | None = None
    latency_ms: int = 0
    citations: list[str] = Field(default_factory=list)
    used_web_fallback: bool = False
    clarification_needed: bool = False
    confidence: float = 0.0
    source_coverage: str = "none"


class SummarizeRequest(BaseModel):
    filename: str
    content: str = Field(min_length=1)
    page_count: int = Field(ge=1)


class VisionRequest(BaseModel):
    image_name: str
    image_bytes_b64: str = Field(min_length=1)
    question: str = Field(min_length=1)
    contains_sensitive_data: bool = False
    confirmation: bool = False


class IngestRequest(BaseModel):
    filename: str
    content: str = Field(min_length=1)
    content_encoding: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    message: str
    chunks_stored: int
    source: str
    suggested_questions: list[str] = Field(default_factory=list)
    extraction: dict[str, Any] = Field(default_factory=dict)


class WebKnowledgeSeedRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    max_pages_per_site: int | None = Field(default=None, ge=1, le=50)


class WebKnowledgeSeedResponse(BaseModel):
    message: str
    pages_fetched: int
    chunks_stored: int
    source: str
    urls: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WebKnowledgeEntry(BaseModel):
    url: str
    host: str
    chunks: int = 0
    last_updated: datetime | None = None
    preview: str = ""


class WebKnowledgeListResponse(BaseModel):
    entries: list[WebKnowledgeEntry] = Field(default_factory=list)


class WebKnowledgeSection(BaseModel):
    heading: str | None = None
    paragraphs: list[str] = Field(default_factory=list)


class WebKnowledgePageDetail(BaseModel):
    url: str
    host: str = ""
    title: str = ""
    chunks: int = 0
    last_updated: datetime | None = None
    excerpt: str = ""
    word_count: int = 0
    char_count: int = 0
    body: str = ""
    sections: list[WebKnowledgeSection] = Field(default_factory=list)


class WebKnowledgeDeleteResponse(BaseModel):
    message: str
    url: str
    chunks_deleted: int = 0


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=1)
    role: UserRole
    session_id: str | None = None
    plan: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class FinanceQuoteRequest(BaseModel):
    symbol: str = Field(min_length=1)
    period: str = Field(default="5d")
    interval: str = Field(default="1d")


class FinanceQuoteResponse(BaseModel):
    symbol: str
    price: float
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    currency: str | None = None
    last_updated: datetime | None = None


class PhidataRequest(BaseModel):
    prompt: str = Field(min_length=1)


class PhidataResponse(BaseModel):
    answer: str
    provider: str
    used_tools: list[str] = Field(default_factory=list)


class StackResponse(BaseModel):
    packages: dict[str, str]


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str]


class DashboardResponse(BaseModel):
    scope: str
    total_queries_this_month: int
    queries_by_source: dict[str, int]
    average_latency_ms_last_30_days: float
    most_searched_topics: list[str]
    language_distribution: dict[str, int]
    daily_active_usage_heatmap: dict[str, int]
    token_consumption_vs_plan_limit: dict[str, int]
    admin_metrics: dict[str, Any] | None = None


class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryLog(BaseModel):
    query_text: str
    detected_language: str
    response_source: ResponseSource
    tokens_used: int
    latency_ms: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_role: UserRole
    session_id: str
    user_id: str
    document_uploaded: bool = False
    image_uploaded: bool = False
    voice_mode: bool = False
    used_web_fallback: bool = False
    retrieval_score: float = 0.0
    translated_to_en: bool = False
    translated_back: bool = False
