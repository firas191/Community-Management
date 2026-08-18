"""Topic modeling endpoints (brief Section 9.3, Week 8).

  POST /topics/run   cluster an account's recent comments into topics and store them
  GET  /topics       the stored topics for an account, largest first

BERTopic is an optional extra and is not installed in the application image (its
umap/hdbscan/numba chain caps numpy below the version the KPI engine pins), so
without it this endpoint answers 503 with an install hint rather than failing
obscurely. Everything else about the pipeline ships and is tested.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.nlp import topic_service
from app.nlp.topics import TopicsUnavailableError
from app.schemas.topics import DiscoverResponse, TopicsResponse

log = get_logger("api.topics")
router = APIRouter(prefix="/topics", tags=["topics"], dependencies=[Depends(require_api_key)])


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"{exc} (topic modeling needs the topics extra).",
    )


@router.post("/run", response_model=DiscoverResponse)
def run_topics(
    account_id: int = Query(...),
    window: str = Query("30d"),
    min_topic_size: int = Query(3, ge=2, le=50),
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = topic_service.discover_topics(
            db, account_id, window, min_topic_size=min_topic_size
        )
        db.commit()
        return result
    except topic_service.TopicServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TopicsUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.get("", response_model=TopicsResponse)
def list_topics(
    account_id: int = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return topic_service.list_topics(db, account_id, limit)
    except topic_service.TopicServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
