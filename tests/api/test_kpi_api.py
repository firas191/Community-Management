"""KPI API contract tests (brief Section 12). Requires PostgreSQL.

Boots the real app with the test session injected, seeds fixtures, and asserts
the HTTP contract: auth, status codes, and response shape.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import get_db
from app.ingestion import synthetic
from app.main import app
from app.models import Account

HEADERS = {"X-API-Key": "change-me"}


@pytest.fixture()
def client(db_session, api_get_db):
    synthetic.seed(db_session)
    db_session.commit()
    # Each request gets its own session, bound to the test DB, like production.
    app.dependency_overrides[get_db] = api_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _aid(db_session, handle: str = "cm_demo_ig") -> int:
    return db_session.scalar(select(Account.id).where(Account.handle == handle))


def test_requires_api_key(client, db_session):
    r = client.get("/kpi/overview", params={"account_id": _aid(db_session)})
    assert r.status_code == 401


def test_overview_contract(client, db_session):
    aid = _aid(db_session)
    r = client.get("/kpi/overview", params={"account_id": aid, "window": "90d"}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == aid
    assert body["n_posts"] > 0
    assert body["avg_engagement_rate"]["value"] is not None
    assert body["followers"]["basis"] == "account_latest"
    assert set(body["deltas"]) == {"total_engagement_pct", "avg_engagement_rate_pct", "n_posts_pct"}


def test_timeseries_contract(client, db_session):
    aid = _aid(db_session)
    r = client.get(
        "/kpi/timeseries",
        params={"account_id": aid, "metric": "err", "granularity": "day", "rolling": 7},
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["labels"]) == len(body["series"][0]["data"])
    assert len(body["series"]) == 2  # base + rolling


def test_by_platform_contract(client):
    r = client.get("/kpi/by-platform", params={"window": "90d"}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "note" in body
    assert len(body["platforms"]) >= 1


def test_top_posts_sorted(client, db_session):
    aid = _aid(db_session)
    r = client.get("/kpi/top-posts", params={"account_id": aid, "metric": "err", "limit": 5}, headers=HEADERS)
    assert r.status_code == 200
    posts = r.json()["posts"]
    scores = [p["score"] for p in posts]
    assert scores == sorted(scores, reverse=True)
    assert len(posts) <= 5
    if posts:
        assert len(posts[0]["kpis"]) == 10  # full per-post KPI breakdown


def test_unknown_account_is_404(client):
    r = client.get("/kpi/overview", params={"account_id": 999999}, headers=HEADERS)
    assert r.status_code == 404


def test_bad_window_is_400(client, db_session):
    aid = _aid(db_session)
    r = client.get("/kpi/overview", params={"account_id": aid, "window": "banana"}, headers=HEADERS)
    assert r.status_code == 400


def test_bad_metric_is_400(client, db_session):
    aid = _aid(db_session)
    r = client.get("/kpi/timeseries", params={"account_id": aid, "metric": "nope"}, headers=HEADERS)
    assert r.status_code == 400
