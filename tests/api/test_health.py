"""Health endpoint contract tests (brief Section 12).

Uses FastAPI dependency overrides so the test needs no real Postgres or Redis.
Verifies the response shape the dashboard stagiaire depends on.
"""

from __future__ import annotations

import app.api.routes_health as health_module
from app.core.db import get_db
from app.main import app


class _StubSession:
    def execute(self, *_args, **_kwargs):
        return None


def _override_db():
    yield _StubSession()


def test_liveness_ok():
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_reports_dependencies(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(health_module, "redis_ping", lambda: True)
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            r = client.get("/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert {d["name"] for d in body["dependencies"]} == {"postgres", "redis"}
    assert all(d["ok"] for d in body["dependencies"])


def test_health_degraded_when_redis_down(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(health_module, "redis_ping", lambda: False)
    app.dependency_overrides[get_db] = _override_db
    try:
        with TestClient(app) as client:
            r = client.get("/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
