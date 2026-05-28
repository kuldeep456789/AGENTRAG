from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


class QueryLogRecord(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[str] = mapped_column(String(32), nullable=False)
    response_source: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_role: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_uploaded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voice_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_web_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retrieval_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    translated_to_en: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    translated_back: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DocumentChunkRecord(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Database:
    def __init__(self, settings: Settings) -> None:
        database_url = settings.postgres_url
        if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
