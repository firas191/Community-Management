"""Scheduled sentiment analysis (brief Section 7.2 `analyze_new_comments`).

Runs every 30 minutes (registered in celery_app beat_schedule). Pulls comments
that have no analysis row yet, runs the real Model A pipeline, and stores the
labels. Uses `shared_task` so this module has no import cycle with celery_app.
"""

from __future__ import annotations

from celery import shared_task

from app.core.db import session_scope
from app.core.logging import get_logger

log = get_logger("workers.analyze")


@shared_task(name="app.workers.tasks_analyze.analyze_new_comments_task")
def analyze_new_comments_task(limit: int = 500) -> dict:
    # Imported lazily so the worker boots even before the NLP extras are present;
    # the model only loads when this task actually runs.
    from app.nlp.sentiment import SentimentAnalyzer
    from app.nlp.service import analyze_new_comments

    analyzer = SentimentAnalyzer()
    with session_scope() as db:
        result = analyze_new_comments(db, analyzer, limit=limit)
    log.info("analyze_task_done", **result)
    return result
