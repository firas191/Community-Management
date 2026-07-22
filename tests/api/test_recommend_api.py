"""Recommendation API contract tests (brief Section 12). Requires PostgreSQL.

Boots the real app with the test session injected, seeds fixtures, and asserts
the HTTP contract: auth, status codes, response shape, and that a fresh request
sees the persisted recommendation (a real commit happened).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import get_db
from app.ingestion import synthetic
from app.main import app
from app.models import Account, Recommendation

HEADERS = {"X-API-Key": "change-me"}


@pytest.fixture()
def client(db_session, api_get_db):
    synthetic.seed(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = api_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _aid(db_session, handle: str = "cm_demo_ig") -> int:
    return db_session.scalar(select(Account.id).where(Account.handle == handle))


def test_requires_api_key(client, db_session):
    r = client.post("/recommendations/best-time", params={"account_id": _aid(db_session)})
    assert r.status_code == 401


def test_best_time_contract_and_persists(client, db_session):
    aid = _aid(db_session)
    before = db_session.scalar(select(func.count()).select_from(Recommendation))
    r = client.post("/recommendations/best-time", params={"account_id": aid, "window": "90d"}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == aid
    assert body["kind"] == "best_time"
    assert body["timezone"] == "Africa/Tunis"
    assert "top_cells" in body and "by_day" in body and "by_hour" in body
    # The route commits, so a fresh session sees the new row.
    after = db_session.scalar(select(func.count()).select_from(Recommendation))
    assert after == before + 1


def test_content_types_contract(client, db_session):
    r = client.post("/recommendations/content-types", params={"account_id": _aid(db_session)}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["kind"] == "content_type"


def test_hashtags_contract(client, db_session):
    r = client.post("/recommendations/hashtags", params={"account_id": _aid(db_session)}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["kind"] == "hashtags"


def test_all_contract(client, db_session):
    r = client.post("/recommendations/all", params={"account_id": _aid(db_session)}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(["best_time", "content_type", "hashtags"]).issubset(body)


def test_unknown_account_404(client, db_session):
    r = client.post("/recommendations/best-time", params={"account_id": 999999}, headers=HEADERS)
    assert r.status_code == 404
