from __future__ import annotations

from contextlib import asynccontextmanager
import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.domain.models import (
    DashboardResponse,
    Feature,
    FinanceQuoteRequest,
    FinanceQuoteResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    LoginRequest,
    PhidataRequest,
    PhidataResponse,
    QueryRequest,
    QueryResponse,
    RefreshRequest,
    StackResponse,
    SummarizeRequest,
    AuthContext,
    UserRole,
    VisionRequest,
    WebKnowledgeEntry,
    WebKnowledgeListResponse,
    WebKnowledgePageDetail,
    WebKnowledgeDeleteResponse,
    WebKnowledgeSeedRequest,
    WebKnowledgeSeedResponse,
)
from app.infra.db import Database
from app.infra.repositories import ChunkRepository, QueryLogRepository
from app.services.providers import (
    AnalyticsService,
    AuthService,
    AuthenticationError,
    CacheService,
    DocumentService,
    EmbeddingService,
    FinanceService,
    LanguageService,
    LLMRouterService,
    PDFExtractionError,
    PermissionError,
    PhidataAgentService,
    ProfileService,
    RateLimitError,
    RateLimiter,
    StorageService,
    VectorStoreService,
    WebsiteKnowledgeService,
    WebSearchService,
    decode_image_bytes,
    ensure_feature,
    get_dependency_versions,
)
from app.workflows.rag import RAGWorkflow


class ServiceContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_status = "disconnected"
        self.db_error: str | None = None
        self.database = None
        self.chunk_repository = None
        self.query_log_repository = None
        try:
            self.database = Database(settings)
            self.database.create_tables()
            self.chunk_repository = ChunkRepository(self.database)
            self.query_log_repository = QueryLogRepository(self.database)
            self.db_status = "connected"
        except Exception as exc:
            self.db_error = str(exc)
        self.cache = CacheService()
        self.embedder = EmbeddingService()
        self.vector_store = VectorStoreService(self.embedder, settings)
        self.language = LanguageService()
        self.llm = LLMRouterService(settings)
        self.web_search = WebSearchService(settings)
        self.auth = AuthService(settings)
        self.rate_limiter = RateLimiter(self.cache, settings)
        self.document_service = DocumentService()
        self.profile_service = ProfileService()
        self.analytics = AnalyticsService(repository=self.query_log_repository)
        self.finance = FinanceService()
        self.phidata = PhidataAgentService(settings)
        self.storage = StorageService(
            self.vector_store,
            self.document_service,
            repository=self.chunk_repository,
        )
        self.storage.hydrate_vector_store()
        self.website_knowledge = WebsiteKnowledgeService(settings, self.storage)
        if settings.web_knowledge_auto_seed:
            self.website_knowledge.seed()
        self.workflow = RAGWorkflow(
            settings=settings,
            cache=self.cache,
            rate_limiter=self.rate_limiter,
            language=self.language,
            vector_store=self.vector_store,
            llm=self.llm,
            web_search=self.web_search,
            analytics=self.analytics,
            embedder=self.embedder,
            storage=self.storage,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.container = ServiceContainer(settings)
    yield


app = FastAPI(title="SaaS RAG Agent", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
_cors_origins = [origin.strip() for origin in _settings.cors_allow_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_container() -> ServiceContainer:
    return app.state.container


def get_auth_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    container: ServiceContainer = Depends(get_container),
):
    if not authorization or not authorization.startswith("Bearer "):
        if container.settings.app_env != "production":
            return AuthContext(
                user_id="guest",
                role=UserRole.guest,
                session_id="guest-session",
                plan="guest",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        if container.settings.app_env != "production":
            return AuthContext(
                user_id="guest",
                role=UserRole.guest,
                session_id="guest-session",
                plan="guest",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    try:
        return container.auth.validate(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def get_voice_mode(
    response_mode: Annotated[str | None, Header(alias="X-Response-Mode")] = None,
) -> bool:
    return (response_mode or "").strip().lower() == "voice"


def get_fast_mode(
    fast_mode: Annotated[str | None, Header(alias="X-Fast-Mode")] = None,
) -> bool:
    return (fast_mode or "").strip().lower() in {"1", "true", "yes", "on"}


@app.post("/query", response_model=QueryResponse)
def query_agent(
    payload: QueryRequest,
    auth=Depends(get_auth_context),
    voice_mode: bool = Depends(get_voice_mode),
    fast_mode: bool = Depends(get_fast_mode),
    container: ServiceContainer = Depends(get_container),
):
    ensure_feature(auth, Feature.rag)
    if voice_mode:
        try:
            ensure_feature(auth, Feature.voice)
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if auth.role.value == "guest":
        public_query = payload.query
        private_markers = ("my ", "our ", "upload", "file", "document")
        if any(marker in public_query.lower() for marker in private_markers):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Guest users can access public knowledge only.",
            )
    try:
        return container.workflow.run(auth, payload.query, voice_mode=voice_mode, fast_mode=fast_mode)
    except RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc


@app.post("/summarize")
def summarize_document(
    payload: SummarizeRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.summarize)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    summary = container.document_service.summarize_document(
        filename=payload.filename,
        content=payload.content,
        page_count=payload.page_count,
        llm=container.llm,
    )
    container.vector_store.add_chunks(summary["chunks"])
    return {
        "title": summary["title"],
        "executive_summary": summary["executive_summary"],
        "key_points": summary["key_points"],
        "suggested_follow_up_questions": summary["follow_up_questions"],
        "source": "[LLM Knowledge]",
    }


@app.post("/vision")
def analyze_image(
    payload: VisionRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.vision)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if payload.contains_sensitive_data and not payload.confirmation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This image may contain personal or sensitive data. Please confirm before processing.",
        )

    _ = decode_image_bytes(payload.image_bytes_b64)
    started_at = time.perf_counter()
    description = f"I can see the uploaded image named '{payload.image_name}'."
    answer = container.llm.analyze_image(payload.image_name, payload.question)
    return {
        "description": description,
        "answer": answer,
        "source": "[LLM Knowledge]",
        "llm_provider": "openrouter" if container.settings.openrouter_api_key else "unconfigured",
        "llm_model": container.settings.openrouter_vision_model if container.settings.openrouter_api_key else None,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
    }


@app.post("/input", response_model=IngestResponse)
def ingest_document(
    payload: IngestRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.upload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    try:
        ingest_result = container.storage.store_document(
            payload.filename,
            payload.content,
            payload.metadata
            | {
                "uploaded_by": auth.user_id,
                "mime_type": payload.mime_type,
                "content_encoding": payload.content_encoding,
            },
            content_encoding=payload.content_encoding,
        )
    except PDFExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {
        "message": "Document ingested successfully.",
        "chunks_stored": ingest_result["chunks_stored"],
        "source": "[Database]",
        "suggested_questions": ingest_result["suggested_questions"],
        "extraction": ingest_result["extraction"],
    }


@app.post("/knowledge/web/seed", response_model=WebKnowledgeSeedResponse)
def seed_web_knowledge(
    payload: WebKnowledgeSeedRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.upload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    result = container.website_knowledge.seed(
        urls=payload.urls or None,
        max_pages_per_site=payload.max_pages_per_site,
    )
    return {
        "message": "Website knowledge ingested successfully.",
        "pages_fetched": result["pages_fetched"],
        "chunks_stored": result["chunks_stored"],
        "source": "[Database]",
        "urls": result["urls"],
        "errors": result["errors"],
    }


@app.get("/knowledge/web/list", response_model=WebKnowledgeListResponse)
def list_web_knowledge(
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.upload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not container.chunk_repository:
        return {"entries": []}

    rows = container.chunk_repository.list_seeded_web_pages()
    entries = [
        WebKnowledgeEntry(
            url=row["url"],
            host=row["host"],
            chunks=row["chunks"],
            last_updated=row["last_updated"],
            preview=row["preview"],
        )
        for row in rows
    ]
    return {"entries": entries}


@app.get("/knowledge/web/page", response_model=WebKnowledgePageDetail)
def get_web_knowledge_page(
    url: str,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.upload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not container.chunk_repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    detail = container.chunk_repository.get_seeded_web_page_detail(url)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")
    return detail


@app.delete("/knowledge/web/page", response_model=WebKnowledgeDeleteResponse)
def delete_web_knowledge_page(
    url: str,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.upload)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if not container.chunk_repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    result = container.storage.delete_seeded_web_page(url)
    if result["chunks_deleted"] <= 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found.")

    return {
        "message": "Synced webpage removed from knowledge base.",
        "url": result["url"],
        "chunks_deleted": result["chunks_deleted"],
    }


@app.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    try:
        ensure_feature(auth, Feature.dashboard)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return container.analytics.dashboard(auth)


@app.get("/health", response_model=HealthResponse)
def health(container: ServiceContainer = Depends(get_container)):
    db_status = container.db_status
    if container.db_error:
        db_status = f"{db_status}: {container.db_error.splitlines()[0][:120]}"
    return HealthResponse(
        status="ok" if container.db_status == "connected" else "degraded",
        services={
            "db": db_status,
            "redis": "connected",
            "llm": (
                container.settings.openrouter_default_model
                if container.settings.openrouter_api_key
                else container.settings.claude_model
                if container.settings.anthropic_api_key or container.settings.claude_api_key
                else container.settings.groq_model
                if container.settings.groq_api_key
                else "not-configured"
            ),
            "mcp": "configured-via-adapter",
        },
    )


@app.post("/auth/login")
def login(payload: LoginRequest, container: ServiceContainer = Depends(get_container)):
    access_token = container.auth.issue_token(
        user_id=payload.user_id,
        role=payload.role,
        session_id=payload.session_id,
        plan=payload.plan,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/auth/refresh")
def refresh(payload: RefreshRequest, container: ServiceContainer = Depends(get_container)):
    try:
        auth = container.auth.validate(payload.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    access_token = container.auth.issue_token(
        user_id=auth.user_id,
        role=auth.role,
        session_id=auth.session_id,
        plan=auth.plan,
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/finance/quote", response_model=FinanceQuoteResponse)
def finance_quote(
    payload: FinanceQuoteRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    _ = auth
    try:
        quote = container.finance.quote(payload.symbol, payload.period, payload.interval)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return FinanceQuoteResponse(**quote)


@app.post("/agents/phidata", response_model=PhidataResponse)
def phidata_agent(
    payload: PhidataRequest,
    auth=Depends(get_auth_context),
    container: ServiceContainer = Depends(get_container),
):
    _ = auth
    result = container.phidata.ask(payload.prompt)
    return PhidataResponse(**result)


@app.get("/stack", response_model=StackResponse)
def stack_info(container: ServiceContainer = Depends(get_container)):
    _ = container
    packages = [
        "fastapi",
        "uvicorn",
        "phidata",
        "python-dotenv",
        "yfinance",
        "packaging",
        "duckduckgo-search",
        "groq",
    ]
    return StackResponse(packages=get_dependency_versions(packages))
