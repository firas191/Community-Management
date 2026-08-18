"""Analyst agent endpoints (brief Section 11.6, Week 7).

  POST /agent/ask   ask a question; the agent calls analytics tools and answers
  GET  /agent/runs  recent runs with their tool traces (explainability)

Every answer is grounded in tool results and the full trace is persisted, so any
figure in an answer can be traced back to the function that produced it. Returns
503 with a hint when the agent or LLM extras are missing, or no provider is set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agent import service as agent_service
from app.agent.graph import AgentUnavailableError
from app.api.routes_llm import get_gateway
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.llm.gateway import LLMError, LLMGateway, LLMUnavailableError
from app.schemas.agent import AskRequest, AskResponse, RunsResponse

log = get_logger("api.agent")
router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_api_key)])


@router.post("/ask", response_model=AskResponse)
def ask(
    req: AskRequest,
    db: Session = Depends(get_db),
    gateway: LLMGateway = Depends(get_gateway),
) -> dict:
    try:
        result = agent_service.ask(
            db, gateway, req.question, account_id=req.account_id, conversation_id=req.conversation_id
        )
        db.commit()
        return result
    except agent_service.AgentServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (AgentUnavailableError, LLMUnavailableError, LLMError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/runs", response_model=RunsResponse)
def runs(
    account_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    return agent_service.recent_runs(db, account_id=account_id, limit=limit)
