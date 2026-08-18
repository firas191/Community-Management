"""Scheduled maintenance (brief Section 7.1/7.2: 30-day raw event retention).

Runs daily. `session_scope` commits, so a successful purge is durable and a
failure rolls back rather than half-deleting.
"""

from __future__ import annotations

from celery import shared_task

from app.core.db import session_scope
from app.core.logging import get_logger

log = get_logger("workers.maintenance")


@shared_task(name="app.workers.tasks_maintenance.purge_raw_events_task")
def purge_raw_events_task(days: int | None = None) -> dict:
    from app.ingestion.retention import RAW_EVENT_RETENTION_DAYS, purge_raw_events

    with session_scope() as db:
        result = purge_raw_events(db, days=days or RAW_EVENT_RETENTION_DAYS)
    log.info("purge_raw_events_done", **result)
    return result
