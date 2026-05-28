from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.domain.models import AuthContext, DocumentChunk, QueryLog, UserRole
from app.infra.db import Database, DocumentChunkRecord, QueryLogRecord


class QueryLogRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, log: QueryLog) -> None:
        with self.database.session() as session:
            session.add(
                QueryLogRecord(
                    query_text=log.query_text,
                    detected_language=log.detected_language,
                    response_source=log.response_source.value,
                    tokens_used=log.tokens_used,
                    latency_ms=log.latency_ms,
                    timestamp=log.timestamp,
                    user_role=log.user_role.value,
                    session_id=log.session_id,
                    user_id=log.user_id,
                    document_uploaded=log.document_uploaded,
                    image_uploaded=log.image_uploaded,
                    voice_mode=log.voice_mode,
                    used_web_fallback=log.used_web_fallback,
                    retrieval_score=log.retrieval_score,
                    translated_to_en=log.translated_to_en,
                    translated_back=log.translated_back,
                )
            )

    def dashboard(self, auth: AuthContext) -> dict[str, Any]:
        with self.database.session() as session:
            rows = session.query(QueryLogRecord).all()

        relevant = rows if auth.role == UserRole.admin else [row for row in rows if row.user_id == auth.user_id]
        queries_by_source = Counter(row.response_source for row in relevant)
        language_distribution = Counter(row.detected_language for row in relevant)
        heatmap = Counter(row.timestamp.date().isoformat() for row in relevant)
        topic_counter = Counter()
        for row in relevant:
            for token in row.query_text.lower().split():
                cleaned = "".join(ch for ch in token if ch.isalpha())
                if len(cleaned) >= 4:
                    topic_counter[cleaned] += 1

        admin_metrics = None
        if auth.role == UserRole.admin:
            admin_metrics = {
                "total_active_users": len({row.user_id for row in rows}),
                "revenue_metrics": {"mrr": 0, "arr": 0},
                "error_rates": {"application": 0},
                "fallback_rates": {"web_search": queries_by_source.get("web_search", 0)},
            }

        return {
            "scope": "all_users" if auth.role == UserRole.admin else "current_user",
            "total_queries_this_month": len(relevant),
            "queries_by_source": dict(queries_by_source),
            "average_latency_ms_last_30_days": (
                sum(row.latency_ms for row in relevant) / len(relevant) if relevant else 0
            ),
            "most_searched_topics": [term for term, _ in topic_counter.most_common(10)],
            "language_distribution": dict(language_distribution),
            "daily_active_usage_heatmap": dict(heatmap),
            "token_consumption_vs_plan_limit": {
                "used": sum(row.tokens_used for row in relevant),
                "limit": 100000 if auth.role == UserRole.admin else 10000,
            },
            "admin_metrics": admin_metrics,
        }


class ChunkRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_many(self, chunks: list[DocumentChunk]) -> int:
        now = datetime.now(timezone.utc)
        with self.database.session() as session:
            for chunk in chunks:
                existing = (
                    session.query(DocumentChunkRecord)
                    .filter(DocumentChunkRecord.chunk_id == chunk.chunk_id)
                    .first()
                )
                if existing:
                    existing.content = chunk.content
                    existing.metadata_json = chunk.metadata
                else:
                    session.add(
                        DocumentChunkRecord(
                            chunk_id=chunk.chunk_id,
                            content=chunk.content,
                            metadata_json=chunk.metadata,
                            created_at=now,
                        )
                    )
        return len(chunks)

    def list_all(self) -> list[DocumentChunk]:
        with self.database.session() as session:
            rows = session.query(DocumentChunkRecord).all()
            return [
                DocumentChunk(
                    chunk_id=row.chunk_id,
                    content=row.content,
                    metadata=row.metadata_json or {},
                )
                for row in rows
            ]

    def list_seeded_web_pages(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = (
                session.query(DocumentChunkRecord)
                .filter(DocumentChunkRecord.metadata_json["source"].as_string() == "seeded_website")
                .order_by(DocumentChunkRecord.created_at.desc())
                .all()
            )

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            metadata = row.metadata_json or {}
            url = str(metadata.get("source_url") or "").strip()
            if not url:
                continue
            host = str(metadata.get("website_host") or "")
            preview = row.content.replace("\n", " ").strip()[:220]

            current = grouped.get(url)
            if not current:
                grouped[url] = {
                    "url": url,
                    "host": host,
                    "chunks": 1,
                    "last_updated": row.created_at,
                    "preview": preview,
                }
                continue

            current["chunks"] += 1
            if row.created_at and (current["last_updated"] is None or row.created_at > current["last_updated"]):
                current["last_updated"] = row.created_at
            if not current["preview"] and preview:
                current["preview"] = preview

        entries = list(grouped.values())
        entries.sort(key=lambda item: item["last_updated"] or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
        return entries

    def get_seeded_web_page_detail(self, url: str) -> dict[str, Any] | None:
        from app.services.web_knowledge_format import build_page_detail, normalize_page_url

        candidates: list[str] = []
        normalized = normalize_page_url(url)
        if normalized:
            candidates.append(normalized)
        stripped = url.strip()
        if stripped:
            candidates.append(stripped)
            if not stripped.endswith("/"):
                candidates.append(f"{stripped}/")

        seen_urls: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen_urls:
                continue
            seen_urls.add(candidate)

            with self.database.session() as session:
                rows = (
                    session.query(DocumentChunkRecord)
                    .filter(DocumentChunkRecord.metadata_json["source"].as_string() == "seeded_website")
                    .filter(DocumentChunkRecord.metadata_json["source_url"].as_string() == candidate)
                    .order_by(DocumentChunkRecord.created_at.asc())
                    .all()
                )

            if not rows:
                continue

            metadata = rows[0].metadata_json or {}
            host = str(metadata.get("website_host") or "")
            chunks = [
                {
                    "content": row.content,
                    "metadata": row.metadata_json or {},
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            last_updated = max((row.created_at for row in rows if row.created_at), default=None)
            return build_page_detail(
                url=candidate,
                host=host,
                chunks=chunks,
                last_updated=last_updated,
            )

        return None

    def delete_seeded_web_page(self, url: str) -> dict[str, Any]:
        from app.services.web_knowledge_format import normalize_page_url

        candidates: list[str] = []
        normalized = normalize_page_url(url)
        if normalized:
            candidates.append(normalized)
        stripped = url.strip()
        if stripped:
            candidates.append(stripped)
            if not stripped.endswith("/"):
                candidates.append(f"{stripped}/")

        deleted_ids: list[str] = []
        canonical_url = normalized or stripped
        seen_urls: set[str] = set()

        with self.database.session() as session:
            for candidate in candidates:
                if not candidate or candidate in seen_urls:
                    continue
                seen_urls.add(candidate)

                rows = (
                    session.query(DocumentChunkRecord)
                    .filter(DocumentChunkRecord.metadata_json["source"].as_string() == "seeded_website")
                    .filter(DocumentChunkRecord.metadata_json["source_url"].as_string() == candidate)
                    .all()
                )
                if not rows:
                    continue

                canonical_url = candidate
                for row in rows:
                    deleted_ids.append(row.chunk_id)
                    session.delete(row)

        return {
            "url": canonical_url,
            "chunks_deleted": len(deleted_ids),
            "chunk_ids": deleted_ids,
        }
