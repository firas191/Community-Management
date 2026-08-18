"""Topic discovery service (brief Section 9.3, Week 8). The DB-facing layer.

Loads an account's comments for a window, clusters them through the injected
backend, and stores each cluster as a `topics` row with its keywords, size, and
average sentiment. Each clustered comment's `comment_analyses.topic_id` is
updated, so "what are people talking about, and how do they feel about it" is one
join rather than a second model run.

Re-running for the same account and window replaces that window's topics, so the
job is idempotent and a re-run after more comments arrive does not duplicate rows.

Transaction boundary follows the project convention: this layer stages rows; the
API route (or Celery task) commits.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.analytics.service import parse_window
from app.core.logging import get_logger
from app.models import Account, Comment, CommentAnalysis, Post, Topic
from app.nlp import topics as topic_layer
from app.nlp.topics import TopicBackend

log = get_logger("nlp.topic_service")

# Net sentiment mapping, matching the sentiment summary rollup.
_NET = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}


class TopicServiceError(ValueError):
    """Bad request (unknown account, or not enough data). Mapped to HTTP 400/404."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_comments(db: Session, account_id: int, since: datetime, until: datetime) -> list[tuple]:
    """(comment_id, text, sentiment) for an account's comments in the window.

    Sentiment is left-joined: a comment with no analysis still takes part in
    clustering, it just does not contribute to the topic's sentiment average.
    """
    stmt = (
        select(Comment.id, Comment.text_content, CommentAnalysis.sentiment)
        .join(Post, Post.id == Comment.post_id)
        .outerjoin(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
        .where(
            Post.account_id == account_id,
            Comment.published_at >= since,
            Comment.published_at < until,
            Comment.text_content.is_not(None),
        )
        .order_by(Comment.id)
    )
    return [r for r in db.execute(stmt).all() if (r[1] or "").strip()]


def discover_topics(
    db: Session,
    account_id: int,
    window: str = "30d",
    *,
    backend: TopicBackend | None = None,
    min_topic_size: int = topic_layer.MIN_TOPIC_SIZE,
    persist: bool = True,
) -> dict:
    """Cluster an account's recent comments into topics and store them."""
    if db.get(Account, account_id) is None:
        raise TopicServiceError(f"Account {account_id} not found.")

    delta = parse_window(window)
    now = _now()
    since = now - delta
    rows = _load_comments(db, account_id, since, now)

    if len(rows) < topic_layer.MIN_DOCS_FOR_TOPICS:
        # Honest refusal rather than clustering noise into invented themes.
        return {
            "account_id": account_id, "window": window, "generated_at": now.isoformat(),
            "n_comments": len(rows), "n_topics": 0, "topics": [],
            "reason": "insufficient_data",
            "model_name": None, "model_version": None,
        }

    backend = backend or topic_layer.get_default_backend()
    docs = topic_layer.prepare_docs([r[1] for r in rows])
    _assignments, clusters = backend.fit(docs)
    keep = topic_layer.usable_clusters(clusters, min_topic_size)

    window_start, window_end = since.date(), now.date()
    if persist:
        # Idempotent: this window's topics for this account are replaced wholesale.
        db.execute(
            delete(Topic).where(
                Topic.account_id == account_id,
                Topic.window_start == window_start,
                Topic.window_end == window_end,
            )
        )

    out: list[dict] = []
    for cluster in sorted(keep, key=lambda c: c.size, reverse=True):
        comment_ids = [rows[i][0] for i in cluster.doc_indices]
        sentiments = [rows[i][2] for i in cluster.doc_indices if rows[i][2] in _NET]
        avg = topic_layer.average_sentiment([_NET[s] for s in sentiments])
        label = topic_layer.label_from_keywords(cluster.keywords)

        if persist:
            db.add(
                Topic(
                    account_id=account_id,
                    label=label,
                    keywords=cluster.keywords or None,
                    comment_count=cluster.size,
                    avg_sentiment=avg,
                    window_start=window_start,
                    window_end=window_end,
                )
            )
            # Link comments to their topic so sentiment-by-topic is a plain join.
            db.execute(
                update(CommentAnalysis)
                .where(CommentAnalysis.comment_id.in_(comment_ids))
                .values(topic_id=cluster.topic_id)
            )

        out.append(
            {
                "topic_id": cluster.topic_id,
                "label": label,
                "keywords": cluster.keywords,
                "comment_count": cluster.size,
                "avg_sentiment": avg,
                "n_labeled": len(sentiments),
            }
        )

    log.info("topics_discovered", account_id=account_id, n_topics=len(out), n_comments=len(rows))
    return {
        "account_id": account_id, "window": window, "generated_at": now.isoformat(),
        "n_comments": len(rows), "n_topics": len(out), "topics": out, "reason": None,
        "model_name": getattr(backend, "model_name", None),
        "model_version": getattr(backend, "model_version", None),
    }


def list_topics(db: Session, account_id: int, limit: int = 50) -> dict:
    """Stored topics for an account, largest first."""
    if db.get(Account, account_id) is None:
        raise TopicServiceError(f"Account {account_id} not found.")
    rows = db.scalars(
        select(Topic)
        .where(Topic.account_id == account_id)
        .order_by(Topic.comment_count.desc().nullslast())
        .limit(min(limit, 200))
    ).all()
    return {
        "account_id": account_id,
        "count": len(rows),
        "topics": [
            {
                "id": t.id,
                "label": t.label,
                "keywords": list(t.keywords or []),
                "comment_count": t.comment_count,
                "avg_sentiment": t.avg_sentiment,
                "window_start": t.window_start.isoformat() if t.window_start else None,
                "window_end": t.window_end.isoformat() if t.window_end else None,
            }
            for t in rows
        ],
    }
