"""Recommendation and generated-content models (Weeks 5, 6)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # best_time,content_type,hashtags,format
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text)  # high,medium,low
    # Sample sizes and lift values: every recommendation is explainable (brief 6.2).
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GeneratedContent(Base):
    __tablename__ = "generated_contents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)  # brief given to the LLM
    variants: Mapped[dict] = mapped_column(JSONB, nullable=False)  # N generated options
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
