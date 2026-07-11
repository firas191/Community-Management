"""API-key auth (brief Sections 12, 13).

Clients send `X-API-Key`. The dependency compares it to the configured key in
constant time. Health liveness is intentionally left unauthenticated so
orchestrators can probe it; everything else requires the key.
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def _constant_time_eq(a: str, b: str) -> bool:
    # Compare digests so timing does not leak key length or content.
    ha = hashlib.sha256(a.encode("utf-8")).digest()
    hb = hashlib.sha256(b.encode("utf-8")).digest()
    return hmac.compare_digest(ha, hb)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency. Raises 401 (problem+json) if the key is missing or wrong."""
    if x_api_key is None or not _constant_time_eq(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def author_hash(external_author_id: str) -> str:
    """SHA-256 of a platform author id. Privacy by construction (brief Section 6.2)."""
    return hashlib.sha256(external_author_id.encode("utf-8")).hexdigest()
