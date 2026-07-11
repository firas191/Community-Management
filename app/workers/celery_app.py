"""Celery application (brief Sections 4, 7.2).

Redis is broker and result backend. The full ingestion/analysis/report schedule
from Section 7.2 is added as each job's code lands in its roadmap week. Week 1
ships one real heartbeat task so the worker and beat services are proven to run
end to end under `docker compose up`.
"""

from __future__ import annotations

from celery import Celery

from app.config import settings
from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("workers.celery")

celery_app = Celery(
    "community_management",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

# Beat schedule. Section 7.2 jobs are registered as their code lands (Week 3+).
celery_app.conf.beat_schedule = {
    "heartbeat-every-5-min": {
        "task": "app.workers.celery_app.heartbeat",
        "schedule": 300.0,
    },
}


@celery_app.task(name="app.workers.celery_app.heartbeat")
def heartbeat() -> str:
    """Proves the worker+beat wiring. Replaced by real jobs in Section 7.2 order."""
    log.info("celery_heartbeat")
    return "ok"
