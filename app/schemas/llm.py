"""LLM request/response schemas (Week 6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    brief: str = Field(min_length=1, description="What the post should be about.")
    account_id: int | None = Field(default=None, description="Use this account's recent posts as brand voice.")
    n: int = Field(default=3, ge=1, le=8)
    language: str = "auto"
    tone: str = "friendly"
    platform: str = "instagram"


class GenerateResponse(BaseModel):
    account_id: int | None = None
    brief: str
    platform: str
    variants: list[str]
    provider: str
    model: str
    latency_ms: int
    fallback_depth: int
    cached: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ProvidersResponse(BaseModel):
    configured: dict[str, bool]
    chain: list[str]
    ready: bool
