"""LLM API contract tests (Week 6). Requires PostgreSQL.

Boots the real app with a stub gateway injected (no network), seeds fixtures, and
checks the HTTP contract plus that generation persists to generated_contents and
one llm_calls row per attempt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes_llm import get_gateway
from app.core.db import get_db
from app.ingestion import synthetic
from app.llm.gateway import Attempt, LLMResult
from app.main import app
from app.models import Account, GeneratedContent, LLMCall

HEADERS = {"X-API-Key": "change-me"}


class _StubGateway:
    """Returns a canned JSON array and one ok attempt, so nothing hits the network."""

    def complete(self, messages, *, purpose="general", max_tokens=800, temperature=0.7, use_cache=True):
        return LLMResult(
            text='["Option one", "Option two", "Option three"]',
            provider="groq", model="groq/llama-3.3-70b-versatile", latency_ms=15, fallback_depth=0,
            prompt_tokens=11, completion_tokens=22,
            attempts=[Attempt("groq", "groq/llama-3.3-70b-versatile", "ok", 15, 11, 22)],
        )


@pytest.fixture()
def client(db_session, api_get_db):
    synthetic.seed(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = api_get_db
    app.dependency_overrides[get_gateway] = lambda: _StubGateway()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _aid(db_session, handle: str = "cm_demo_ig") -> int:
    return db_session.scalar(select(Account.id).where(Account.handle == handle))


def test_requires_api_key(client):
    r = client.post("/llm/generate", json={"brief": "hi"})
    assert r.status_code == 401


def test_providers_endpoint(client):
    r = client.get("/llm/providers", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"configured", "chain", "ready"}
    assert set(body["configured"]) == {"groq", "gemini", "openrouter", "nvidia"}


def test_generate_persists_content_and_calls(client, db_session):
    gc_before = db_session.scalar(select(func.count()).select_from(GeneratedContent))
    call_before = db_session.scalar(select(func.count()).select_from(LLMCall))

    r = client.post(
        "/llm/generate",
        params={},
        json={"brief": "Announce our weekend promo", "account_id": _aid(db_session), "n": 3},
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["variants"] == ["Option one", "Option two", "Option three"]
    assert body["provider"] == "groq"

    # persisted: one generated_contents row and one llm_calls row (one attempt).
    assert db_session.scalar(select(func.count()).select_from(GeneratedContent)) == gc_before + 1
    assert db_session.scalar(select(func.count()).select_from(LLMCall)) == call_before + 1


def test_generate_unknown_account_404(client):
    r = client.post("/llm/generate", json={"brief": "hi", "account_id": 999999}, headers=HEADERS)
    assert r.status_code == 404
