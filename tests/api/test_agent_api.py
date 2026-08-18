"""Agent API contract tests (Week 7). Requires PostgreSQL.

Runs the real graph against the real tools and a real seeded database, with only
the LLM faked: the stub asks for a KPI tool on the first turn and writes an answer
on the second. That exercises the whole loop (tool dispatch, trace, persistence)
end to end without a network call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.routes_llm import get_gateway
from app.core.db import get_db
from app.ingestion import synthetic
from app.llm.gateway import Attempt, LLMResult, ToolCall
from app.main import app
from app.models import Account, AgentRun

# The route compiles a LangGraph state machine, so without the agent extra it can
# only answer 503. Skip rather than fail, the same contract the real-model
# sentiment smoke test uses. CI installs `.[dev,agent]`, so these do run there.
# Safe to check after the imports above: graph.py imports langgraph lazily, inside
# build_graph, so importing the app never requires it.
pytest.importorskip(
    "langgraph", reason="agent tests need the agent extra: pip install -e '.[agent]'"
)

HEADERS = {"X-API-Key": "change-me"}


class _ToolThenAnswerGateway:
    """Turn 1: call get_kpi_overview. Turn 2: answer from the tool result."""

    def __init__(self):
        self.turn = 0

    def complete(self, messages, *, purpose="general", max_tokens=800, temperature=0.7, use_cache=True, tools=None):
        self.turn += 1
        attempts = [Attempt("groq", "groq/a", "ok", 10, 5, 7)]
        if self.turn == 1:
            return LLMResult(
                text="", provider="groq", model="groq/a", latency_ms=10, fallback_depth=0,
                attempts=attempts,
                tool_calls=[ToolCall(id="c1", name="get_kpi_overview", arguments='{"window": "90d"}')],
            )
        return LLMResult(
            text="Engagement held steady over the window.", provider="groq", model="groq/a",
            latency_ms=12, fallback_depth=0, attempts=attempts,
        )


@pytest.fixture()
def client(db_session, api_get_db):
    synthetic.seed(db_session)
    db_session.commit()
    app.dependency_overrides[get_db] = api_get_db
    app.dependency_overrides[get_gateway] = lambda: _ToolThenAnswerGateway()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _aid(db_session, handle: str = "cm_demo_ig") -> int:
    return db_session.scalar(select(Account.id).where(Account.handle == handle))


def test_requires_api_key(client):
    assert client.post("/agent/ask", json={"question": "how are we doing?"}).status_code == 401


def test_ask_uses_a_tool_and_persists_the_run(client, db_session):
    before = db_session.scalar(select(func.count()).select_from(AgentRun))
    aid = _aid(db_session)

    r = client.post(
        "/agent/ask",
        json={"question": "How did engagement do over the last 90 days?", "account_id": aid},
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Engagement held steady over the window."
    assert body["tool_call_count"] == 1
    assert body["trace"][0]["tool"] == "get_kpi_overview"
    assert body["trace"][0]["ok"] is True  # the real KPI tool ran against real rows
    assert body["conversation_id"]

    # the route commits, so a separate session sees the run
    assert db_session.scalar(select(func.count()).select_from(AgentRun)) == before + 1


def test_runs_endpoint_lists_traces(client, db_session):
    aid = _aid(db_session)
    client.post("/agent/ask", json={"question": "how are we doing?", "account_id": aid}, headers=HEADERS)
    r = client.get("/agent/runs", params={"account_id": aid}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["runs"][0]["question"]
    assert body["runs"][0]["trace"][0]["tool"] == "get_kpi_overview"


def test_unknown_account_404(client):
    r = client.post("/agent/ask", json={"question": "hi", "account_id": 999999}, headers=HEADERS)
    assert r.status_code == 404
