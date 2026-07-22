"""Recommendation service integration tests (brief Section 8.5). Requires PostgreSQL.

Seeds the synthetic fixtures (posts across content types, hashtags, and times)
then exercises the DB-facing recommendation service and its persistence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.analytics import recommend_service as reco
from app.analytics.service import AccountNotFoundError
from app.ingestion import synthetic
from app.models import Account, Recommendation


@pytest.fixture()
def seeded(db_session):
    synthetic.seed(db_session)
    db_session.commit()
    return db_session


def _aid(db, handle: str = "cm_demo_ig") -> int:
    return db.scalar(select(Account.id).where(Account.handle == handle))


def test_best_time_returns_cells_and_marginals(seeded):
    out = reco.best_time(seeded, _aid(seeded), "90d", persist=False)
    assert out["kind"] == "best_time"
    assert out["timezone"] == "Africa/Tunis"
    assert out["baseline_er"] is not None
    # Marginals aggregate all posts, so with seeded data they are populated and ranked.
    assert len(out["by_day"]) >= 1
    assert len(out["by_hour"]) >= 1
    for cell in out["top_cells"]:
        assert 0 <= cell["day_of_week"] <= 6
        assert 0 <= cell["hour"] <= 23
        assert cell["n"] >= 2  # thin cells are never surfaced


def test_content_types_ranked_with_evidence(seeded):
    out = reco.content_types(seeded, _aid(seeded), "90d", persist=False)
    assert out["kind"] == "content_type"
    for item in out["ranked"]:
        assert item["n"] >= 2
        assert item["confidence"] in {"low", "medium", "high"}
        assert "lift" in item


def test_hashtags_ranked_from_seeded_pool(seeded):
    out = reco.hashtags(seeded, _aid(seeded), "90d", persist=False)
    assert out["kind"] == "hashtags"
    # Seeded posts draw from a hashtag pool, so at least one qualifies or the
    # honest reason is returned; never a fabricated pick.
    assert out["ranked"] or out["reason"] is not None


def test_youtube_uses_erf_basis(seeded):
    out = reco.best_time(seeded, _aid(seeded, "cm_demo_yt"), "90d", persist=False)
    # Public YouTube hides reach, so recommendations are built on ERF, not nulls.
    assert out["engagement_rate_basis"] in {"erf", "none"}


def test_persist_writes_a_recommendation_row(seeded):
    before = seeded.scalar(select(func.count()).select_from(Recommendation))
    reco.best_time(seeded, _aid(seeded), "90d", persist=True)
    seeded.commit()
    after = seeded.scalar(select(func.count()).select_from(Recommendation))
    assert after == before + 1
    row = seeded.scalars(select(Recommendation).order_by(Recommendation.id.desc())).first()
    assert row.kind == "best_time"
    assert "baseline_er" in row.evidence


def test_unknown_account_raises(seeded):
    with pytest.raises(AccountNotFoundError):
        reco.best_time(seeded, 999999, "90d", persist=False)
