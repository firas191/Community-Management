"""Topic modeling response schemas (Week 8)."""

from __future__ import annotations

from pydantic import BaseModel


class TopicOut(BaseModel):
    topic_id: int | None = None
    label: str
    keywords: list[str] = []
    comment_count: int | None = None
    avg_sentiment: float | None = None
    n_labeled: int | None = None


class DiscoverResponse(BaseModel):
    account_id: int
    window: str
    generated_at: str
    n_comments: int
    n_topics: int
    topics: list[TopicOut]
    reason: str | None = None
    model_name: str | None = None
    model_version: str | None = None


class StoredTopic(BaseModel):
    id: int
    label: str
    keywords: list[str] = []
    comment_count: int | None = None
    avg_sentiment: float | None = None
    window_start: str | None = None
    window_end: str | None = None


class TopicsResponse(BaseModel):
    account_id: int
    count: int
    topics: list[StoredTopic]
