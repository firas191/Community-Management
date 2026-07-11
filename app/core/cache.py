"""Redis helpers: client singleton, key builders, and typed get/set.

Redis serves three roles (brief Section 6.3): KPI and LLM response cache,
free-tier rate-limit token buckets, and the Celery broker/backend. This module
covers the cache and key-naming concerns. Celery configures its own connection.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

import redis

from app.config import settings


@lru_cache
def get_redis() -> redis.Redis:
    """Cached Redis client. decode_responses gives str in/out."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


# --- Key builders (brief Section 6.3). Centralized so patterns stay consistent. ---
def kpi_key(account_id: int | str, window: str, granularity: str) -> str:
    return f"cache:kpi:{account_id}:{window}:{granularity}"


def llm_key(prompt: str, model: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"p": prompt, "m": model, "params": params}, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"cache:llm:{digest}"


def ratelimit_key(provider: str) -> str:
    return f"ratelimit:{provider}"


# --- Typed JSON cache helpers ---
def cache_get_json(key: str) -> Any | None:
    client = get_redis()
    raw = client.get(key)
    return json.loads(raw) if raw is not None else None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    client = get_redis()
    client.set(key, json.dumps(value, default=str), ex=ttl_seconds)


def ping() -> bool:
    """Liveness check used by /health. Returns False instead of raising."""
    try:
        return bool(get_redis().ping())
    except redis.RedisError:
        return False
