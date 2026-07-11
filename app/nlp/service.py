"""Sentiment service (brief Sections 9.5, 9.6, 11.5). The only NLP layer with a DB.

Responsibilities:
  - analyze_new_comments: find comments with no analysis row, run the pipeline,
    store labels with model name + version (idempotent upsert on comment_id).
  - sentiment_summary: distribution, net sentiment, per-language breakdown, a
    daily trend, and deltas versus the previous window.
  - negative_alerts: recent negative comments plus per-day negative share, with
    the days flagged where the negative share spikes (mean + 2 sigma, n >= 10).

Sentiment is mapped to a net score for rollups: positive = +1, neutral = 0,
negative = -1. The mean over a window lands in [-1, 1].
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.analytics.service import AccountNotFoundError, parse_window
from app.core.logging import get_logger
from app.models import Account, Comment, CommentAnalysis, Post
from app.nlp.sentiment import SentimentAnalyzer

log = get_logger("nlp.service")

_NET = {"positive": 1, "neutral": 0, "negative": -1}
NEG_ALERT_MIN_COMMENTS = 10
NEG_ALERT_SIGMA = 2.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _account_scoped(stmt: Select, account_id: int | None) -> Select:
    if account_id is None:
        return stmt
    return stmt.join(Post, Post.id == Comment.post_id).where(Post.account_id == account_id)


def analyze_new_comments(
    db: Session,
    analyzer: SentimentAnalyzer,
    *,
    account_id: int | None = None,
    limit: int = 500,
) -> dict:
    """Analyze unlabeled comments and store results. Idempotent on comment_id."""
    stmt = select(Comment.id, Comment.text_content).where(
        ~select(CommentAnalysis.comment_id)
        .where(CommentAnalysis.comment_id == Comment.id)
        .exists()
    )
    stmt = _account_scoped(stmt, account_id).limit(limit)
    rows = db.execute(stmt).all()
    if not rows:
        return {"analyzed": 0, "skipped": 0}

    ids = [r[0] for r in rows]
    texts = [r[1] or "" for r in rows]
    results = analyzer.analyze(texts)

    stored = 0
    for cid, res in zip(ids, results, strict=True):
        ins = (
            pg_insert(CommentAnalysis)
            .values(
                comment_id=cid,
                language=res["language"],
                sentiment=res["sentiment"],
                sentiment_score=res["score"],
                model_name=res["model_name"],
                model_version=res["model_version"],
            )
            .on_conflict_do_update(
                index_elements=["comment_id"],
                set_={
                    "language": res["language"],
                    "sentiment": res["sentiment"],
                    "sentiment_score": res["score"],
                    "model_name": res["model_name"],
                    "model_version": res["model_version"],
                    "analyzed_at": _now(),
                },
            )
        )
        db.execute(ins)
        stored += 1
    # Persist the batch. The API session does not auto-commit, and a rolled-back
    # analysis is invisible to later read requests (each request is its own session).
    db.commit()
    log.info("comments_analyzed", stored=stored, account_id=account_id)
    return {"analyzed": stored, "skipped": 0}


def _labeled_rows(db: Session, account_id: int, since: datetime, until: datetime):
    """(sentiment, language, score, published_at) for analyzed comments in window."""
    stmt = (
        select(
            CommentAnalysis.sentiment,
            CommentAnalysis.language,
            CommentAnalysis.sentiment_score,
            Comment.published_at,
            Comment.text_content,
        )
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Post, Post.id == Comment.post_id)
        .where(
            Post.account_id == account_id,
            Comment.published_at >= since,
            Comment.published_at < until,
        )
    )
    return db.execute(stmt).all()


def _distribution(sentiments: list[str]) -> dict:
    total = len(sentiments)
    counts = Counter(sentiments)
    dist = {s: counts.get(s, 0) for s in ("positive", "neutral", "negative")}
    pct = {s: (round(dist[s] / total * 100, 2) if total else None) for s in dist}
    net = round(sum(_NET[s] for s in sentiments) / total, 4) if total else None
    return {"total": total, "counts": dist, "pct": pct, "net_sentiment": net}


def sentiment_summary(
    db: Session, account_id: int, window: str = "30d"
) -> dict:
    """Distribution, per-language breakdown, daily trend, and prior-window deltas."""
    if db.get(Account, account_id) is None:
        raise AccountNotFoundError(f"Account {account_id} not found.")
    delta = parse_window(window)
    now = _now()
    cur = _labeled_rows(db, account_id, now - delta, now)
    prev = _labeled_rows(db, account_id, now - 2 * delta, now - delta)

    cur_sent = [r[0] for r in cur]
    overall = _distribution(cur_sent)

    by_language: dict[str, dict] = {}
    langs = {r[1] for r in cur}
    for lang in langs:
        by_language[lang or "unknown"] = _distribution([r[0] for r in cur if r[1] == lang])

    # Daily net-sentiment trend (chart-ready), gap-free within the window.
    day_bucket: dict[str, list[int]] = {}
    for sent, _lang, _score, published, _text in cur:
        key = published.date().isoformat()
        day_bucket.setdefault(key, []).append(_NET[sent])
    labels = sorted(day_bucket)
    trend = {
        "labels": labels,
        "series": [{"name": "net_sentiment", "data": [round(statistics.fmean(day_bucket[d]), 4) for d in labels]}],
    }

    prev_overall = _distribution([r[0] for r in prev])
    deltas = {
        "net_sentiment": _delta(overall["net_sentiment"], prev_overall["net_sentiment"]),
        "negative_pct": _delta(overall["pct"]["negative"], prev_overall["pct"]["negative"]),
    }

    return {
        "account_id": account_id,
        "window": window,
        "generated_at": now.isoformat(),
        "overall": overall,
        "by_language": by_language,
        "trend": trend,
        "deltas": deltas,
    }


def _delta(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None:
        return None
    return round(cur - prev, 4)


def negative_alerts(
    db: Session, account_id: int, window: str = "14d", limit: int = 20
) -> dict:
    """Recent negatives plus per-day negative share, flagging spike days."""
    if db.get(Account, account_id) is None:
        raise AccountNotFoundError(f"Account {account_id} not found.")
    delta = parse_window(window)
    now = _now()
    rows = _labeled_rows(db, account_id, now - delta, now)

    # Per-day negative share.
    per_day: dict[str, list[str]] = {}
    for sent, _lang, _score, published, _text in rows:
        per_day.setdefault(published.date().isoformat(), []).append(sent)
    day_shares = {
        d: round(sum(1 for s in sents if s == "negative") / len(sents), 4)
        for d, sents in per_day.items()
    }
    # Spike rule (brief 11.5): share > mean + 2 sigma AND at least 10 comments.
    shares = list(day_shares.values())
    threshold = None
    if len(shares) >= 2:
        mu, sigma = statistics.fmean(shares), statistics.pstdev(shares)
        threshold = mu + NEG_ALERT_SIGMA * sigma
    flagged = [
        {"date": d, "negative_share": day_shares[d], "n_comments": len(per_day[d])}
        for d in sorted(per_day)
        if threshold is not None
        and day_shares[d] > threshold
        and len(per_day[d]) >= NEG_ALERT_MIN_COMMENTS
    ]

    recent = sorted(
        (r for r in rows if r[0] == "negative"), key=lambda r: r[3], reverse=True
    )[:limit]
    recent_negatives = [
        {
            "text": r[4],
            "language": r[1],
            "score": round(float(r[2]), 4),
            "published_at": r[3].isoformat(),
        }
        for r in recent
    ]

    return {
        "account_id": account_id,
        "window": window,
        "generated_at": now.isoformat(),
        "flagged_days": flagged,
        "recent_negatives": recent_negatives,
    }
