from __future__ import annotations

import base64
import binascii
import hashlib
from html.parser import HTMLParser
import ipaddress
import math
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
import logging
import jwt
try:
    import yfinance as yf
except Exception:
    yf = None
try:
    from duckduckgo_search import DDGS
except Exception:
    DDGS = None
from groq import Groq
from langdetect import DetectorFactory, LangDetectException, detect
from packaging.version import InvalidVersion, Version

try:
    from phi.agent import Agent as PhiAgent
    from phi.model.groq import Groq as PhiGroq
    from phi.tools.duckduckgo import DuckDuckGo as PhiDuckDuckGo
except Exception:
    PhiAgent = None
    PhiGroq = None
    PhiDuckDuckGo = None

from app.core.config import Settings
from app.domain.models import AuthContext, DocumentChunk, Feature, QueryLog, RetrievalResult, ROLE_FEATURES, SUPPORTED_LANGUAGE_CODES, UserRole
from app.infra.repositories import ChunkRepository, QueryLogRepository
from app.services.answer_style import infer_answer_style, prompt_rules_for_style, style_rules

DetectorFactory.seed = 0
logger = logging.getLogger(__name__)


def get_dependency_versions(packages: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in packages:
        try:
            raw = pkg_version(package)
        except PackageNotFoundError:
            versions[package] = "not-installed"
            continue
        try:
            versions[package] = str(Version(raw))
        except InvalidVersion:
            versions[package] = raw
    return versions


class PermissionError(Exception):
    """Raised when a role is not allowed to use a feature."""


class RateLimitError(Exception):
    """Raised when a user exceeded their plan limits."""


class AuthenticationError(Exception):
    """Raised when the JWT is invalid."""


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be converted into searchable text."""


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def validate(self, token: str) -> AuthContext:
        try:
            claims = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired token.") from exc

        role = UserRole(claims["role"])
        return AuthContext(
            user_id=str(claims["sub"]),
            role=role,
            session_id=str(claims.get("session_id", claims["sub"])),
            plan=claims.get("plan"),
            raw_claims=claims,
        )

    def issue_token(
        self,
        user_id: str,
        role: UserRole,
        session_id: str | None = None,
        plan: str | None = None,
        expires_in_minutes: int = 60,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "role": role.value,
            "session_id": session_id or f"session-{user_id}",
            "plan": plan or role.value,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=expires_in_minutes)).timestamp()),
        }
        return jwt.encode(payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)


class CacheService:
    def __init__(self) -> None:
        self._values: dict[str, tuple[Any, float | None]] = {}
        self._lists: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def get(self, key: str) -> Any | None:
        item = self._values.get(key)
        if not item:
            return None
        value, expires_at = item
        if expires_at and expires_at < time.time():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        self._values[key] = (value, expires_at)

    def append_session_turn(
        self,
        key: str,
        value: dict[str, Any],
        max_turns: int,
        ttl_seconds: int,
    ) -> None:
        turns = self._lists[key]
        turns.append(value)
        self._lists[key] = turns[-max_turns:]
        self.set(f"{key}:ttl", True, ttl_seconds)

    def get_session_turns(self, key: str) -> list[dict[str, Any]]:
        if self.get(f"{key}:ttl") is None:
            self._lists.pop(key, None)
            return []
        return self._lists.get(key, [])


class RateLimiter:
    def __init__(self, cache: CacheService, settings: Settings) -> None:
        self.cache = cache
        self.settings = settings

    def check(self, auth: AuthContext) -> None:
        if auth.role != UserRole.free_user:
            return
        today_key = f"rate:{auth.user_id}:{date.today().isoformat()}"
        count = int(self.cache.get(today_key) or 0)
        if count >= self.settings.free_user_daily_limit:
            raise RateLimitError("Daily query limit reached for the free plan.")
        self.cache.set(today_key, count + 1, 86400)


class LanguageService:
    def detect(self, text: str) -> str:
        try:
            code = detect(text)
        except LangDetectException:
            return "en"
        return code if code in SUPPORTED_LANGUAGE_CODES else "en"

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        return f"[Translated {source}->{target}] {text}"

    def is_supported(self, language_code: str) -> bool:
        return language_code in SUPPORTED_LANGUAGE_CODES


class EmbeddingService:
    @staticmethod
    def fingerprint(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

    def similarity(self, left: str, right: str) -> float:
        left_terms = self.fingerprint(left)
        right_terms = self.fingerprint(right)
        if not left_terms or not right_terms:
            return 0.0
        overlap = len(left_terms & right_terms)
        return overlap / math.sqrt(len(left_terms) * len(right_terms))


class VectorStoreService:
    def __init__(self, embedder: EmbeddingService, settings: Settings | None = None) -> None:
        self.embedder = embedder
        self.settings = settings
        self._documents: list[DocumentChunk] = []

    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        self._documents.extend(chunks)

    def remove_chunks_by_ids(self, chunk_ids: set[str]) -> int:
        if not chunk_ids:
            return 0
        before = len(self._documents)
        self._documents = [chunk for chunk in self._documents if chunk.chunk_id not in chunk_ids]
        return before - len(self._documents)

    def has_documents(self) -> bool:
        return bool(self._documents)

    def has_documents_for_user(self, user_id: str) -> bool:
        if not user_id:
            return False
        for chunk in self._documents:
            if chunk.metadata.get("uploaded_by") == user_id:
                return True
        return False

    def search(self, query: str, top_k: int = 5, *, user_id: str | None = None) -> list[RetrievalResult]:
        query_terms = self.embedder.fingerprint(query)
        if not query_terms:
            return []

        semantic_weight = self.settings.hybrid_semantic_weight if self.settings else 0.65
        keyword_weight = self.settings.hybrid_keyword_weight if self.settings else 0.35
        scored: list[RetrievalResult] = []
        for chunk in self._documents:
            if user_id and chunk.metadata.get("uploaded_by") not in {None, "", user_id}:
                continue
            chunk_terms = self.embedder.fingerprint(chunk.content)
            if not chunk_terms:
                continue
            semantic_score = self.embedder.similarity(query, chunk.content)
            keyword_score = len(query_terms & chunk_terms) / max(len(query_terms), 1)
            exact_phrase_bonus = 0.1 if query.lower() in chunk.content.lower() else 0.0
            score = min(
                1.0,
                (semantic_score * semantic_weight)
                + (keyword_score * keyword_weight)
                + exact_phrase_bonus,
            )
            scored.append(
                RetrievalResult(
                    content=chunk.content,
                    score=score,
                    metadata=chunk.metadata
                    | {
                        "chunk_id": chunk.chunk_id,
                        "semantic_score": round(semantic_score, 4),
                        "keyword_score": round(keyword_score, 4),
                    },
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]


class WebSearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, query: str) -> list[dict[str, str]]:
        if "???" in query or "noresult" in query.lower():
            return []
        provider = (self.settings.web_search_provider or "stub").strip().lower()
        if self._is_news_query(query) and self.settings.news_api_key:
            news_results = self._newsapi_search(query)
            if news_results:
                return news_results
        if provider == "duckduckgo":
            if DDGS is None:
                logger.warning("duckduckgo_search is not installed; using stub web search results.")
                return self._stub_results(query)
            return self._duckduckgo_search(query)
        return self._stub_results(query)

    @staticmethod
    def _stub_results(query: str) -> list[dict[str, str]]:
        return [
            {
                "title": "Stub web result",
                "url": "https://example.com/search-result",
                "snippet": f"Live-search fallback for: {query}",
            }
        ]

    @staticmethod
    def _is_news_query(query: str) -> bool:
        lowered = query.lower()
        return any(term in lowered for term in {"news", "latest", "breaking", "headline", "headlines", "today"})

    @staticmethod
    def _country_from_query(query: str) -> str | None:
        lowered = query.lower()
        country_terms = {
            "india": "in",
            "indian": "in",
            "usa": "us",
            "u.s.": "us",
            "united states": "us",
            "america": "us",
            "uk": "gb",
            "united kingdom": "gb",
            "britain": "gb",
            "canada": "ca",
            "australia": "au",
        }
        for term, code in country_terms.items():
            if term in lowered:
                return code
        return None

    @staticmethod
    def _clean_news_query(query: str) -> str:
        cleaned = query.lower()
        cleaned = re.sub(r"\b(latest|breaking|today'?s?|current|recent|news|headlines?|in|about|related to)\b", " ", cleaned)
        cleaned = re.sub(r"\b(india|indian|usa|u\.s\.|united states|america|uk|united kingdom|britain|canada|australia)\b", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _newsapi_search(self, query: str) -> list[dict[str, str]]:
        if not self.settings.news_api_key:
            return []

        country = self._country_from_query(query)
        cleaned_query = self._clean_news_query(query)
        endpoint = "https://newsapi.org/v2/top-headlines" if country else "https://newsapi.org/v2/everything"
        params: dict[str, Any] = {
            "apiKey": self.settings.news_api_key,
            "pageSize": self.settings.news_api_max_results,
        }
        if country:
            params["country"] = country
            if cleaned_query:
                params["q"] = cleaned_query
        else:
            params.update(
                {
                    "q": cleaned_query or query,
                    "language": "en",
                    "sortBy": "publishedAt",
                }
            )

        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.exception("News API search failed", exc_info=exc)
            return []

        articles = payload.get("articles") or []
        normalized: list[dict[str, str]] = []
        for article in articles:
            title = article.get("title") or ""
            description = article.get("description") or ""
            content = article.get("content") or ""
            published_at = article.get("publishedAt") or ""
            source_name = (article.get("source") or {}).get("name") or "News API"
            url = article.get("url") or ""
            snippet_parts = [part for part in [title, description, content] if part]
            snippet = " ".join(snippet_parts)
            if published_at or source_name:
                snippet = f"{snippet} Published: {published_at}. Source: {source_name}.".strip()
            if title or snippet:
                normalized.append(
                    {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                    }
                )
        return normalized

    def _duckduckgo_search(self, query: str) -> list[dict[str, str]]:
        if DDGS is None:
            return self._stub_results(query)
        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=self.settings.duckduckgo_max_results)
                normalized = []
                for item in results:
                    normalized.append(
                        {
                            "title": item.get("title") or "",
                            "url": item.get("href") or item.get("url") or "",
                            "snippet": item.get("body") or "",
                        }
                    )
                return normalized
        except Exception as exc:
            logger.exception("DuckDuckGo search failed", exc_info=exc)
            return []


class ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._links: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if len(cleaned) >= 2:
            self._text_parts.append(cleaned)

    @property
    def text(self) -> str:
        return "\n".join(self._text_parts)

    @property
    def links(self) -> list[str]:
        return self._links


class WebsiteKnowledgeService:
    ALLOWED_HOSTS = {
        "www.w3schools.com",
        "w3schools.com",
        "www.geeksforgeeks.org",
        "geeksforgeeks.org",
        "www.wikipedia.org",
        "wikipedia.org",
        "en.wikipedia.org",
    }
    PRIORITY_TERMS = (
        "python",
        "html",
        "css",
        "javascript",
        "java",
        "sql",
        "data-structures",
        "algorithm",
        "dsa",
        "wiki",
        "computer",
        "programming",
    )

    def __init__(self, settings: Settings, storage: "StorageService") -> None:
        self.settings = settings
        self.storage = storage

    def seed(self, urls: list[str] | None = None, max_pages_per_site: int | None = None) -> dict[str, Any]:
        start_urls = urls or self._settings_urls()
        per_site_limit = max_pages_per_site or self.settings.web_knowledge_max_pages_per_site
        fetched_urls: list[str] = []
        errors: list[str] = []
        chunks_stored = 0

        for start_url in start_urls:
            normalized_start = self._normalize_url(start_url)
            if not normalized_start or not self._is_allowed_url(normalized_start):
                errors.append(f"Skipped unsafe or unsupported URL: {start_url}")
                continue

            queue = [normalized_start]
            seen: set[str] = set()
            fetched_for_site = 0
            base_host = urlparse(normalized_start).netloc.lower()

            while queue and fetched_for_site < per_site_limit:
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                if not self._is_allowed_url(url):
                    continue
                if urlparse(url).netloc.lower() != base_host and base_host != "www.wikipedia.org":
                    continue

                try:
                    page = self._fetch_page(url)
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
                    continue

                if len(page["text"]) < 300:
                    continue

                chunks_stored += self._store_page(url, page["text"])
                fetched_urls.append(url)
                fetched_for_site += 1

                next_links = self._prioritize_links(page["links"], url)
                for link in next_links:
                    if link not in seen and link not in queue:
                        queue.append(link)

        return {
            "pages_fetched": len(fetched_urls),
            "chunks_stored": chunks_stored,
            "urls": fetched_urls,
            "errors": errors[:20],
        }

    def _settings_urls(self) -> list[str]:
        return [
            item.strip()
            for item in self.settings.web_knowledge_seed_urls.split(",")
            if item.strip()
        ]

    def _fetch_page(self, url: str) -> dict[str, Any]:
        headers = {"User-Agent": f"{self.settings.app_name}/0.1 educational-rag-seeder"}
        with httpx.Client(timeout=self.settings.web_knowledge_request_timeout, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type:
                raise ValueError(f"Unsupported content type: {content_type}")

        parser = ReadableHTMLParser()
        parser.feed(response.text)
        return {
            "text": self._clean_text(parser.text),
            "links": parser.links,
        }

    def _store_page(self, url: str, text: str) -> int:
        host = urlparse(url).netloc.lower()
        filename = f"web-{host}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}.txt"
        result = self.storage.store_document(
            filename,
            f"Source URL: {url}\nSource website: {host}\n\n{text}",
            {
                "source": "seeded_website",
                "source_url": url,
                "website_host": host,
            },
            content_encoding="text",
        )
        return int(result["chunks_stored"])

    def _prioritize_links(self, links: list[str], base_url: str) -> list[str]:
        normalized_links = []
        for href in links:
            link = self._normalize_url(urljoin(base_url, href))
            if link and self._is_allowed_url(link):
                normalized_links.append(link)
        unique_links = list(dict.fromkeys(normalized_links))
        unique_links.sort(key=self._priority_score)
        return unique_links[:40]

    def _priority_score(self, url: str) -> int:
        lowered = url.lower()
        if any(term in lowered for term in self.PRIORITY_TERMS):
            return 0
        return 1

    def _normalize_url(self, url: str) -> str | None:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            return None
        clean_url, _fragment = urldefrag(url)
        return clean_url.rstrip("/") + "/"

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        if hostname in {"localhost", "127.0.0.1", "0.0.0.0"} or hostname.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
        )

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


class OpenRouterLLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api_key = settings.openrouter_api_key
        self.base_url = "https://openrouter.ai/api/v1"
        self.headers = self._build_headers(settings)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _build_headers(settings: Settings) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.openrouter_api_key:
            headers["Authorization"] = f"Bearer {settings.openrouter_api_key}"
        if settings.openrouter_referer:
            headers["HTTP-Referer"] = settings.openrouter_referer
        if settings.app_name:
            headers["X-Title"] = settings.app_name
        return headers

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OpenRouter is not configured. Please add OPENROUTER_API_KEY.")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            if response.status_code >= 400:
                detail = response.text.strip()
                raise RuntimeError(f"{response.status_code} {response.reason_phrase}: {detail}")
            return response.json()

    def answer_with_context(
        self,
        query: str,
        context: list[str],
        model: str | None = None,
        max_tokens: int | None = None,
        answer_style: str = "detailed",
    ) -> str:
        if not self.api_key:
            return "OpenRouter is not configured. Please add OPENROUTER_API_KEY."

        system_prompt = (
            "You are a helpful RAG assistant."
            "\nRules:"
            "\n1) First, evaluate if the provided context is actually relevant to the user's explicit question."
            "\n2) If the context is completely irrelevant to the question, completely IGNORE the context and answer from your general knowledge. If you do not know the answer, say 'Information not found in the knowledge base.'"
            "\n3) If the context is relevant, use ONLY the provided context to answer the question, do not hallucinate outside facts."
            "\n4) When source/page labels are present and you use them, mention the relevant page or source in the answer."
            "\n5) For coding questions, format nicely. NEVER output inline code blocks like ```python without placing them on their own new lines."
            f"{prompt_rules_for_style(answer_style, rag=True)}"
        )
        if context:
            context_str = "\n".join(context)
            system_prompt += f"\n\nContext:\n{context_str}"
        try:
            payload = {
                "model": model or self.settings.openrouter_default_model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens
            response = self._post_chat_completion(payload)
            return response["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.exception("OpenRouter call failed", exc_info=exc)
            return (
                "The OpenRouter service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )

    def general_answer(
        self,
        query: str,
        model: str | None = None,
        max_tokens: int | None = None,
        answer_style: str = "detailed",
    ) -> str:
        """Answer using the LLM's own knowledge, without restricting to a context."""
        if not self.api_key:
            return "OpenRouter is not configured. Please add OPENROUTER_API_KEY."
        system_prompt = (
            "You are a highly knowledgeable, helpful AI assistant. "
            "Answer the user's question accurately, concisely, and clearly. "
            "If you are unsure, say so honestly. "
            "For coding questions, use Markdown with fenced ```language code blocks, 'Output:' lines, bullet lists, and **bold** key terms."
            f"{prompt_rules_for_style(answer_style)}"
        )
        try:
            payload = {
                "model": model or self.settings.openrouter_default_model,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens
            response = self._post_chat_completion(payload)
            return response["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.exception("OpenRouter general_answer failed", exc_info=exc)
            return (
                "The OpenRouter service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )

    def summarize(self, text: str, instructions: str, model: str | None = None, max_tokens: int | None = None) -> str:
        if not self.api_key:
            return "OpenRouter is not configured. Please add OPENROUTER_API_KEY."
        try:
            payload = {
                "model": model or self.settings.openrouter_fast_model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text[:8000]},
                ],
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens
            response = self._post_chat_completion(payload)
            return response["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            logger.exception("OpenRouter call failed", exc_info=exc)
            return (
                "The OpenRouter service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )

    def analyze_image(self, image_name: str, question: str) -> str:
        if not self.api_key:
            return "OpenRouter is not configured. Please add OPENROUTER_API_KEY."
        return (
            f"OpenRouter vision is configured to use '{self.settings.openrouter_vision_model}'. "
            f"Image analysis will answer the question: {question}"
        )


class GroqLLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = Groq(api_key=settings.groq_api_key) if settings.groq_api_key else None

    def is_configured(self) -> bool:
        return self.client is not None

    def answer_with_context(
        self,
        query: str,
        context: list[str],
        max_tokens: int | None = None,
        answer_style: str = "detailed",
    ) -> str:
        if not self.client:
            return "Groq is not configured. Please add GROQ_API_KEY."
        system_prompt = (
            "You are a helpful RAG assistant."
            "\nRules:"
            "\n1) First, evaluate if the provided context is actually relevant to the user's explicit question."
            "\n2) If the context is completely irrelevant to the question, completely IGNORE the context and answer from your own knowledge, or if you don't know, say 'Information not found in the knowledge base.'"
            "\n3) If the context is relevant, use ONLY the provided context to answer the question, do not hallucinate."
            "\n4) When source/page labels are present and you use them, mention the relevant page or source in the answer."
            "\n5) For coding questions, format nicely. NEVER output inline code blocks like ```python without placing them on their own new lines."
            f"{prompt_rules_for_style(answer_style, rag=True)}"
        )
        if context:
            context_str = "\n".join(context)
            context_str = context_str[: self.settings.groq_context_max_chars]
            system_prompt += f"\n\nContext:\n{context_str}"
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.groq_model,
                temperature=self.settings.groq_temperature,
                max_tokens=max_tokens or self.settings.groq_max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            logger.exception("Groq call failed", exc_info=exc)
            return (
                "The Groq service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )

    def general_answer(
        self,
        query: str,
        max_tokens: int | None = None,
        answer_style: str = "detailed",
    ) -> str:
        """Answer using the LLM's own knowledge, without restricting to a context."""
        if not self.client:
            return "Groq is not configured. Please add GROQ_API_KEY."
        system_prompt = (
            "You are a highly knowledgeable, helpful AI assistant. "
            "Answer the user's question accurately, concisely, and clearly. "
            "If you are unsure, say so honestly. "
            "For coding questions, keep the explanation short and put every code sample in fenced Markdown code blocks with the language name."
            f"{prompt_rules_for_style(answer_style)}"
        )
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.groq_model,
                temperature=0.3,
                max_tokens=max_tokens or self.settings.groq_max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            logger.exception("Groq general_answer failed", exc_info=exc)
            return (
                "The Groq service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )

    def summarize(self, text: str, instructions: str, max_tokens: int | None = None) -> str:
        if not self.client:
            return "Groq is not configured. Please add GROQ_API_KEY."
        try:
            completion = self.client.chat.completions.create(
                model=self.settings.groq_model,
                temperature=self.settings.groq_temperature,
                max_tokens=max_tokens or self.settings.groq_max_tokens,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text[: self.settings.groq_context_max_chars]},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            logger.exception("Groq call failed", exc_info=exc)
            return (
                "The Groq service is unavailable. "
                "Please verify your API key, model name, and billing, then try again."
            )


class FinanceService:
    def quote(self, symbol: str, period: str = "5d", interval: str = "1d") -> dict[str, Any]:
        if yf is None:
            raise RuntimeError(
                "Finance data is unavailable. Install yfinance in the project virtual environment."
            )
        ticker = yf.Ticker(symbol)
        history = ticker.history(period=period, interval=interval)
        if history.empty:
            raise ValueError("No price history returned for symbol.")

        latest = history.iloc[-1]
        previous = history.iloc[-2] if len(history) > 1 else latest
        price = float(latest["Close"])
        prev_close = float(previous["Close"]) if "Close" in previous else None
        change = price - prev_close if prev_close is not None else None
        change_percent = (change / prev_close * 100.0) if prev_close else None

        currency = None
        try:
            currency = getattr(ticker, "fast_info", {}).get("currency")
        except Exception:
            currency = None

        last_updated = None
        try:
            last_updated = latest.name.to_pydatetime()
        except Exception:
            last_updated = None

        return {
            "symbol": symbol.upper(),
            "price": price,
            "previous_close": prev_close,
            "change": change,
            "change_percent": change_percent,
            "currency": currency,
            "last_updated": last_updated,
        }


class PhidataAgentService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_available(self) -> bool:
        return bool(PhiAgent and PhiGroq and self.settings.groq_api_key)

    def ask(self, prompt: str) -> dict[str, Any]:
        if not self.is_available():
            return {
                "answer": "Phidata is not configured. Add GROQ_API_KEY to enable the agent.",
                "provider": "unavailable",
                "used_tools": [],
            }

        tools = []
        if PhiDuckDuckGo:
            tools.append(PhiDuckDuckGo())

        model = self._build_model()
        if not model:
            return {
                "answer": "Phidata is available, but the Groq model could not be initialized.",
                "provider": "unavailable",
                "used_tools": [],
            }

        agent = PhiAgent(
            name="PhidataAgent",
            model=model,
            tools=tools,
            instructions=[
                "Use tools only when needed.",
                "Keep answers concise and helpful.",
            ],
        )

        try:
            response = self._run_agent(agent, prompt)
        except Exception as exc:
            logger.exception("Phidata agent failed", exc_info=exc)
            return {
                "answer": "Phidata agent failed to respond. Please check logs.",
                "provider": "phidata",
                "used_tools": [tool.__class__.__name__ for tool in tools],
            }

        if hasattr(response, "content"):
            answer = response.content
        else:
            answer = str(response)

        return {
            "answer": answer,
            "provider": "phidata",
            "used_tools": [tool.__class__.__name__ for tool in tools],
        }

    def _build_model(self) -> Any | None:
        try:
            return PhiGroq(api_key=self.settings.groq_api_key, id=self.settings.groq_model)
        except TypeError:
            try:
                return PhiGroq(api_key=self.settings.groq_api_key, model=self.settings.groq_model)
            except Exception:
                return None

    @staticmethod
    def _run_agent(agent: Any, prompt: str) -> Any:
        if hasattr(agent, "run"):
            return agent.run(prompt)
        if hasattr(agent, "respond"):
            return agent.respond(prompt)
        raise RuntimeError("Unsupported phidata agent interface.")


class LLMRouterService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.openrouter = OpenRouterLLMService(settings)
        self.groq = GroqLLMService(settings)

    def answer_with_context(self, query: str, context: list[str], fast_mode: bool = False) -> str:
        return self.answer_with_context_result(query, context, fast_mode)["answer"]

    def answer_with_context_result(self, query: str, context: list[str], fast_mode: bool = False) -> dict[str, str | None]:
        answer_style = infer_answer_style(query)
        # When there is no context, fall back to general knowledge immediately
        if not context:
            return self.general_answer_result(query, fast_mode=fast_mode)

        if fast_mode and self.groq.is_configured():
            condensed = self._condense_context_if_needed(context, fast_mode=fast_mode, provider="groq")
            answer = self.groq.answer_with_context(
                query,
                condensed,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "groq"),
                answer_style=answer_style,
            )
            if not self._groq_failed(answer) and "information not found" not in answer.lower():
                return {
                    "answer": answer,
                    "provider": "groq",
                    "model": self.settings.groq_model,
                    "answer_style": answer_style,
                }
        if fast_mode and self.openrouter.is_configured():
            condensed = self._condense_context_if_needed(context, fast_mode=fast_mode, provider="openrouter")
            model = self.settings.openrouter_fast_model
            answer = self.openrouter.answer_with_context(
                query,
                condensed,
                model=model,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "openrouter"),
                answer_style=answer_style,
            )
            if not self._openrouter_failed(answer) and "information not found" not in answer.lower():
                return {
                    "answer": answer,
                    "provider": "openrouter",
                    "model": model,
                    "answer_style": answer_style,
                }
            if self.groq.is_configured():
                groq_answer = self.groq.answer_with_context(
                    query,
                    condensed,
                    max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "groq"),
                    answer_style=answer_style,
                )
                if not self._groq_failed(groq_answer):
                    return {
                        "answer": groq_answer,
                        "provider": "groq",
                        "model": self.settings.groq_model,
                        "answer_style": answer_style,
                    }
            return self.general_answer_result(query, fast_mode=fast_mode)

        task_type = self._infer_task_type(query)
        if self._should_use_groq(task_type, query, context):
            condensed = self._condense_context_if_needed(context, fast_mode=False, provider="groq")
            answer = self.groq.answer_with_context(
                query,
                condensed,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "groq"),
                answer_style=answer_style,
            )
            if not self._groq_failed(answer) and "information not found" not in answer.lower():
                return {
                    "answer": answer,
                    "provider": "groq",
                    "model": self.settings.groq_model,
                    "answer_style": answer_style,
                }
        if self._should_use_openrouter(task_type, query, context):
            model = self._select_openrouter_model(task_type)
            condensed = self._condense_context_if_needed(context, fast_mode=False, provider="openrouter")
            answer = self.openrouter.answer_with_context(
                query,
                condensed,
                model=model,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "openrouter"),
                answer_style=answer_style,
            )
            if not self._openrouter_failed(answer) and "information not found" not in answer.lower():
                return {
                    "answer": answer,
                    "provider": "openrouter",
                    "model": model,
                    "answer_style": answer_style,
                }
            if self.groq.is_configured():
                groq_answer = self.groq.answer_with_context(
                    query,
                    condensed,
                    max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "groq"),
                    answer_style=answer_style,
                )
                if not self._groq_failed(groq_answer):
                    return {
                        "answer": groq_answer,
                        "provider": "groq",
                        "model": self.settings.groq_model,
                        "answer_style": answer_style,
                    }

        return {
            "answer": self._unconfigured_message(),
            "provider": "unconfigured",
            "model": None,
            "answer_style": answer_style,
        }

    def general_answer(self, query: str, fast_mode: bool = False) -> str:
        return self.general_answer_result(query, fast_mode)["answer"]

    def general_answer_result(self, query: str, fast_mode: bool = False) -> dict[str, str | None]:
        """Answer using the LLM's own knowledge when no context is available."""
        answer_style = infer_answer_style(query)
        prompt_query = self._format_coding_query(query) if answer_style == "coding" else query
        if self.groq.is_configured():
            answer = self.groq.general_answer(
                prompt_query,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "groq"),
                answer_style=answer_style,
            )
            if not self._groq_failed(answer):
                return {
                    "answer": answer,
                    "provider": "groq",
                    "model": self.settings.groq_model,
                    "answer_style": answer_style,
                }
        if self.openrouter.is_configured():
            model = (
                self.settings.openrouter_fast_model
                if fast_mode
                else self.settings.openrouter_default_model
            )
            answer = self.openrouter.general_answer(
                prompt_query,
                model=model,
                max_tokens=self._max_tokens_for_style(answer_style, fast_mode, "openrouter"),
                answer_style=answer_style,
            )
            if not self._openrouter_failed(answer):
                return {
                    "answer": answer,
                    "provider": "openrouter",
                    "model": model,
                    "answer_style": answer_style,
                }
        return {
            "answer": self._unconfigured_message(),
            "provider": "unconfigured",
            "model": None,
            "answer_style": answer_style,
        }

    def _max_tokens_for_style(self, style: str, fast_mode: bool, provider: str) -> int:
        if style == "brief":
            return 220 if provider == "groq" else 320
        if style == "coding":
            if provider == "groq":
                return self.settings.groq_max_tokens
            return self.settings.openrouter_max_tokens
        if fast_mode:
            if provider == "groq":
                return self.settings.groq_max_tokens
            return self.settings.openrouter_fast_max_tokens
        if provider == "groq":
            return self.settings.groq_max_tokens
        return self.settings.openrouter_max_tokens

    def summarize(self, text: str, instructions: str, fast_mode: bool = False) -> str:
        task_type = "summary"
        if self._should_use_groq(task_type, text, []):
            answer = self.groq.summarize(
                text,
                instructions,
                max_tokens=self.settings.groq_max_tokens,
            )
            if not self._groq_failed(answer):
                return answer
        if self._should_use_openrouter(task_type, text, []):
            model = self._select_openrouter_model(task_type)
            answer = self.openrouter.summarize(
                text,
                instructions,
                model=model,
                max_tokens=self.settings.openrouter_fast_max_tokens if fast_mode else self.settings.openrouter_max_tokens,
            )
            if not self._openrouter_failed(answer):
                return answer
            if self.groq.is_configured():
                groq_answer = self.groq.summarize(
                    text,
                    instructions,
                    max_tokens=self.settings.groq_max_tokens,
                )
                if not self._groq_failed(groq_answer):
                    return groq_answer
        return self._unconfigured_message()

    def analyze_image(self, image_name: str, question: str) -> str:
        if self.openrouter.is_configured() and self.settings.openrouter_vision_model:
            return self.openrouter.analyze_image(image_name, question)
        return self._unconfigured_message("vision")

    def is_uncertain(self, query: str, context: list[str]) -> bool:
        short_query = len(query.split()) <= 2
        empty_context = not any(item.strip() for item in context)
        return short_query or empty_context

    def _should_use_openrouter(self, task_type: str, query: str, context: list[str]) -> bool:
        if not self.openrouter.is_configured():
            return False
        if task_type in {"reasoning", "coding", "planning"}:
            return True
        if len(query.split()) >= 60:
            return True
        if any(token in query.lower() for token in {"debug", "refactor", "stack trace", "traceback"}):
            return True
        if context and len("\n".join(context)) > self.settings.openrouter_context_max_chars:
            return True
        return False

    def _should_use_groq(self, task_type: str, query: str, context: list[str]) -> bool:
        if not self.groq.is_configured():
            return False
        if not self.openrouter.is_configured():
            return True
        if task_type in {"rag", "summary"} and len(query.split()) < 40:
            return True
        return False

    @staticmethod
    def _groq_failed(answer: str) -> bool:
        lowered = answer.lower()
        return "groq is not configured" in lowered or "groq service is unavailable" in lowered

    @staticmethod
    def _openrouter_failed(answer: str) -> bool:
        lowered = answer.lower()
        return (
            "openrouter is not configured" in lowered
            or "openrouter service is unavailable" in lowered
        )

    def _infer_task_type(self, query: str) -> str:
        if is_coding_query(query):
            return "coding"
        lowered = query.lower()
        if any(token in lowered for token in {"plan", "strategy", "architecture", "design", "tradeoff", "analysis"}):
            return "reasoning"
        if "summar" in lowered:
            return "summary"
        return "rag"

    @staticmethod
    def _format_coding_query(query: str) -> str:
        return (
            f"{query}\n\n"
            "Formatting requirements for this coding answer:"
            f"{style_rules('coding')}"
        )

    def _select_openrouter_model(self, task_type: str) -> str:
        if task_type == "coding":
            return self.settings.openrouter_coding_model
        if task_type == "reasoning" or task_type == "planning":
            return self.settings.openrouter_reasoning_model
        if task_type == "summary":
            return self.settings.openrouter_fast_model
        return self.settings.openrouter_default_model

    def _condense_context_if_needed(self, context: list[str], fast_mode: bool, provider: str) -> list[str]:
        if not context:
            return []
        joined = "\n".join(context)
        if provider == "groq":
            max_chars = (
                self.settings.groq_fast_context_max_chars
                if fast_mode
                else self.settings.groq_context_max_chars
            )
        else:
            max_chars = (
                self.settings.openrouter_fast_context_max_chars
                if fast_mode
                else self.settings.openrouter_context_max_chars
            )
        if len(joined) <= max_chars:
            return context
        summary = self.summarize(joined, "Summarize the context for a RAG answer.", fast_mode=fast_mode)
        if summary == self._unconfigured_message():
            return [joined[:max_chars]]
        return [summary[:max_chars]]

    @staticmethod
    def _unconfigured_message(capability: str = "llm") -> str:
        if capability == "vision":
            return "No vision provider is configured. Add OPENROUTER_API_KEY to enable image analysis."
        return "No LLM provider is configured. Add GROQ_API_KEY or OPENROUTER_API_KEY."


class DocumentService:
    @staticmethod
    def sanitize_text(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text.replace("\x00", "")).strip()

    def prepare_content(
        self,
        filename: str,
        content: str,
        content_encoding: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix != "pdf":
            clean_content = self.sanitize_text(content)
            if not clean_content:
                raise ValueError("Uploaded document did not contain readable text.")
            return clean_content, {
                "parser": "plain-text",
                "text_length": len(clean_content),
                "extraction_status": "ok",
            }

        pdf_bytes = self._decode_pdf_content(content, content_encoding)
        extracted_text, extraction_meta = self.extract_pdf_text(pdf_bytes)
        clean_content = self.sanitize_text(extracted_text)
        if not clean_content:
            extracted_text, extraction_meta = self.extract_pdf_text_with_ocr(pdf_bytes, extraction_meta)
            clean_content = self.sanitize_text(extracted_text)
        extraction_meta["text_length"] = len(clean_content)
        if not clean_content:
            raise PDFExtractionError(
                "No readable text was found in this PDF. It may be scanned or image-only; "
                "please run OCR before uploading or install an OCR pipeline such as OCRmyPDF/Tesseract."
            )
        return clean_content, extraction_meta | {"extraction_status": "ok"}

    def _decode_pdf_content(self, content: str, content_encoding: str | None) -> bytes:
        raw_content = content.strip()
        if raw_content.startswith("data:"):
            raw_content = raw_content.split(",", 1)[-1]
            content_encoding = "base64"

        if (content_encoding or "").lower() == "base64":
            try:
                return base64.b64decode(raw_content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise PDFExtractionError("The uploaded PDF content is not valid base64.") from exc

        if raw_content.startswith("%PDF"):
            return raw_content.encode("latin-1", errors="ignore")

        raise PDFExtractionError(
            "PDF uploads must be sent as base64 content so the backend can extract text correctly."
        )

    def extract_pdf_text(self, pdf_bytes: bytes) -> tuple[str, dict[str, Any]]:
        try:
            return self._extract_pdf_text_with_pymupdf(pdf_bytes)
        except ModuleNotFoundError:
            logger.info("PyMuPDF is not installed; falling back to pypdf for PDF extraction.")
        except Exception as exc:
            logger.exception("PyMuPDF PDF extraction failed; trying pypdf fallback.", exc_info=exc)

        try:
            return self._extract_pdf_text_with_pypdf(pdf_bytes)
        except ModuleNotFoundError as exc:
            raise PDFExtractionError(
                "PDF parsing dependencies are missing. Install PyMuPDF or pypdf, then restart the backend."
            ) from exc
        except Exception as exc:
            logger.exception("PDF text extraction failed", exc_info=exc)
            raise PDFExtractionError(f"PDF text extraction failed: {exc}") from exc

    @staticmethod
    def _extract_pdf_text_with_pymupdf(pdf_bytes: bytes) -> tuple[str, dict[str, Any]]:
        import fitz

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_texts = [
                f"[Page {page_number}]\n{page.get_text('text')}"
                for page_number, page in enumerate(doc, start=1)
            ]
            return "\n\n".join(page_texts), {
                "parser": "pymupdf",
                "page_count": doc.page_count,
            }

    @staticmethod
    def _extract_pdf_text_with_pypdf(pdf_bytes: bytes) -> tuple[str, dict[str, Any]]:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        page_texts = [
            f"[Page {page_number}]\n{page.extract_text() or ''}"
            for page_number, page in enumerate(reader.pages, start=1)
        ]
        return "\n\n".join(page_texts), {
            "parser": "pypdf",
            "page_count": len(reader.pages),
        }

    def extract_pdf_text_with_ocr(
        self,
        pdf_bytes: bytes,
        base_meta: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            import fitz
            from PIL import Image
            import pytesseract
        except ModuleNotFoundError:
            logger.warning("OCR fallback skipped because pytesseract/Pillow/PyMuPDF is not installed.")
            return "", (base_meta or {}) | {"ocr_attempted": False, "ocr_status": "missing-dependency"}

        try:
            page_texts: list[str] = []
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.open(BytesIO(pix.tobytes("png")))
                    page_texts.append(f"[Page {page.number + 1}]\n{pytesseract.image_to_string(image)}")
                return "\n\n".join(page_texts), (base_meta or {}) | {
                    "parser": "pytesseract-ocr",
                    "page_count": doc.page_count,
                    "ocr_attempted": True,
                    "ocr_status": "ok",
                }
        except Exception as exc:
            logger.exception("PDF OCR fallback failed", exc_info=exc)
            return "", (base_meta or {}) | {"ocr_attempted": True, "ocr_status": f"failed: {exc}"}

    def chunk(
        self,
        filename: str,
        content: str,
        max_chars: int = 1000,
        overlap: int = 200,
    ) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        clean_content = self.sanitize_text(content)
        if not clean_content:
            return chunks

        step = max(1, max_chars - overlap)
        for index, start in enumerate(range(0, len(clean_content), step), start=1):
            chunk_text = clean_content[start : start + max_chars].strip()
            if not chunk_text:
                continue
            page_matches = re.findall(r"\[Page\s+(\d+)\]", chunk_text)
            pages = sorted({int(page) for page in page_matches})
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{filename}-{index}",
                    content=chunk_text,
                    metadata={
                        "filename": filename,
                        "chunk_index": index,
                        "char_start": start,
                        "char_end": start + len(chunk_text),
                        "pages": pages,
                        "page": pages[0] if pages else None,
                    },
                )
            )
            if start + max_chars >= len(clean_content):
                break
        return chunks

    @staticmethod
    def suggested_questions(filename: str, chunks: list[DocumentChunk]) -> list[str]:
        base = [
            f"Summarize {filename} with key points.",
            "What are the main risks or concerns in this document?",
            "Extract action items, decisions, and deadlines.",
            "Which sections or pages should I review first?",
        ]
        text = "\n".join(chunk.content[:300] for chunk in chunks[:4]).lower()
        if any(term in text for term in {"revenue", "profit", "cost", "budget", "financial"}):
            base.insert(2, "Find the important financial metrics and trends.")
        if any(term in text for term in {"architecture", "system", "workflow", "pipeline"}):
            base.insert(2, "Explain the architecture or workflow in simple terms.")
        return base[:5]

    def summarize_document(
        self,
        filename: str,
        content: str,
        page_count: int,
        llm: LLMRouterService,
    ) -> dict[str, Any]:
        chunks = self.chunk(filename, content)
        if page_count < 5:
            core_summary = llm.summarize(content, "Direct summary")
        else:
            map_summaries = [llm.summarize(chunk.content, "Chunk summary") for chunk in chunks]
            core_summary = llm.summarize("\n".join(map_summaries), "Reduced summary")

        key_points = []
        for sentence in re.split(r"(?<=[.!?])\s+", content.strip()):
            if sentence:
                key_points.append(sentence[:160])
            if len(key_points) == 5:
                break

        return {
            "title": filename,
            "executive_summary": core_summary[:600],
            "key_points": key_points,
            "follow_up_questions": [
                "What are the main risks or decisions in this document?",
                "Can you extract action items from this file?",
                "Would you like a shorter executive brief?",
            ],
            "chunks": chunks,
        }


class ProfileService:
    def get_user_profile(self, auth: AuthContext) -> dict[str, Any]:
        return {
            "user_id": auth.user_id,
            "plan": auth.plan or auth.role.value,
            "preferences": {"response_language": "auto"},
            "history_enabled": True,
        }


class AnalyticsService:
    def __init__(self, repository: QueryLogRepository | None = None) -> None:
        self.repository = repository
        self._logs: list[QueryLog] = []

    def log_query(self, log: QueryLog) -> None:
        if self.repository:
            self.repository.add(log)
        else:
            self._logs.append(log)

    def dashboard(self, auth: AuthContext) -> dict[str, Any]:
        if self.repository:
            return self.repository.dashboard(auth)
        relevant = self._logs if auth.role == UserRole.admin else [
            entry for entry in self._logs if entry.user_id == auth.user_id
        ]
        from collections import Counter

        queries_by_source = Counter(entry.response_source.value for entry in relevant)
        language_distribution = Counter(entry.detected_language for entry in relevant)
        heatmap = Counter(entry.timestamp.date().isoformat() for entry in relevant)
        topic_counter = Counter()
        for entry in relevant:
            for token in re.findall(r"[a-zA-Z]{4,}", entry.query_text.lower()):
                topic_counter[token] += 1

        admin_metrics = None
        if auth.role == UserRole.admin:
            admin_metrics = {
                "total_active_users": len({entry.user_id for entry in self._logs}),
                "revenue_metrics": {"mrr": 0, "arr": 0},
                "error_rates": {"application": 0},
                "fallback_rates": {"web_search": queries_by_source.get("web_search", 0)},
            }

        return {
            "scope": "all_users" if auth.role == UserRole.admin else "current_user",
            "total_queries_this_month": len(relevant),
            "queries_by_source": dict(queries_by_source),
            "average_latency_ms_last_30_days": (
                sum(entry.latency_ms for entry in relevant) / len(relevant)
                if relevant
                else 0
            ),
            "most_searched_topics": [term for term, _ in topic_counter.most_common(10)],
            "language_distribution": dict(language_distribution),
            "daily_active_usage_heatmap": dict(heatmap),
            "token_consumption_vs_plan_limit": {
                "used": sum(entry.tokens_used for entry in relevant),
                "limit": 100000 if auth.role == UserRole.admin else 10000,
            },
            "admin_metrics": admin_metrics,
        }


class StorageService:
    def __init__(
        self,
        vector_store: VectorStoreService,
        document_service: DocumentService,
        repository: ChunkRepository | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.document_service = document_service
        self.repository = repository

    def store_document(
        self,
        filename: str,
        content: str,
        metadata: dict[str, Any],
        content_encoding: str | None = None,
    ) -> dict[str, Any]:
        prepared_content, extraction_meta = self.document_service.prepare_content(
            filename,
            content,
            content_encoding=content_encoding,
        )
        chunks = self.document_service.chunk(filename, prepared_content)
        logger.info(
            "Document ingested",
            extra={
                "filename": filename,
                "text_length": extraction_meta.get("text_length", len(prepared_content)),
                "chunks": len(chunks),
                "parser": extraction_meta.get("parser"),
                "page_count": extraction_meta.get("page_count"),
            },
        )
        if not chunks:
            raise ValueError("Document text was extracted, but no searchable chunks were created.")
        enriched = [
            chunk.model_copy(update={"metadata": chunk.metadata | metadata | extraction_meta})
            for chunk in chunks
        ]
        self.vector_store.add_chunks(enriched)
        if self.repository:
            self.repository.add_many(enriched)
        return {
            "chunks_stored": len(enriched),
            "extraction": extraction_meta,
            "suggested_questions": self.document_service.suggested_questions(filename, enriched),
        }

    def store_text(self, content: str, metadata: dict[str, Any]) -> int:
        pseudo_filename = metadata.get("filename", "generated-knowledge")
        return int(self.store_document(pseudo_filename, content, metadata)["chunks_stored"])

    def hydrate_vector_store(self) -> int:
        if not self.repository:
            return 0
        chunks = self.repository.list_all()
        if chunks:
            self.vector_store.add_chunks(chunks)
        return len(chunks)

    def delete_seeded_web_page(self, url: str) -> dict[str, Any]:
        if not self.repository:
            return {"url": url, "chunks_deleted": 0}
        deleted = self.repository.delete_seeded_web_page(url)
        if deleted["chunk_ids"]:
            self.vector_store.remove_chunks_by_ids(set(deleted["chunk_ids"]))
        return {
            "url": deleted["url"],
            "chunks_deleted": deleted["chunks_deleted"],
        }


def ensure_feature(auth: AuthContext, feature: Feature) -> None:
    if feature not in ROLE_FEATURES[auth.role]:
        raise PermissionError(
            f"Your current plan does not include {feature.value}. Please upgrade to access this."
        )


def semantic_cache_key(query: str, language_code: str) -> str:
    digest = hashlib.sha256(f"{language_code}:{query}".encode("utf-8")).hexdigest()
    return f"semantic:{digest}"


def decode_image_bytes(image_bytes_b64: str) -> bytes:
    return base64.b64decode(image_bytes_b64.encode("utf-8"))


def is_coding_query(query: str) -> bool:
    lowered = query.lower()
    coding_terms = {
        "api",
        "code",
        "coding",
        "debug",
        "dsa",
        "exception",
        "function",
        "implement",
        "javascript",
        "python",
        "react",
        "script",
        "stack trace",
        "traceback",
    }
    return any(term in lowered for term in coding_terms)


def is_ambiguous_query(query: str) -> bool:
    """Return True only for truly vague, context-free inputs that cannot be answered."""
    stripped = query.strip().lower()
    # Single-word filler inputs with no real information content
    ambiguous_single_words = {
        "explain",
        "help",
        "go",
        "ok",
        "hmm",
        "yes",
        "no",
        "okay",
        "sure",
        "what",
        "huh",
    }
    # Multi-word phrases that are completely context-free
    ambiguous_phrases = {
        "tell me more",
        "what about this",
        "how about this",
        "can you help",
        "explain this",
        "help me",
    }
    word_count = len(stripped.split())
    # Only flag single-word filler inputs OR known ambiguous multi-word phrases
    if word_count == 1 and stripped in ambiguous_single_words:
        return True
    if stripped in ambiguous_phrases:
        return True
    return False


def is_sensitive_query(query: str) -> bool:
    lowered = query.lower()
    sensitive_terms = {
        "medical",
        "medicine",
        "diagnosis",
        "legal",
        "lawsuit",
        "contract",
        "financial",
        "investment",
        "stock",
        "tax",
    }
    return any(term in lowered for term in sensitive_terms)


MARKDOWN_ANSWER_RULES = (
    "\nFormatting rules:"
    "\n- Write in clean GitHub-Flavored Markdown."
    "\n- Use ## section headings, short paragraphs, and bullet lists where helpful."
    "\n- Highlight key terms with **bold**."
    "\n- Put every code sample in fenced blocks with a language tag, e.g. ```python."
    "\n- Put each code statement on its own line inside the fence; never collapse code into one line."
    "\n- After runnable examples, add a line 'Output:' and then a ```output fence with sample output."
)


def format_text_response(answer: str, source_tag: str) -> str:
    """Preserve markdown for the frontend renderer; append source footer when useful."""
    clean_answer = answer.strip()
    source_label = source_tag.strip("[]")
    if source_label and source_label.lower() not in {"llm", "none", "unconfigured", ""}:
        return f"{clean_answer}\n\n---\n\n*Source: {source_label}*"
    return clean_answer


def format_voice_response(answer: str) -> str:
    spoken = re.sub(r"\s+", " ", answer.replace("#", " ").replace("*", " ")).strip()
    if not spoken.lower().startswith("here"):
        spoken = f"Here is what I found. {spoken}"
    return spoken
