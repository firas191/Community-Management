"""Sentiment endpoints (brief Section 9.6).

  POST /sentiment/analyze          ad-hoc texts -> per-text language + sentiment
  POST /sentiment/run              analyze stored comments that have no label yet
  GET  /sentiment/summary          distribution, per-language, trend, deltas
  GET  /sentiment/negative-alerts  recent negatives + spike days

The sentiment model is injected via `get_analyzer`, so tests swap in a stub
backend. If the model cannot load (NLP extras not installed) the endpoints that
need it return 503 with an actionable message instead of a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.service import AccountNotFoundError, KPIQueryError
from app.core.db import get_db
from app.core.security import require_api_key
from app.nlp import service
from app.nlp.sentiment import SentimentAnalyzer
from app.schemas.sentiment import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeRunResponse,
    NegativeAlertsResponse,
    SummaryResponse,
)

router = APIRouter(prefix="/sentiment", tags=["sentiment"], dependencies=[Depends(require_api_key)])


def get_analyzer() -> SentimentAnalyzer:
    """Default analyzer (real Model A, lazy-loaded). Overridden in tests."""
    return SentimentAnalyzer()


def _model_unavailable(exc: RuntimeError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def _query_error(exc: KPIQueryError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(exc, AccountNotFoundError) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, analyzer: SentimentAnalyzer = Depends(get_analyzer)) -> dict:
    try:
        results = analyzer.analyze(req.texts)
    except RuntimeError as exc:
        raise _model_unavailable(exc) from exc
    return {"results": results}


@router.post("/run", response_model=AnalyzeRunResponse)
def run_batch(
    account_id: int | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    analyzer: SentimentAnalyzer = Depends(get_analyzer),
) -> dict:
    try:
        return service.analyze_new_comments(db, analyzer, account_id=account_id, limit=limit)
    except RuntimeError as exc:
        raise _model_unavailable(exc) from exc


@router.get("/summary", response_model=SummaryResponse)
def summary(
    account_id: int = Query(...),
    window: str = Query("30d"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return service.sentiment_summary(db, account_id, window)
    except KPIQueryError as exc:
        raise _query_error(exc) from exc


@router.get("/negative-alerts", response_model=NegativeAlertsResponse)
def negative_alerts(
    account_id: int = Query(...),
    window: str = Query("14d"),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return service.negative_alerts(db, account_id, window, limit)
    except KPIQueryError as exc:
        raise _query_error(exc) from exc
