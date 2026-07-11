"""Connector interface (brief Section 7.1).

Every live source (Meta, YouTube) implements this Protocol. The CSV importer is
not a Connector; it is a one-shot parser that emits the same records. Both feed
the normalizer, so the storage path is identical.

Rules every Connector must honor (enforced by review and tests):
  - Incremental sync using the `since` cursor. Never full re-fetch.
  - Idempotent: re-running yields no duplicates (normalizer upserts guarantee it).
  - Retry with exponential backoff + jitter on 429/5xx.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.ingestion.records import (
    AccountRecord,
    CommentRecord,
    MetricSnapshotRecord,
    PostRecord,
)


@runtime_checkable
class Connector(Protocol):
    #: Stable source key stored on raw_events and sync_cursors (e.g. "youtube").
    source: str

    def fetch_accounts(self) -> list[AccountRecord]: ...

    def fetch_posts(self, account_external_id: str, since: datetime) -> list[PostRecord]: ...

    def fetch_metrics(self, post_external_ids: list[str]) -> list[MetricSnapshotRecord]: ...

    def fetch_comments(
        self, post_external_id: str, since: datetime
    ) -> list[CommentRecord]: ...
