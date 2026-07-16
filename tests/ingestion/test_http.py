"""Resilient HTTP client: retry on 429/5xx, fail on 4xx. No network."""

from __future__ import annotations

import pytest

from app.ingestion import http


class _Resp:
    def __init__(self, status_code, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._data


def test_retries_5xx_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Resp(503, text="busy")
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(http.httpx, "get", fake_get)
    out = http.get_json("http://x", _sleep=lambda s: None)
    assert out == {"ok": True}
    assert calls["n"] == 3


def test_4xx_raises_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return _Resp(400, text="bad request")

    monkeypatch.setattr(http.httpx, "get", fake_get)
    with pytest.raises(http.HTTPError):
        http.get_json("http://x", _sleep=lambda s: None)
    assert calls["n"] == 1  # not retried


def test_retries_exhausted_raises(monkeypatch):
    monkeypatch.setattr(http.httpx, "get", lambda *a, **k: _Resp(500, text="err"))
    with pytest.raises(http.HTTPError):
        http.get_json("http://x", max_retries=2, _sleep=lambda s: None)


def test_backoff_honors_retry_after():
    assert http._backoff(0, "5") == 5.0
    assert http._backoff(9, None) <= 30.0  # capped
