"""Sentiment service integration (brief 9.5, 11.5). Requires PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.analytics.service import AccountNotFoundError
from app.ingestion import synthetic
from app.models import Account, Comment, CommentAnalysis
from app.nlp import service
from app.nlp.sentiment import SentimentAnalyzer
from tests.nlp.stubs import StubBackend


@pytest.fixture()
def seeded(db_session):
    synthetic.seed(db_session)
    db_session.commit()
    return db_session


def _analyzer() -> SentimentAnalyzer:
    return SentimentAnalyzer(StubBackend(), arabizi_backend=None)


def _ig(db) -> int:
    return db.scalar(select(Account.id).where(Account.handle == "cm_demo_ig"))


def test_analyze_new_comments_stores_and_is_idempotent(seeded):
    total_comments = seeded.scalar(select(func.count()).select_from(Comment))
    first = service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    seeded.commit()
    assert first["analyzed"] == total_comments
    stored = seeded.scalar(select(func.count()).select_from(CommentAnalysis))
    assert stored == total_comments
    # Re-run: nothing left unanalyzed.
    second = service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    assert second["analyzed"] == 0


def test_every_analysis_carries_model_traceability(seeded):
    service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    seeded.commit()
    row = seeded.execute(select(CommentAnalysis).limit(1)).scalar_one()
    assert row.model_name == "stub-model"
    assert row.model_version == "stub-1.0"
    assert row.sentiment in ("positive", "neutral", "negative")
    assert row.language is not None


def test_summary_distribution(seeded):
    service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    seeded.commit()
    summ = service.sentiment_summary(seeded, _ig(seeded), "90d")
    overall = summ["overall"]
    assert overall["total"] > 0
    assert sum(overall["counts"].values()) == overall["total"]
    assert -1.0 <= overall["net_sentiment"] <= 1.0
    assert set(summ["deltas"]) == {"net_sentiment", "negative_pct"}
    assert "labels" in summ["trend"]


def test_summary_has_language_breakdown(seeded):
    service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    seeded.commit()
    summ = service.sentiment_summary(seeded, _ig(seeded), "90d")
    # The seeded comments span fr/en/ar/aeb-latn, so several registers appear.
    assert len(summ["by_language"]) >= 2


def test_negative_alerts_structure(seeded):
    service.analyze_new_comments(seeded, _analyzer(), limit=10000)
    seeded.commit()
    alerts = service.negative_alerts(seeded, _ig(seeded), "90d")
    assert "flagged_days" in alerts
    assert isinstance(alerts["recent_negatives"], list)
    for n in alerts["recent_negatives"]:
        assert set(n) >= {"text", "score", "published_at"}


def test_unknown_account_raises(seeded):
    with pytest.raises(AccountNotFoundError):
        service.sentiment_summary(seeded, 999999, "30d")
