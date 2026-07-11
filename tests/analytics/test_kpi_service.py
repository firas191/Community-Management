"""KPI service integration tests (brief Sections 8, 13).

Requires PostgreSQL. Seeds the synthetic fixtures, then exercises the service
against real rows: latest-snapshot join, follower resolution, aggregation.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.analytics import service
from app.analytics.service import AccountNotFoundError
from app.ingestion import synthetic
from app.models import Account


@pytest.fixture()
def seeded(db_session):
    synthetic.seed(db_session)
    db_session.commit()
    return db_session


def _account_id(db, handle: str) -> int:
    return db.scalar(select(Account.id).where(Account.handle == handle))


def test_overview_has_real_numbers_for_instagram(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    ov = service.overview(seeded, aid, "90d")
    assert ov["n_posts"] > 0
    # Instagram exposes reach, so the primary basis is ERR and the average resolves.
    assert ov["engagement_rate_basis"] == "err"
    assert ov["avg_engagement_rate"]["value"] is not None
    assert ov["median_engagement_rate"]["value"] is not None
    assert ov["total_engagement"] > 0
    # No follower snapshots are seeded, so followers fall back to the account value.
    assert ov["followers"]["basis"] == "account_latest"
    assert ov["followers"]["value"] == 8200
    assert ov["best_post"]["engagement_rate"] >= ov["worst_post"]["engagement_rate"]


def test_overview_youtube_falls_back_to_followers_basis(seeded):
    aid = _account_id(seeded, "cm_demo_yt")
    ov = service.overview(seeded, aid, "90d")
    # YouTube hides reach in the fixtures, so the engine uses ERF, not a null.
    assert ov["engagement_rate_basis"] == "erf"
    assert ov["avg_engagement_rate"]["value"] is not None


def test_overview_deltas_present(seeded):
    aid = _account_id(seeded, "cm_demo_fb")
    ov = service.overview(seeded, aid, "30d")
    assert set(ov["deltas"]) == {"total_engagement_pct", "avg_engagement_rate_pct", "n_posts_pct"}


def test_timeseries_is_chart_ready_and_gap_filled(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    ts = service.timeseries(seeded, aid, metric="err", granularity="day")
    assert ts["metric"] == "err"
    assert len(ts["labels"]) == len(ts["series"][0]["data"])
    assert len(ts["labels"]) > 0


def test_timeseries_rolling_adds_second_series(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    ts = service.timeseries(seeded, aid, metric="engagement", granularity="day", rolling=7)
    assert len(ts["series"]) == 2
    assert ts["series"][1]["name"].endswith("_rolling_7")


def test_by_platform_lists_platforms_with_zscore_field(seeded):
    out = service.by_platform(seeded, "30d")
    assert len(out["platforms"]) >= 1
    for row in out["platforms"]:
        assert "zscore_vs_90d_baseline" in row
        assert row["avg_engagement_rate"]["value"] is not None


def test_top_posts_sorted_descending(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    out = service.top_posts(seeded, aid, metric="err", limit=5)
    scores = [p["score"] for p in out["posts"]]
    assert scores == sorted(scores, reverse=True)
    assert out["count"] <= 5


def test_include_synthetic_false_excludes_seeded_rows(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    out = service.top_posts(seeded, aid, metric="err", limit=50, include_synthetic=False)
    assert out["count"] == 0  # every seeded row is flagged synthetic


def test_unknown_account_raises(seeded):
    with pytest.raises(AccountNotFoundError):
        service.overview(seeded, 999999, "30d")


def test_bad_window_raises(seeded):
    aid = _account_id(seeded, "cm_demo_ig")
    with pytest.raises(service.KPIQueryError):
        service.overview(seeded, aid, "banana")


def test_follower_resolver_fallback_basis(seeded):
    aid = _account_id(seeded, "cm_demo_fb")
    acc = seeded.get(Account, aid)
    value, basis = service.resolve_followers(seeded, acc)
    assert value == 15400 and basis == "account_latest"
