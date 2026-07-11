"""Comment analysis and topic models (NLP outputs, Week 3+)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CommentAnalysis(Base):
    __tablename__ = "comment_analyses"

    comment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comments.id"), primary_key=True
    )
    language: Mapped[str | None] = mapped_column(Text)  # fr,en,ar,aeb-latn,other
    sentiment: Mapped[str] = mapped_column(Text, nullable=False)  # positive,neutral,negative
    sentiment_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Traceability: which model produced this label (brief 6.2 reproducibility).
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(Integer)
    is_toxic: Mapped[bool | None] = mapped_column(Boolean)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    label: Mapped[str] = mapped_column(Text, nullable=False)  # LLM-generated
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    comment_count: Mapped[int | None] = mapped_column(Integer)
    avg_sentiment: Mapped[float | None] = mapped_column(Float)  # -1..1 rollup
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
