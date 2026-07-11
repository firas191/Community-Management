"""Unified ingestion records (brief Section 7.1).

Every connector and the CSV importer produce these platform-agnostic records.
The normalizer consumes them and upserts into PostgreSQL. Keeping this contract
in one place means a new connector only has to emit these shapes.

Nullable numeric fields default to None, never 0, so a missing platform metric
stays honest all the way to the KPI layer (brief Section 8.1 guards).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class AccountRecord:
    platform: str  # canonical platform name (config.constants.PLATFORMS)
    external_id: str
    handle: str | None = None
    display_name: str | None = None
    followers_count: int | None = None
    is_competitor: bool = False


@dataclass(slots=True)
class PostRecord:
    account_external_id: str
    platform: str
    external_id: str
    published_at: datetime
    content_type: str | None = None
    text_content: str | None = None
    permalink: str | None = None
    media_count: int = 0
    is_synthetic: bool = False
    # hashtags left None here: the normalizer extracts them from text_content.
    hashtags: list[str] | None = None


@dataclass(slots=True)
class MetricSnapshotRecord:
    post_external_id: str
    account_external_id: str
    platform: str
    captured_at: datetime
    likes: int = 0
    comments_count: int = 0
    shares: int = 0
    saves: int = 0
    reach: int | None = None
    impressions: int | None = None
    video_views: int | None = None
    clicks: int | None = None


@dataclass(slots=True)
class CommentRecord:
    post_external_id: str
    account_external_id: str
    platform: str
    external_id: str | None
    text_content: str
    published_at: datetime | None = None
    like_count: int = 0
    author_external_id: str | None = None  # hashed by the normalizer, never stored raw
    is_synthetic: bool = False


@dataclass(slots=True)
class IngestionResult:
    """Per-run summary logged by the normalizer (brief Section 13 logging)."""

    source: str
    accounts_upserted: int = 0
    posts_upserted: int = 0
    snapshots_inserted: int = 0
    comments_upserted: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def note_skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1
