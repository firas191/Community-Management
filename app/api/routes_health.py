"""Health and meta endpoints (brief Section 12).

/health/live is unauthenticated for orchestrator probes.
/health checks db + redis and reports degraded if any dependency is down.
/meta/models lists loaded model names + versions (populated as NLP/LLM land).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.core.cache import ping as redis_ping
from app.core.db import get_db
from app.schemas.health import DependencyStatus, HealthResponse, LivenessResponse
from config.constants import (
    EMBEDDING_MODEL,
    SENTIMENT_MODEL_MULTILINGUAL,
)

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get("/health", response_model=HealthResponse)
async def health(db: Session = Depends(get_db)) -> HealthResponse:
    deps: list[DependencyStatus] = []

    try:
        db.execute(text("SELECT 1"))
        deps.append(DependencyStatus(name="postgres", ok=True))
    except Exception as exc:  # pragma: no cover - exercised only on real outage
        deps.append(DependencyStatus(name="postgres", ok=False, detail=str(exc)))

    deps.append(DependencyStatus(name="redis", ok=redis_ping()))

    status = "ok" if all(d.ok for d in deps) else "degraded"
    return HealthResponse(status=status, version=__version__, dependencies=deps)


@router.get("/meta/models", tags=["meta"])
async def models() -> dict:
    # Registry of models the system will load. Versions filled in as weeks land.
    return {
        "sentiment_multilingual": {"name": SENTIMENT_MODEL_MULTILINGUAL, "version": "pending"},
        "embedding": {"name": EMBEDDING_MODEL, "version": "pending"},
        "arabizi_finetuned": {"name": "community-management-arabizi", "version": "not_trained"},
    }
