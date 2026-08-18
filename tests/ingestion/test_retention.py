"""Raw event retention (brief 7.1). Cutoff maths is pure; the purge needs Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.ingestion.retention import RAW_EVENT_RETENTION_DAYS, cutoff_for, purge_raw_events
from app.models import RawEvent


def test_cutoff_is_days_before_now():
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert cutoff_for(30, now) == datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def test_cutoff_rejects_a_zero_or_negative_window():
    with pytest.raises(ValueError):
        cutoff_for(0)
    with pytest.raises(ValueError):
        cutoff_for(-5)


def test_default_retention_matches_the_brief():
    assert RAW_EVENT_RETENTION_DAYS == 30


def test_purge_deletes_only_expired_rows(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            RawEvent(source="youtube", entity_type="post", payload={"i": 1}, captured_at=now - timedelta(days=45)),
            RawEvent(source="youtube", entity_type="post", payload={"i": 2}, captured_at=now - timedelta(days=31)),
            RawEvent(source="youtube", entity_type="post", payload={"i": 3}, captured_at=now - timedelta(days=10)),
            RawEvent(source="youtube", entity_type="post", payload={"i": 4}, captured_at=now),
        ]
    )
    db_session.commit()

    result = purge_raw_events(db_session, days=30, now=now)
    db_session.commit()

    assert result["deleted"] == 2  # the 45- and 31-day-old rows
    assert result["remaining"] == 2
    assert result["retention_days"] == 30
    assert db_session.scalar(select(func.count()).select_from(RawEvent)) == 2


def test_purge_on_empty_table_is_a_no_op(db_session):
    result = purge_raw_events(db_session, days=30)
    assert result["deleted"] == 0
    assert result["oldest_remaining"] is None
