"""KPI endpoints (brief Sections 8, 12).

  GET /kpi/overview      headline KPIs + deltas vs previous window
  GET /kpi/timeseries    any metric, any granularity, gap-filled, chart-ready
  GET /kpi/by-platform   raw KPIs + z-score vs each platform's own 90-day baseline
  GET /kpi/top-posts     posts ranked by a metric, each with a KPI breakdown

Results are cached in Redis for 15 minutes (brief Section 6.3). The cache is a
pure optimization: if Redis is unreachable the endpoint still computes and serves
the answer, it just skips the cache. Numbers never depend on the cache being up.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics import service
from app.analytics.service import AccountNotFoundError, KPIQueryError
from app.core.cache import cache_get_json, cache_set_json
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.schemas.kpi import (
    ByPlatformResponse,
    KPIOverviewResponse,
    TimeSeriesResponse,
    TopPostsResponse,
)

log = get_logger("api.kpi")
router = APIRouter(prefix="/kpi", tags=["kpi"], dependencies=[Depends(require_api_key)])

CACHE_TTL_SECONDS = 15 * 60


def _cache_key(endpoint: str, params: dict[str, Any]) -> str:
    raw = json.dumps({"e": endpoint, "p": params}, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"cache:kpi:{endpoint}:{digest}"


def _cached(key: str, compute: Callable[[], dict]) -> dict:
    """Serve from cache when possible, else compute and populate. Never fail on Redis."""
    try:
        hit = cache_get_json(key)
        if hit is not None:
            hit["_cache"] = "hit"
            return hit
    except Exception:  # noqa: BLE001 - cache is optional, degrade silently
        log.warning("cache_read_failed", key=key)
    result = compute()
    try:
        cache_set_json(key, result, CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        log.warning("cache_write_failed", key=key)
    result = {**result, "_cache": "miss"}
    return result


def _handle(exc: KPIQueryError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if isinstance(exc, AccountNotFoundError) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _parse_dt(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} must be ISO 8601, got '{value}'.",
        ) from None


@router.get("/overview", response_model=KPIOverviewResponse)
def kpi_overview(
    account_id: int = Query(...),
    window: str = Query("30d"),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    key = _cache_key("overview", {"a": account_id, "w": window, "s": include_synthetic})
    try:
        return _cached(key, lambda: service.overview(db, account_id, window, include_synthetic=include_synthetic))
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.get("/timeseries", response_model=TimeSeriesResponse)
def kpi_timeseries(
    account_id: int = Query(...),
    metric: str = Query("err"),
    granularity: str = Query("day"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    rolling: int | None = Query(None, ge=2, le=90),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    dt_from = _parse_dt(date_from, "from")
    dt_to = _parse_dt(date_to, "to")
    key = _cache_key(
        "timeseries",
        {"a": account_id, "m": metric, "g": granularity, "f": date_from, "t": date_to, "r": rolling, "s": include_synthetic},
    )
    try:
        return _cached(
            key,
            lambda: service.timeseries(
                db, account_id, metric, granularity,
                dt_from=dt_from, dt_to=dt_to, rolling=rolling, include_synthetic=include_synthetic,
            ),
        )
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.get("/by-platform", response_model=ByPlatformResponse)
def kpi_by_platform(
    window: str = Query("30d"),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    key = _cache_key("by_platform", {"w": window, "s": include_synthetic})
    try:
        return _cached(key, lambda: service.by_platform(db, window, include_synthetic=include_synthetic))
    except KPIQueryError as exc:
        raise _handle(exc) from exc


@router.get("/top-posts", response_model=TopPostsResponse)
def kpi_top_posts(
    account_id: int = Query(...),
    metric: str = Query("err"),
    limit: int = Query(10, ge=1, le=100),
    window: str | None = Query(None),
    include_synthetic: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    key = _cache_key("top_posts", {"a": account_id, "m": metric, "l": limit, "w": window, "s": include_synthetic})
    try:
        return _cached(
            key,
            lambda: service.top_posts(db, account_id, metric, limit, window=window, include_synthetic=include_synthetic),
        )
    except KPIQueryError as exc:
        raise _handle(exc) from exc
