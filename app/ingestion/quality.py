"""Data-quality guards applied at ingestion (brief Sections 7.1, 13).

Rules:
  - Reject negative engagement counts (corrupt row).
  - Reject timestamps more than a small tolerance into the future (clock skew ok).
  - Flag reach < likes as an anomaly (reach should bound engagement) but keep the row.

Pure functions, unit-tested. They return a verdict; the normalizer decides to
insert, skip, or flag based on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.ingestion.records import MetricSnapshotRecord, PostRecord
from config.constants import FUTURE_TIMESTAMP_TOLERANCE_MINUTES


@dataclass(slots=True)
class Verdict:
    ok: bool = True  # False = reject the row
    reject_reason: str | None = None
    flags: list[str] = field(default_factory=list)  # non-fatal data-quality notes


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # Treat naive timestamps as UTC so comparisons never raise.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def check_post(post: PostRecord, now: datetime | None = None) -> Verdict:
    now = now or _now_utc()
    tolerance = timedelta(minutes=FUTURE_TIMESTAMP_TOLERANCE_MINUTES)
    if _aware(post.published_at) > now + tolerance:
        return Verdict(ok=False, reject_reason="future_timestamp")
    if post.media_count < 0:
        return Verdict(ok=False, reject_reason="negative_media_count")
    return Verdict()


def check_metric(metric: MetricSnapshotRecord, now: datetime | None = None) -> Verdict:
    now = now or _now_utc()
    tolerance = timedelta(minutes=FUTURE_TIMESTAMP_TOLERANCE_MINUTES)

    if _aware(metric.captured_at) > now + tolerance:
        return Verdict(ok=False, reject_reason="future_timestamp")

    # Negative counts are corrupt. Nullable fields only checked when present.
    counts = {
        "likes": metric.likes,
        "comments_count": metric.comments_count,
        "shares": metric.shares,
        "saves": metric.saves,
        "reach": metric.reach,
        "impressions": metric.impressions,
        "video_views": metric.video_views,
        "clicks": metric.clicks,
    }
    for name, value in counts.items():
        if value is not None and value < 0:
            return Verdict(ok=False, reject_reason=f"negative_{name}")

    verdict = Verdict()
    engagement = metric.likes + metric.comments_count + metric.shares + metric.saves
    if metric.reach is not None and metric.reach < engagement:
        # Keep the row but flag it: reach should bound engagement (brief 8.1).
        verdict.flags.append("reach_lt_engagement")
    return verdict
