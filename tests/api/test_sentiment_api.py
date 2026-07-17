"""Sentiment API contract (brief 9.6). Requires PostgreSQL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes_sentiment import get_analyzer
from app.core.db import get_db
from app.ingestion import synthetic
from app.main import app
from app.models import Account
from app.nlp.sentiment import SentimentAnalyzer
from tests.nlp.stubs import StubBackend, UnavailableBackend

HEADERS = {"X-API-Key": "change-me"}


@pytest.fixture()
def client(db_session, api_get_db):
    synthetic.seed(db_session)
    db_session.commit()
    # Fresh session per request (like production): /summary only sees what /run
    # actually committed, so a missing commit fails the test instead of hiding.
    app.dependency_overrides[get_db] = api_get_db
    app.dependency_overrides[get_analyzer] = lambda: SentimentAnalyzer(StubBackend(), arabizi_backend=None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _ig(db) -> int:
    return db.scalar(select(Account.id).where(Account.handle == "cm_demo_ig"))


def test_analyze_requires_api_key(client):
    r = client.post("/sentiment/analyze", json={"texts": ["hello"]})
    assert r.status_code == 401


def test_analyze_returns_language_and_sentiment(client):
    r = client.post(
        "/sentiment/analyze",
        json={"texts": ["3ajbetni barcha", "Not worth the price", "منتج رائع"]},
        headers=HEADERS,
    )
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["language"] == "aeb-latn"
    assert results[0]["sentiment"] == "positive"
    assert results[1]["sentiment"] == "negative"
    assert results[2]["language"] == "ar"


def test_analyze_returns_503_when_model_unavailable(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_analyzer] = lambda: SentimentAnalyzer(UnavailableBackend(), arabizi_backend=None)
    try:
        c = TestClient(app)
        r = c.post("/sentiment/analyze", json={"texts": ["hello"]}, headers=HEADERS)
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_run_batch_then_summary(client, db_session):
    aid = _ig(db_session)
    run = client.post("/sentiment/run", params={"account_id": aid, "limit": 5000}, headers=HEADERS)
    assert run.status_code == 200
    assert run.json()["analyzed"] > 0

    summ = client.get("/sentiment/summary", params={"account_id": aid, "window": "90d"}, headers=HEADERS)
    assert summ.status_code == 200
    body = summ.json()
    assert body["overall"]["total"] > 0
    assert set(body["deltas"]) == {"net_sentiment", "negative_pct"}


def test_negative_alerts(client, db_session):
    aid = _ig(db_session)
    client.post("/sentiment/run", params={"limit": 5000}, headers=HEADERS)
    r = client.get("/sentiment/negative-alerts", params={"account_id": aid, "window": "90d"}, headers=HEADERS)
    assert r.status_code == 200
    assert "recent_negatives" in r.json()


def test_summary_unknown_account_404(client):
    r = client.get("/sentiment/summary", params={"account_id": 999999}, headers=HEADERS)
    assert r.status_code == 404
