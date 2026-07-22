"""Recommendation query service (brief Section 8.5). The DB-facing layer.

Loads an account's posts joined to their latest snapshot, computes each post's
primary engagement rate and its local-timezone day/hour, and hands plain tuples
to the pure ``recommend`` module. The returned recommendations are persisted to
the ``recommendations`` table (kind / payload / confidence / evidence) so the
dashboard can show them with their evidence, exactly as the brief requires.

Timezone matters here: "best time to post" is meaningless in UTC for a Tunisian
audience, so publish times are converted to the display timezone (Africa/Tunis)
before the day-of-week and hour buckets are formed.

Transaction boundary follows the project convention: this layer stages rows but
does not commit; the API route (or Celery task) owns the commit.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.analytics import kpi, recommend
from app.analytics.service import (
    _get_account,
    _now,
    _pm_from_row,
    load_posts_df,
    parse_window,
)
from app.models import Platform, Recommendation
from config.constants import DISPLAY_TZ_DEFAULT


def _er_rows(df: pd.DataFrame, tz: str) -> tuple[list[dict], str]:
    """Per-post {er, content_type, text, dow, hour} for posts whose primary ER resolves.

    Returns the rows and the dominant ER basis (err/erf) across them, so the basis
    is disclosed with every recommendation.
    """
    rows: list[dict] = []
    bases: list[str] = []
    if df.empty:
        return rows, "none"
    for _, r in df.iterrows():
        metric, basis = kpi.primary_engagement_rate(_pm_from_row(r))
        if not metric.ok:
            continue
        ts = pd.to_datetime(r["published_at"], utc=True).tz_convert(tz)
        rows.append(
            {
                "er": float(metric.value),
                "content_type": r.get("content_type"),
                "text": r.get("text_content"),
                "dow": int(ts.weekday()),  # 0 = Monday
                "hour": int(ts.hour),
            }
        )
        bases.append(basis)
    dominant = max(set(bases), key=bases.count) if bases else "none"
    return rows, dominant


def _persist(db: Session, account_id: int, kind: str, payload: dict, confidence: str | None, evidence: dict) -> None:
    db.add(
        Recommendation(
            account_id=account_id,
            kind=kind,
            payload=payload,
            confidence=confidence,
            evidence=evidence,
        )
    )


def _envelope(account_id: int, window: str, kind: str, basis: str, now, result: dict) -> dict:
    return {
        "account_id": account_id,
        "window": window,
        "kind": kind,
        "engagement_rate_basis": basis,
        "generated_at": now.isoformat(),
        **result,
    }


def best_time(
    db: Session,
    account_id: int,
    window: str = "90d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
    top_k: int = 5,
    persist: bool = True,
) -> dict:
    """Best day/hour slots to post, in the display timezone, with evidence."""
    _get_account(db, account_id)
    now = _now()
    since = now - parse_window(window)
    df = load_posts_df(db, account_id=account_id, since=since, until=now, include_synthetic=include_synthetic)
    rows, basis = _er_rows(df, tz)

    result = recommend.recommend_best_time([(r["dow"], r["hour"], r["er"]) for r in rows], top_k=top_k)
    result["timezone"] = tz
    top = result["top_cells"][0] if result["top_cells"] else None
    confidence = top["confidence"] if top else None
    if persist:
        _persist(
            db, account_id, "best_time", result, confidence,
            {"n_posts": len(rows), "baseline_er": result["baseline_er"], "basis": basis, "window": window, "timezone": tz},
        )
    return _envelope(account_id, window, "best_time", basis, now, result)


def content_types(
    db: Session,
    account_id: int,
    window: str = "90d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
    persist: bool = True,
) -> dict:
    """Which content type (image/video/carousel/...) earns the most engagement."""
    _get_account(db, account_id)
    now = _now()
    since = now - parse_window(window)
    df = load_posts_df(db, account_id=account_id, since=since, until=now, include_synthetic=include_synthetic)
    rows, basis = _er_rows(df, tz)

    obs = [(str(r["content_type"] or "unknown"), r["er"]) for r in rows]
    result = recommend.rank_categories(obs, top_k=None)
    top = result["ranked"][0] if result["ranked"] else None
    confidence = top["confidence"] if top else None
    if persist:
        _persist(
            db, account_id, "content_type", result, confidence,
            {"n_posts": len(rows), "baseline_er": result["baseline_er"], "basis": basis, "window": window},
        )
    return _envelope(account_id, window, "content_type", basis, now, result)


def hashtags(
    db: Session,
    account_id: int,
    window: str = "90d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
    top_k: int = 10,
    persist: bool = True,
) -> dict:
    """Best-performing hashtags by engagement lift over the account's baseline."""
    _get_account(db, account_id)
    now = _now()
    since = now - parse_window(window)
    df = load_posts_df(db, account_id=account_id, since=since, until=now, include_synthetic=include_synthetic)
    rows, basis = _er_rows(df, tz)

    result = recommend.recommend_hashtags([(r["text"], r["er"]) for r in rows], top_k=top_k)
    top = result["ranked"][0] if result["ranked"] else None
    confidence = top["confidence"] if top else None
    if persist:
        _persist(
            db, account_id, "hashtags", result, confidence,
            {"n_posts": len(rows), "baseline_er": result["baseline_er"], "basis": basis, "window": window},
        )
    return _envelope(account_id, window, "hashtags", basis, now, result)


def all_recommendations(
    db: Session,
    account_id: int,
    window: str = "90d",
    *,
    tz: str = DISPLAY_TZ_DEFAULT,
    include_synthetic: bool = True,
    persist: bool = True,
) -> dict:
    """All recommendation kinds for an account in one call."""
    acc = _get_account(db, account_id)
    now = _now()
    return {
        "account_id": account_id,
        "handle": acc.handle,
        "platform": db.get(Platform, acc.platform_id).name if acc.platform_id else None,
        "window": window,
        "generated_at": now.isoformat(),
        "best_time": best_time(db, account_id, window, tz=tz, include_synthetic=include_synthetic, persist=persist),
        "content_type": content_types(db, account_id, window, tz=tz, include_synthetic=include_synthetic, persist=persist),
        "hashtags": hashtags(db, account_id, window, tz=tz, include_synthetic=include_synthetic, persist=persist),
    }
