"""Recommendation endpoints (brief Sections 8.5, 12).

  POST /recommendations/best-time      best day/hour slots (display timezone)
  POST /recommendations/content-types  best content type by engagement lift
  POST /recommendations/hashtags       best hashtags by engagement lift
  POST /recommendations/all            all of the above in one call

These are POST because each call generates and persists a recommendation record
(kind / payload / confidence / evidence) for the audit trail the brief asks for.
Every item returned carries its evidence: sample size, lift over the account's
own baseline, and a confidence tier. Thin data yields a `reason`, never a guess.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics import recommend_service as reco
from app.analytics.service import AccountNotFoundError, KPIQueryError
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.schemas.recommend import (
    AllRecommendationsResponse,
    BestTimeResponse,
    CategoryResponse,
)

log = get_logger("api.recommend")
router = APIRouter(prefix="/recommendations", tags=["recommendations"], dependencies=[Depends(require_api_key)])


def _handle(exc: KPIQueryError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(exc, AccountNotFoundError) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/best-time", response_model=BestTimeResponse)
def best_time(
    account_id: int = Query(...),
    window: str = Query("90d"),
    top_k: int = Query(5, ge=1, le=24),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = reco.best_time(db, account_id, window, top_k=top_k, include_synthetic=include_synthetic)
        db.commit()
        return result
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.post("/content-types", response_model=CategoryResponse)
def content_types(
    account_id: int = Query(...),
    window: str = Query("90d"),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = reco.content_types(db, account_id, window, include_synthetic=include_synthetic)
        db.commit()
        return result
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.post("/hashtags", response_model=CategoryResponse)
def hashtags(
    account_id: int = Query(...),
    window: str = Query("90d"),
    top_k: int = Query(10, ge=1, le=50),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = reco.hashtags(db, account_id, window, top_k=top_k, include_synthetic=include_synthetic)
        db.commit()
        return result
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.post("/all", response_model=AllRecommendationsResponse)
def all_recommendations(
    account_id: int = Query(...),
    window: str = Query("90d"),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = reco.all_recommendations(db, account_id, window, include_synthetic=include_synthetic)
        db.commit()
        return result
    except KPIQueryError as exc:
        raise _handle(exc) from exc
