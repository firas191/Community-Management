"""Data-quality guard tests (brief Sections 7.1, 13). No database required."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingestion import quality
from app.ingestion.records import MetricSnapshotRecord, PostRecord

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def _post(published_at):
    return PostRecord(
        account_external_id="a1",
        platform="facebook",
        external_id="p1",
        published_at=published_at,
    )


def _metric(**kw):
    base = dict(
        post_external_id="p1",
        account_external_id="a1",
        platform="facebook",
        captured_at=NOW,
    )
    base.update(kw)
    return MetricSnapshotRecord(**base)


def test_future_post_rejected():
    v = quality.check_post(_post(NOW + timedelta(hours=1)), now=NOW)
    assert not v.ok
    assert v.reject_reason == "future_timestamp"


def test_recent_post_accepted():
    v = quality.check_post(_post(NOW - timedelta(days=1)), now=NOW)
    assert v.ok


def test_small_clock_skew_tolerated():
    # Within the 5-minute tolerance the row is accepted.
    v = quality.check_post(_post(NOW + timedelta(minutes=3)), now=NOW)
    assert v.ok


def test_negative_count_rejected():
    v = quality.check_metric(_metric(likes=-5), now=NOW)
    assert not v.ok
    assert v.reject_reason == "negative_likes"


def test_reach_less_than_engagement_flagged_not_rejected():
    # Engagement 100, reach 40: kept but flagged (brief 8.1).
    v = quality.check_metric(_metric(likes=100, reach=40), now=NOW)
    assert v.ok
    assert "reach_lt_engagement" in v.flags


def test_null_reach_no_flag():
    v = quality.check_metric(_metric(likes=100, reach=None), now=NOW)
    assert v.ok
    assert v.flags == []
