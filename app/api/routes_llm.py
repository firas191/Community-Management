"""LLM endpoints (brief Section 11.3, Week 6).

  POST /llm/generate   generate caption options for a brief (uses failover + logging)
  GET  /llm/providers  which providers are configured and the active failover chain

Generation persists the result to ``generated_contents`` and one ``llm_calls`` row
per attempt, so failovers and token usage are auditable. If the ``llm`` extra is not
installed, or no provider key is set, the endpoint returns 503 with a clear hint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.llm import providers
from app.llm import service as llm_service
from app.llm.gateway import LLMError, LLMGateway, LLMUnavailableError
from app.schemas.llm import GenerateRequest, GenerateResponse, ProvidersResponse

log = get_logger("api.llm")
router = APIRouter(prefix="/llm", tags=["llm"], dependencies=[Depends(require_api_key)])


def get_gateway() -> LLMGateway:
    """Default gateway (litellm-backed). Overridden with a stub in tests."""
    return LLMGateway()


@router.get("/providers", response_model=ProvidersResponse)
def providers_status() -> dict:
    return providers.status(settings)


@router.post("/generate", response_model=GenerateResponse)
def generate(
    req: GenerateRequest,
    db: Session = Depends(get_db),
    gateway: LLMGateway = Depends(get_gateway),
) -> dict:
    try:
        result = llm_service.generate_content(
            db, gateway,
            brief=req.brief, account_id=req.account_id, n=req.n,
            language=req.language, tone=req.tone, platform=req.platform,
        )
        db.commit()
        return result
    except llm_service.LLMServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc} (endpoint needs the LLM extra).",
        ) from exc
    except LLMError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
