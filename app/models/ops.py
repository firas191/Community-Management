"""Operational models: LLM observability, raw event archive, sync cursors, agent runs.

llm_calls is in the brief DDL. raw_events (Section 7.1, 30-day archive),
sync_cursors (Section 7.1, per-account incremental cursors), and agent_runs
(Section 11.6, tool traces) are described in prose and modeled here so the
ingestion and agent layers have their storage ready in roadmap order.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LLMCall(Base):
    """Observability of the free-tier gateway (brief 6.2, 11.3)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)
    fallback_depth: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RawEvent(Base):
    """Raw API payload archive for debuggability and reprocessing (brief 7.1).

    Retention 30 days, enforced by a scheduled purge job (Week 3).
    """

    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # meta,youtube,csv
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # post,comment,metric
    external_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncCursor(Base):
    """Per-account, per-source incremental cursor (brief 7.1: never full re-fetch)."""

    __tablename__ = "sync_cursors"
    __table_args__ = (UniqueConstraint("source", "account_external_id", "entity_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    account_external_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # posts,comments,metrics
    cursor_value: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    """Analyst agent run + tool trace for explainability (brief 11.6)."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(BigInteger)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    reasoning_trace: Mapped[dict | None] = mapped_column(JSONB)  # tool calls + results
    tool_call_count: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
