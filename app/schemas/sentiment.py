"""Sentiment API schemas (brief Section 9.6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=200)


class AnalyzeItem(BaseModel):
    text: str
    language: str
    language_confidence: float
    language_method: str
    sentiment: str
    score: float
    model_name: str
    model_version: str
    needs_arabizi_specialist: bool
    emoji_polarity: float


class AnalyzeResponse(BaseModel):
    results: list[AnalyzeItem]


class AnalyzeRunResponse(BaseModel):
    analyzed: int
    skipped: int


class Distribution(BaseModel):
    total: int
    counts: dict[str, int]
    pct: dict[str, float | None]
    net_sentiment: float | None = None


class SummaryResponse(BaseModel):
    account_id: int
    window: str
    generated_at: str
    overall: Distribution
    by_language: dict[str, Distribution]
    trend: dict
    deltas: dict


class FlaggedDay(BaseModel):
    date: str
    negative_share: float
    n_comments: int


class NegativeComment(BaseModel):
    text: str
    language: str | None = None
    score: float
    published_at: str


class NegativeAlertsResponse(BaseModel):
    account_id: int
    window: str
    generated_at: str
    flagged_days: list[FlaggedDay]
    recent_negatives: list[NegativeComment]
