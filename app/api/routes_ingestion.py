"""Ingestion endpoints (brief Section 12).

  POST /ingestion/csv      multipart upload of a Business Suite / Kaggle export
  GET  /ingestion/status   row counts per table + sync cursors
  POST /ingestion/run      trigger a live connector sync

Live connectors (Meta Graph API, YouTube Data API) run via /ingestion/run using
credentials and target ids from settings. The CSV path stays fully functional and
needs no credentials.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.logging import get_logger
from app.core.security import require_api_key
from app.ingestion.csv_importer import CSVImportError, import_csv_bytes
from app.ingestion.http import HTTPError
from app.ingestion.sync import ConnectorConfigError, build_connector, run_connector
from app.models import (
    Account,
    Comment,
    Post,
    PostMetricSnapshot,
    SyncCursor,
)
from app.schemas.ingestion import (
    ConnectorRunResponse,
    CSVImportResponse,
    CursorStatus,
    IngestionStatusResponse,
)

log = get_logger("api.ingestion")
router = APIRouter(prefix="/ingestion", tags=["ingestion"], dependencies=[Depends(require_api_key)])


@router.post("/csv", response_model=CSVImportResponse)
async def import_csv(
    file: UploadFile = File(...),
    profile: str | None = Form(default=None),
    platform: str | None = Form(default=None),
    account_external_id: str | None = Form(default=None),
    account_name: str | None = Form(default=None),
    as_of: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> CSVImportResponse:
    content = await file.read()
    parsed_as_of: datetime | None = None
    if as_of:
        try:
            parsed_as_of = datetime.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"as_of must be ISO 8601, got '{as_of}'.",
            ) from None
    try:
        result = import_csv_bytes(
            db,
            content,
            profile_id=profile,
            platform_override=platform,
            default_account_external_id=account_external_id,
            default_account_name=account_name,
            as_of=parsed_as_of,
        )
        db.commit()
    except CSVImportError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return CSVImportResponse(
        source=result.source,
        profile=profile or "meta_business_suite_posts",
        accounts_upserted=result.accounts_upserted,
        posts_upserted=result.posts_upserted,
        snapshots_inserted=result.snapshots_inserted,
        comments_upserted=result.comments_upserted,
        rows_skipped=result.rows_skipped,
        skip_reasons=result.skip_reasons,
    )


@router.get("/status", response_model=IngestionStatusResponse)
async def status_endpoint(db: Session = Depends(get_db)) -> IngestionStatusResponse:
    counts = {
        "accounts": db.scalar(select(func.count()).select_from(Account)) or 0,
        "posts": db.scalar(select(func.count()).select_from(Post)) or 0,
        "post_metric_snapshots": db.scalar(select(func.count()).select_from(PostMetricSnapshot)) or 0,
        "comments": db.scalar(select(func.count()).select_from(Comment)) or 0,
    }
    cursors = [
        CursorStatus(
            source=c.source,
            account_external_id=c.account_external_id,
            entity_type=c.entity_type,
            cursor_value=c.cursor_value,
            updated_at=c.updated_at,
        )
        for c in db.scalars(select(SyncCursor)).all()
    ]
    return IngestionStatusResponse(row_counts=counts, cursors=cursors)


@router.post("/run", response_model=ConnectorRunResponse)
def run_connector_endpoint(
    connector: str = Form(...),
    db: Session = Depends(get_db),
) -> ConnectorRunResponse:
    """Run one incremental sync for a live connector (`youtube` or `meta`).

    Credentials and target channel/page ids come from settings. Returns a summary
    with upsert counts. 400 if the connector is unknown or not configured, 502 if
    the platform API itself fails.
    """
    try:
        conn = build_connector(connector)
        result = run_connector(db, conn)
        db.commit()
    except ConnectorConfigError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Connector API error: {exc}") from exc
    except Exception:
        db.rollback()
        raise

    return ConnectorRunResponse(
        source=result.source,
        accounts_upserted=result.accounts_upserted,
        posts_upserted=result.posts_upserted,
        snapshots_inserted=result.snapshots_inserted,
        comments_upserted=result.comments_upserted,
        rows_skipped=result.rows_skipped,
        skip_reasons=result.skip_reasons,
    )
