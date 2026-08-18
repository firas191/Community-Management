"""Analyst agent request/response schemas (Week 7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="A question about the account's performance.")
    account_id: int | None = Field(default=None, description="Account context for the question.")
    conversation_id: str | None = Field(default=None, description="Group turns of one conversation.")


class TraceStep(BaseModel):
    step: int
    tool: str
    arguments: str
    ok: bool
    result: str
    truncated: bool = False


class AskResponse(BaseModel):
    account_id: int | None = None
    conversation_id: str
    question: str
    answer: str
    tool_call_count: int
    trace: list[TraceStep]
    provider: str | None = None
    model: str | None = None
    latency_ms: int


class RunOut(BaseModel):
    id: int
    account_id: int | None = None
    conversation_id: str | None = None
    question: str
    answer: str | None = None
    tool_call_count: int | None = None
    trace: list[TraceStep] = []
    created_at: str | None = None


class RunsResponse(BaseModel):
    count: int
    runs: list[RunOut]
