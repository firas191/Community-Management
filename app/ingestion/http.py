"""Resilient JSON HTTP client for connectors (brief Section 7.1).

One small helper: GET a URL and return parsed JSON, retrying on 429 and 5xx with
exponential backoff plus jitter, and respecting a Retry-After header when present.
Connectors receive this as an injectable callable, so tests pass a stub that
returns canned API payloads without any network.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger("ingestion.http")

_RETRY_STATUS = {429, 500, 502, 503, 504}

# The signature connectors depend on. Swap it in tests.
GetJson = Callable[..., dict[str, Any]]


class HTTPError(RuntimeError):
    """Non-retryable HTTP failure, or retries exhausted."""


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_retries: int = 4,
    timeout: float = 20.0,
    _sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """GET `url` and return JSON. Retries 429/5xx with backoff, then raises HTTPError."""
    last_detail = ""
    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:  # network/timeout: retry a few times
            last_detail = f"transport error: {exc}"
            if attempt < max_retries:
                _sleep(_backoff(attempt, None))
                continue
            raise HTTPError(last_detail) from exc

        if resp.status_code == 200:
            return resp.json()

        last_detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
        if resp.status_code in _RETRY_STATUS and attempt < max_retries:
            log.warning("http_retry", url=url, status=resp.status_code, attempt=attempt)
            _sleep(_backoff(attempt, resp.headers.get("Retry-After")))
            continue
        raise HTTPError(last_detail)

    raise HTTPError(last_detail or "retries exhausted")


def _backoff(attempt: int, retry_after: str | None) -> float:
    """Exponential backoff with jitter, capped at 30s. Honor Retry-After if given."""
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return min(2.0**attempt + random.random(), 30.0)
