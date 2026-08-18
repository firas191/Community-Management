"""Raw event retention (brief Section 7.1: 30-day archive).

`raw_events` stores every API payload so an ingestion bug can be diagnosed and
reprocessed. That table grows without bound, so the brief caps it at 30 days. This
module is the purge: one function, a cutoff, a delete, and an honest count.

Two deliberate choices. The retention window is a parameter with a documented
default rather than a hardcoded 30, so it can be tuned per deployment without a
code change. And the purge reports what it deleted (and the oldest row that
remains), so a scheduled job leaves evidence it ran instead of being invisible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import RawEvent

log = get_logger("ingestion.retention")

RAW_EVENT_RETENTION_DAYS = 30


def cutoff_for(days: int, now: datetime | None = None) -> datetime:
    """The timestamp before which rows are expired. Pure, so it is unit-testable."""
    if days < 1:
        raise ValueError(f"Retention must be at least 1 day, got {days}.")
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def purge_raw_events(
    db: Session,
    *,
    days: int = RAW_EVENT_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict:
    """Delete raw_events older than the retention window. Caller owns the commit."""
    cutoff = cutoff_for(days, now)
    before = db.scalar(select(func.count()).select_from(RawEvent)) or 0
    deleted = db.execute(delete(RawEvent).where(RawEvent.captured_at < cutoff)).rowcount or 0
    remaining = before - deleted
    oldest = db.scalar(select(func.min(RawEvent.captured_at)))

    log.info("raw_events_purged", deleted=deleted, remaining=remaining, retention_days=days)
    return {
        "retention_days": days,
        "cutoff": cutoff.isoformat(),
        "deleted": int(deleted),
        "remaining": int(remaining),
        "oldest_remaining": oldest.isoformat() if oldest else None,
    }
