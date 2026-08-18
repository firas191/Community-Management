"""Agent service: run a question and persist the run (Week 7). The DB layer.

Runs the graph, writes one ``agent_runs`` row with the question, the answer, the
full tool trace and the tool-call count (brief 11.6: explainability), and one
``llm_calls`` row per LLM attempt so agent traffic shows up in the same
observability table as everything else.

Transaction boundary follows the project convention: this layer stages rows; the
API route commits.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import graph
from app.llm.gateway import LLMGateway
from app.llm.service import log_calls
from app.models import Account, AgentRun


class AgentServiceError(ValueError):
    """Bad request (e.g. unknown account). Mapped to HTTP 404."""


def ask(
    db: Session,
    gateway: LLMGateway,
    question: str,
    *,
    account_id: int | None = None,
    conversation_id: str | None = None,
    persist: bool = True,
) -> dict:
    """Answer a question with the analytics tools and record the run."""
    if account_id is not None and db.get(Account, account_id) is None:
        raise AgentServiceError(f"Account {account_id} not found.")

    out = graph.run_agent(db, gateway, question, account_id=account_id)
    conversation_id = conversation_id or str(uuid.uuid4())

    if persist:
        for result in out["llm_results"]:
            log_calls(db, result, purpose="agent")
        db.add(
            AgentRun(
                account_id=account_id,
                conversation_id=conversation_id,
                question=question,
                answer=out["answer"],
                reasoning_trace={"tool_calls": out["trace"]},
                tool_call_count=out["tool_call_count"],
            )
        )

    return {
        "account_id": account_id,
        "conversation_id": conversation_id,
        "question": question,
        "answer": out["answer"],
        "tool_call_count": out["tool_call_count"],
        "trace": out["trace"],
        "provider": out["provider"],
        "model": out["model"],
        "latency_ms": out["latency_ms"],
    }


def recent_runs(db: Session, *, account_id: int | None = None, limit: int = 20) -> dict:
    """Recent agent runs, newest first, for the explainability view."""
    stmt = select(AgentRun).order_by(AgentRun.id.desc()).limit(min(limit, 100))
    if account_id is not None:
        stmt = stmt.where(AgentRun.account_id == account_id)
    rows = db.scalars(stmt).all()
    return {
        "count": len(rows),
        "runs": [
            {
                "id": r.id,
                "account_id": r.account_id,
                "conversation_id": r.conversation_id,
                "question": r.question,
                "answer": r.answer,
                "tool_call_count": r.tool_call_count,
                "trace": (r.reasoning_trace or {}).get("tool_calls", []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
