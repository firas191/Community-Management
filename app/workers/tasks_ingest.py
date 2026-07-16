"""Scheduled live ingestion (brief Section 7.2 `ingest_recent`).

Runs every 30 minutes per connector. If the connector is not configured (no API
key or no target ids), it logs and skips instead of failing, so the schedule is
safe to enable before credentials are set. Uses `session_scope`, which commits.
"""

from __future__ import annotations

from celery import shared_task

from app.core.db import session_scope
from app.core.logging import get_logger

log = get_logger("workers.ingest")


@shared_task(name="app.workers.tasks_ingest.ingest_recent_task")
def ingest_recent_task(connector: str = "youtube") -> dict:
    from app.ingestion.sync import ConnectorConfigError, build_connector, run_connector

    try:
        conn = build_connector(connector)
    except ConnectorConfigError as exc:
        log.info("ingest_skipped_unconfigured", connector=connector, detail=str(exc))
        return {"skipped": str(exc)}

    with session_scope() as db:
        result = run_connector(db, conn)
    log.info(
        "ingest_done",
        source=result.source,
        posts=result.posts_upserted,
        snapshots=result.snapshots_inserted,
        comments=result.comments_upserted,
    )
    return {
        "source": result.source,
        "posts": result.posts_upserted,
        "snapshots": result.snapshots_inserted,
        "comments": result.comments_upserted,
    }
