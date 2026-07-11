"""Health/meta response schemas (brief Section 12)."""

from __future__ import annotations

from pydantic import BaseModel


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" or "degraded"
    version: str
    dependencies: list[DependencyStatus]


class LivenessResponse(BaseModel):
    status: str = "ok"
