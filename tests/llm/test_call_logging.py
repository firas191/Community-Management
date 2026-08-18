"""Per-attempt LLM call logging (Week 6, extended Week 7). No DB needed.

A failover must leave a readable trail: one row per attempt, in order, with the
provider's own error message on the failed ones. Diagnosing a failover from SQL
(a retired model versus a rate limit) depends on that message being stored.
"""

from __future__ import annotations

from app.llm.gateway import Attempt, LLMResult
from app.llm.service import log_calls


class FakeSession:
    """Captures what would be persisted."""

    def __init__(self):
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def _result(*attempts: Attempt) -> LLMResult:
    return LLMResult(
        text="hi", provider="gemini", model="gemini/b", latency_ms=10,
        fallback_depth=len(attempts) - 1, attempts=list(attempts),
    )


def test_one_row_per_attempt_with_depth_in_order():
    result = _result(
        Attempt("groq", "groq/a", "error", 200, error="RateLimitError: quota"),
        Attempt("gemini", "gemini/b", "ok", 900, 11, 22),
    )
    db = FakeSession()
    log_calls(db, result, purpose="agent")

    assert len(db.added) == 2
    first, second = db.added
    assert (first.provider, first.status, first.fallback_depth) == ("groq", "error", 0)
    assert (second.provider, second.status, second.fallback_depth) == ("gemini", "ok", 1)
    assert all(row.purpose == "agent" for row in db.added)


def test_failed_attempt_stores_the_provider_message():
    result = _result(Attempt("groq", "groq/a", "error", 189, error="GroqException - model_not_found"))
    db = FakeSession()
    log_calls(db, result, purpose="agent")
    assert "model_not_found" in db.added[0].error


def test_error_is_truncated_and_success_has_none():
    result = _result(
        Attempt("groq", "groq/a", "error", 5, error="x" * 900),
        Attempt("gemini", "gemini/b", "ok", 10, 1, 2),
    )
    db = FakeSession()
    log_calls(db, result, purpose="agent")
    assert len(db.added[0].error) == 500  # bounded, so one bad reply cannot bloat the table
    assert db.added[1].error is None


def test_tokens_are_carried_through():
    result = _result(Attempt("gemini", "gemini/b", "ok", 10, 11, 22))
    db = FakeSession()
    log_calls(db, result, purpose="content_generation")
    assert (db.added[0].prompt_tokens, db.added[0].completion_tokens) == (11, 22)
