from __future__ import annotations

import logging
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.core.config import Settings
from app.domain.models import AuthContext, QueryLog, QueryResponse, ResponseSource
from app.services.answer_style import infer_answer_style
from app.services.providers import (
    AnalyticsService,
    CacheService,
    EmbeddingService,
    LLMRouterService,
    LanguageService,
    RateLimiter,
    StorageService,
    VectorStoreService,
    WebSearchService,
    format_text_response,
    format_voice_response,
    is_ambiguous_query,
    is_sensitive_query,
    semantic_cache_key,
)

logger = logging.getLogger(__name__)


class RAGState(TypedDict, total=False):
    auth: AuthContext
    query: str
    detected_language: str
    translated_query: str
    cache_key: str
    cache_hit: bool
    response_source: ResponseSource
    answer: str
    citations: list[str]
    retrieval_score: float
    retrieval_context: list[str]
    needs_web_search: bool
    used_web_fallback: bool
    voice_mode: bool
    fast_mode: bool
    tokens_used: int
    started_at: float
    clarification_needed: bool
    source_tag: str
    llm_provider: str
    llm_model: str | None
    answer_style: str
    document_context_requested: bool


DOCUMENT_CONTEXT_PHRASES = (
    "uploaded",
    "upload",
    "attached",
    "attachment",
    "knowledge base",
    "kb",
    "retrieved context",
    "from the document",
    "from this document",
    "from the file",
    "from this file",
    "according to the document",
    "according to the file",
    "based on the document",
    "based on the file",
    "summarize the document",
    "summarise the document",
    "summarize this document",
    "summarise this document",
    "summarize the file",
    "summarise the file",
    "summarize this file",
    "summarise this file",
)

WEB_KNOWLEDGE_CONTEXT_PHRASES = (
    "w3schools",
    "geeksforgeeks",
    "gfg",
    "wikipedia",
    "wiki",
    "webpage",
    "website",
    "tutorial",
    "learn python",
    "learn html",
    "learn css",
    "learn javascript",
    "dsa",
    "data structure",
    "data structures",
    "algorithm",
    "algorithms",
    "python",
    "html",
    "css",
    "javascript",
    "java",
    "sql",
    "linked list",
    "array",
    "binary tree",
)

FILENAME_PATTERN = re.compile(r"\b[\w .-]+\.(?:pdf|txt|md|json)\b", re.IGNORECASE)
DOCUMENT_ACTION_PATTERN = re.compile(
    r"\b(?:summari[sz]e|analy[sz]e|explain|extract|find|search|read|review|compare|answer|"
    r"question|questions|tell me about|what does|what is in|inside)\b.{0,48}"
    r"\b(?:document|file|pdf|txt|attachment)\b",
    re.IGNORECASE,
)


class RAGWorkflow:
    def __init__(
        self,
        settings: Settings,
        cache: CacheService,
        rate_limiter: RateLimiter,
        language: LanguageService,
        vector_store: VectorStoreService,
        llm: LLMRouterService,
        web_search: WebSearchService,
        analytics: AnalyticsService,
        embedder: EmbeddingService,
        storage: StorageService,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.rate_limiter = rate_limiter
        self.language = language
        self.vector_store = vector_store
        self.llm = llm
        self.web_search = web_search
        self.analytics = analytics
        self.embedder = embedder
        self.storage = storage
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RAGState)
        graph.add_node("preprocess", self._preprocess)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("llm_reason", self._llm_reason)
        graph.add_node("web_search", self._web_search)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("preprocess")
        graph.add_conditional_edges(
            "preprocess",
            self._route_after_preprocess,
            {
                "finalize": "finalize",
                "retrieve": "retrieve",
            },
        )
        graph.add_conditional_edges(
            "retrieve",
            self._route_after_retrieve,
            {
                "finalize": "finalize",
                "llm_reason": "llm_reason",
            },
        )
        graph.add_conditional_edges(
            "llm_reason",
            self._route_after_llm,
            {
                "finalize": "finalize",
                "web_search": "web_search",
            },
        )
        graph.add_edge("web_search", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def run(self, auth: AuthContext, query: str, voice_mode: bool, fast_mode: bool) -> QueryResponse:
        state = self.graph.invoke(
            {
                "auth": auth,
                "query": query,
                "voice_mode": voice_mode,
                "fast_mode": fast_mode,
                "started_at": time.perf_counter(),
                "tokens_used": 0,
                "citations": [],
                "clarification_needed": False,
            }
        )
        latency_ms = int((time.perf_counter() - state["started_at"]) * 1000)
        detected_language = state["detected_language"]
        answer = state["answer"]
        translated_back = False
        if detected_language != "en" and self.language.is_supported(detected_language):
            answer = self.language.translate(answer, "en", detected_language)
            translated_back = True
        elif detected_language != "en":
            answer = (
                f"{answer}\n\nLanguage note: your language is not fully supported yet, "
                "so I responded in English."
            )

        self.cache.append_session_turn(
            key=f"session:{auth.user_id}",
            value={
                "query": query,
                "answer": answer,
                "source": state["response_source"].value,
                "llm_provider": state.get("llm_provider"),
                "llm_model": state.get("llm_model"),
                "latency_ms": latency_ms,
            },
            max_turns=10,
            ttl_seconds=self.settings.session_ttl_seconds,
        )

        self.analytics.log_query(
            QueryLog(
                query_text=query,
                detected_language=detected_language,
                response_source=state["response_source"],
                tokens_used=max(state["tokens_used"], len(query.split()) + len(answer.split())),
                latency_ms=latency_ms,
                user_role=auth.role,
                session_id=auth.session_id,
                user_id=auth.user_id,
                voice_mode=voice_mode,
                used_web_fallback=state["used_web_fallback"],
                retrieval_score=state["retrieval_score"],
                translated_to_en=detected_language != "en",
                translated_back=translated_back,
            )
        )

        if voice_mode:
            answer = format_voice_response(answer)
            if len(answer.split()) > 150:
                answer = " ".join(answer.split()[:150])
        else:
            answer = format_text_response(answer, state["source_tag"])

        return QueryResponse(
            answer=answer,
            source=state["response_source"],
            detected_language=detected_language,
            translated_language=detected_language if translated_back else None,
            llm_provider=state.get("llm_provider"),
            llm_model=state.get("llm_model"),
            answer_style=state.get("answer_style"),
            latency_ms=latency_ms,
            citations=state["citations"],
            used_web_fallback=state["used_web_fallback"],
            clarification_needed=state["clarification_needed"],
            confidence=self._confidence_from_score(state["retrieval_score"], state["response_source"]),
            source_coverage=self._source_coverage(state["retrieval_score"], state["citations"]),
        )

    def _preprocess(self, state: RAGState) -> RAGState:
        auth = state["auth"]
        self.rate_limiter.check(auth)
        detected_language = self.language.detect(state["query"])
        stripped_query = state["query"].strip().lower()
        if stripped_query in {"hi", "hello", "hey", "good morning", "good evening", "good afternoon"}:
            return {
                **state,
                "detected_language": detected_language,
                "translated_query": state["query"],
                "cache_key": semantic_cache_key(state["query"], detected_language),
                "cache_hit": False,
                "answer": "Hello. How can I help you?",
                "response_source": ResponseSource.none,
                "citations": [],
                "retrieval_score": 0.0,
                "used_web_fallback": False,
                "clarification_needed": False,
                "source_tag": "[No Source]",
                "llm_provider": "system",
                "llm_model": None,
            }
        if is_ambiguous_query(state["query"]):
            return {
                **state,
                "detected_language": detected_language,
                "translated_query": state["query"],
                "cache_key": semantic_cache_key(state["query"], detected_language),
                "cache_hit": False,
                "answer": "Could you clarify what you want me to help with?",
                "response_source": ResponseSource.none,
                "citations": [],
                "retrieval_score": 0.0,
                "used_web_fallback": False,
                "clarification_needed": True,
                "source_tag": "[No Source]",
                "llm_provider": "system",
                "llm_model": None,
            }
        translated_query = (
            self.language.translate(state["query"], detected_language, "en")
            if detected_language != "en" and self.language.is_supported(detected_language)
            else state["query"]
        )
        # Ensure we always request document context so that
        # any globally stored web-search memory can be queried.
        document_context_requested = True
        cache_scope = "doc" if document_context_requested else "general"
        cache_key = f"{cache_scope}:{semantic_cache_key(translated_query, 'en')}"
        cached = self.cache.get(cache_key)
        if cached:
            return {
                **state,
                "detected_language": detected_language,
                "translated_query": translated_query,
                "cache_key": cache_key,
                "cache_hit": True,
                "answer": cached["answer"],
                "response_source": ResponseSource.cache,
                "citations": ["[Cache]"],
                "retrieval_score": 1.0,
                "used_web_fallback": False,
                "clarification_needed": False,
                "source_tag": "[Cache]",
                "llm_provider": cached.get("llm_provider", "cache"),
                "llm_model": cached.get("llm_model"),
                "answer_style": cached.get("answer_style") or infer_answer_style(translated_query),
                "document_context_requested": document_context_requested,
            }

        return {
            **state,
            "detected_language": detected_language,
            "translated_query": translated_query,
            "cache_key": cache_key,
            "cache_hit": False,
            "used_web_fallback": False,
            "retrieval_score": 0.0,
            "clarification_needed": False,
            "document_context_requested": document_context_requested,
        }

    def _route_after_preprocess(self, state: RAGState) -> str:
        return "finalize" if state["cache_hit"] or state["clarification_needed"] else "retrieve"

    def _retrieve(self, state: RAGState) -> RAGState:
        if not state.get("document_context_requested", False):
            return {
                **state,
                "retrieval_score": 0.0,
                "retrieval_context": [],
                "citations": [],
            }

        results = self.vector_store.search(
            state["translated_query"],
            top_k=7,
            user_id=state["auth"].user_id,
        )
        retrieval_score = results[0].score if results else 0.0
        citations = self._format_citations(results)
        context = self._format_retrieval_context(results)
        logger.info(
            "RAG retrieval completed",
            extra={
                "query": state["translated_query"][:160],
                "retrieved_docs": len(results),
                "top_score": retrieval_score,
                "top_filenames": [item.metadata.get("filename") for item in results[:3]],
            },
        )
        if retrieval_score >= self.settings.similarity_threshold:
            result = self.llm.answer_with_context_result(
                state["translated_query"],
                context,
                fast_mode=state["fast_mode"],
            )
            return {
                **state,
                "answer": result["answer"],
                "response_source": ResponseSource.database,
                "citations": citations,
                "retrieval_score": retrieval_score,
                "retrieval_context": context,
                "source_tag": "[Database]",
                "llm_provider": result["provider"],
                "llm_model": result["model"],
                "answer_style": result.get("answer_style") or infer_answer_style(state["translated_query"]),
            }
        return {
            **state,
            "retrieval_score": retrieval_score,
            "retrieval_context": context,
            "citations": citations,
        }

    def _route_after_retrieve(self, state: RAGState) -> str:
        return "finalize" if state.get("response_source") == ResponseSource.database else "llm_reason"

    def _llm_reason(self, state: RAGState) -> RAGState:
        query = state["translated_query"].lower()
        unstable_keywords = {"latest", "today", "current", "price", "news", "recent"}
        context = state.get("retrieval_context", [])
        needs_web_search = False
        if not context:
            # The user explicitly wants: if not in database, search web and cache it.
            return {
                **state,
                "answer": "Searching the web for a reliable answer...",
                "response_source": ResponseSource.none,
                "citations": [],
                "needs_web_search": True,
                "source_tag": "[Web Search]",
                "llm_provider": "system",
                "llm_model": None,
            }

        needs_web_search = any(token in query for token in unstable_keywords)
        result = self.llm.answer_with_context_result(
            state["translated_query"],
            context,
            fast_mode=state["fast_mode"],
        )
        answer = result["answer"]
        if "information not found in the knowledge base" in answer.lower():
            needs_web_search = True
        if is_sensitive_query(state["translated_query"]):
            answer += (
                "\n\nDisclaimer: This information is general in nature and should not replace "
                "advice from a qualified professional."
            )
        return {
            **state,
            "answer": answer,
            "response_source": ResponseSource.llm,
            "citations": state.get("citations") or ["[Retrieved Context]"],
            "needs_web_search": needs_web_search,
            "source_tag": "[Retrieved Context]",
            "llm_provider": result["provider"],
            "llm_model": result["model"],
            "answer_style": result.get("answer_style") or infer_answer_style(state["translated_query"]),
        }

    def _route_after_llm(self, state: RAGState) -> str:
        return "web_search" if state.get("needs_web_search") else "finalize"

    def _web_search(self, state: RAGState) -> RAGState:
        results = self.web_search.search(state["translated_query"])
        if not results:
            return {
                **state,
                "answer": "I was unable to find reliable information for this query. Please rephrase or provide more context.",
                "response_source": ResponseSource.none,
                "citations": [],
                "used_web_fallback": True,
                "source_tag": "[Web Search]",
                "llm_provider": "system",
                "llm_model": None,
            }
        snippets = "\n\n".join(
            (
                f"Title: {item.get('title', '')}\n"
                f"Snippet: {item.get('snippet', '')}\n"
                f"URL: {item.get('url', '')}"
            ).strip()
            for item in results
            if item.get("title") or item.get("snippet")
        )
        if not snippets:
            return {
                **state,
                "answer": "I found search results, but they did not include enough readable detail to answer reliably.",
                "response_source": ResponseSource.none,
                "citations": [],
                "used_web_fallback": True,
                "source_tag": "[Web Search]",
                "llm_provider": "system",
                "llm_model": None,
            }
        result = self.llm.answer_with_context_result(
            state["translated_query"],
            [snippets],
            fast_mode=state["fast_mode"],
        )
        answer = result["answer"]
        self.storage.store_text(
            snippets,
            {
                "filename": "web-search-memory",
                "source": "web_search",
                "urls": [item["url"] for item in results],
            },
        )
        return {
            **state,
            "answer": answer,
            "response_source": ResponseSource.web_search,
            "citations": ["[Web Search]"] + [item["url"] for item in results],
            "used_web_fallback": True,
            "source_tag": "[Web Search]",
            "llm_provider": result["provider"],
            "llm_model": result["model"],
            "answer_style": result.get("answer_style") or infer_answer_style(state["translated_query"]),
        }

    def _finalize(self, state: RAGState) -> RAGState:
        if state["response_source"] not in {ResponseSource.cache, ResponseSource.none}:
            self.cache.set(
                state["cache_key"],
                {
                    "answer": state["answer"],
                    "source": state["response_source"].value,
                    "llm_provider": state.get("llm_provider"),
                    "llm_model": state.get("llm_model"),
                    "answer_style": state.get("answer_style"),
                },
                self.settings.cache_ttl_seconds,
            )
        return state

    @staticmethod
    def _format_citations(results: list[Any]) -> list[str]:
        citations: list[str] = []
        seen: set[str] = set()
        for item in results:
            filename = item.metadata.get("filename", "Document")
            pages = item.metadata.get("pages") or []
            if pages:
                page_label = ", ".join(f"Page {page}" for page in pages[:3])
                citation = f"{filename} - {page_label}"
            elif item.metadata.get("page"):
                citation = f"{filename} - Page {item.metadata['page']}"
            else:
                citation = f"{filename} - Chunk {item.metadata.get('chunk_index', '?')}"
            if citation not in seen:
                citations.append(citation)
                seen.add(citation)
        return citations[:5]

    @staticmethod
    def _format_retrieval_context(results: list[Any]) -> list[str]:
        context: list[str] = []
        for item in results:
            filename = item.metadata.get("filename", "Document")
            pages = item.metadata.get("pages") or []
            source = f"{filename}"
            if pages:
                source += f", page(s): {', '.join(str(page) for page in pages[:3])}"
            elif item.metadata.get("page"):
                source += f", page: {item.metadata['page']}"
            context.append(f"Source: {source}\nScore: {item.score:.2f}\n{item.content}")
        return context

    @staticmethod
    def _confidence_from_score(score: float, source: ResponseSource) -> float:
        if source == ResponseSource.cache:
            return 1.0
        if source == ResponseSource.web_search:
            return 0.65
        if source in {ResponseSource.database, ResponseSource.llm}:
            return round(max(0.2, min(0.98, score)), 2)
        return 0.0

    @staticmethod
    def _source_coverage(score: float, citations: list[str]) -> str:
        if not citations:
            return "none"
        if score >= 0.45:
            return "strong"
        if score >= 0.18:
            return "partial"
        return "weak"

    @staticmethod
    def _should_use_document_context(query: str) -> bool:
        normalized = query.lower()
        if FILENAME_PATTERN.search(query):
            return True
        if DOCUMENT_ACTION_PATTERN.search(query):
            return True
        return any(phrase in normalized for phrase in DOCUMENT_CONTEXT_PHRASES + WEB_KNOWLEDGE_CONTEXT_PHRASES)
