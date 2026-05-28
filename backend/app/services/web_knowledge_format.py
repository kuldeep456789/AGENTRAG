from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urldefrag


def normalize_page_url(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    clean_url, _fragment = urldefrag(url.strip())
    return clean_url.rstrip("/") + "/"


def _parse_chunk_content(content: str) -> tuple[str, str, str]:
    lines = content.splitlines()
    source_url = ""
    source_host = ""
    body_start = 0

    for index, line in enumerate(lines[:6]):
        if line.startswith("Source URL:"):
            source_url = line.split(":", 1)[1].strip()
            body_start = index + 1
        elif line.startswith("Source website:"):
            source_host = line.split(":", 1)[1].strip()
            body_start = index + 1

    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1

    body = "\n".join(lines[body_start:]).strip()
    return source_url, source_host, body


def _merge_chunk_bodies(chunks: list[dict[str, Any]]) -> str:
    ordered = sorted(
        chunks,
        key=lambda item: (
            int((item.get("metadata") or {}).get("chunk_index", 0)),
            item.get("created_at") or datetime.min,
        ),
    )
    bodies: list[str] = []
    seen: set[str] = set()
    for chunk in ordered:
        _, _, body = _parse_chunk_content(str(chunk.get("content") or ""))
        normalized = body.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        bodies.append(normalized)
    return "\n\n".join(bodies)


def _looks_like_heading(line: str) -> bool:
    cleaned = line.strip()
    if not cleaned or len(cleaned) > 120:
        return False
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return False
    if cleaned.endswith((".", "!", "?")):
        return False
    if cleaned.isupper() and len(cleaned.split()) <= 12:
        return True
    if len(cleaned.split()) <= 10 and cleaned[0].isupper() and ":" not in cleaned:
        return True
    return False


def structure_page_sections(body: str) -> list[dict[str, Any]]:
    if not body.strip():
        return []

    sections: list[dict[str, Any]] = []
    blocks = re.split(r"\n{2,}", body.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) > 1 and _looks_like_heading(lines[0]):
            paragraphs = [" ".join(lines[1:])] if len(lines) > 1 else []
            if paragraphs:
                sections.append({"heading": lines[0], "paragraphs": paragraphs})
            continue
        sections.append({"heading": None, "paragraphs": ["\n".join(lines)]})

    if not sections:
        sections.append({"heading": None, "paragraphs": [body.strip()]})
    return sections


def build_page_detail(
    *,
    url: str,
    host: str,
    chunks: list[dict[str, Any]],
    last_updated: datetime | None,
) -> dict[str, Any]:
    body = _merge_chunk_bodies(chunks)
    sections = structure_page_sections(body)
    title = ""
    for section in sections:
        if section.get("heading"):
            title = str(section["heading"])
            break
    if not title:
        title = host or urlparse(url).netloc or "Synced webpage"

    excerpt = re.sub(r"\s+", " ", body).strip()[:320]
    word_count = len(body.split())
    char_count = len(body)

    return {
        "url": url,
        "host": host,
        "title": title,
        "chunks": len(chunks),
        "last_updated": last_updated,
        "excerpt": excerpt,
        "word_count": word_count,
        "char_count": char_count,
        "body": body,
        "sections": sections,
    }
