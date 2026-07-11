"""KPI formula engine (brief Section 8). Pure functions only.

Every rate is a percentage rounded to 2 decimals. Every function is pure: it
takes numbers and returns a `Metric`, so each one is unit-tested against a
hand-computed fixture. No database, no pandas, no clock in this module.

The honesty rule (brief Section 8.1): a rate whose denominator is missing or
non-positive returns `Metric(None, reason)`, never 0. A zero would lie; a null
with a stable machine-readable reason tells the dashboard exactly why.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

ROUND_DP = 2
RATIO_DP = 4


class Reason:
    """Stable, dashboard-facing reason codes for a null KPI. Do not rename."""

    REACH_UNAVAILABLE = "reach_unavailable"
    FOLLOWERS_UNAVAILABLE = "followers_unavailable"
    IMPRESSIONS_UNAVAILABLE = "impressions_unavailable"
    CLICKS_UNAVAILABLE = "clicks_unavailable"
    VIDEO_VIEWS_UNAVAILABLE = "video_views_unavailable"
    NON_POSITIVE_DENOMINATOR = "non_positive_denominator"
    INSUFFICIENT_SNAPSHOTS = "insufficient_snapshots"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class Metric:
    """A KPI value or an honest null with a reason. Never a lying zero."""

    value: float | None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict[str, float | str | None]:
        return {"value": self.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PostMetrics:
    """The inputs a single post's KPIs are computed from."""

    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    reach: int | None = None
    impressions: int | None = None
    video_views: int | None = None
    clicks: int | None = None
    followers: int | None = None

    @property
    def engagement(self) -> int:
        """Total engagement actions = likes + comments + shares + saves."""
        return self.likes + self.comments + self.shares + self.saves


def _rate(numerator: float, denominator: float | None, missing_reason: str) -> Metric:
    """Percentage = numerator / denominator * 100, with the honesty guard.

    A `None` denominator means the platform does not expose that field: return
    the caller's specific reason. A `<= 0` denominator is present-but-unusable:
    return NON_POSITIVE_DENOMINATOR. A zero numerator over a positive denominator
    is a truthful 0.0.
    """
    if denominator is None:
        return Metric(None, missing_reason)
    if denominator <= 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    return Metric(round(numerator / denominator * 100.0, ROUND_DP))


# --- Post-level KPIs (brief Section 8.1) ---
def engagement_rate_by_reach(pm: PostMetrics) -> Metric:
    """ERR = (L + C + S + Sv) / reach * 100. Primary ER when reach is exposed."""
    return _rate(pm.engagement, pm.reach, Reason.REACH_UNAVAILABLE)


def engagement_rate_by_followers(pm: PostMetrics) -> Metric:
    """ERF = (L + C + S + Sv) / followers * 100. Fallback when reach is hidden."""
    return _rate(pm.engagement, pm.followers, Reason.FOLLOWERS_UNAVAILABLE)


def engagement_rate_by_impressions(pm: PostMetrics) -> Metric:
    return _rate(pm.engagement, pm.impressions, Reason.IMPRESSIONS_UNAVAILABLE)


def amplification_rate(pm: PostMetrics) -> Metric:
    """Shares / followers * 100. Willingness to share is the strongest signal."""
    return _rate(pm.shares, pm.followers, Reason.FOLLOWERS_UNAVAILABLE)


def applause_rate(pm: PostMetrics) -> Metric:
    return _rate(pm.likes, pm.followers, Reason.FOLLOWERS_UNAVAILABLE)


def conversation_rate(pm: PostMetrics) -> Metric:
    return _rate(pm.comments, pm.followers, Reason.FOLLOWERS_UNAVAILABLE)


def save_rate(pm: PostMetrics) -> Metric:
    return _rate(pm.saves, pm.reach, Reason.REACH_UNAVAILABLE)


def virality_rate(pm: PostMetrics) -> Metric:
    return _rate(pm.shares, pm.reach, Reason.REACH_UNAVAILABLE)


def click_through_rate(pm: PostMetrics) -> Metric:
    if pm.clicks is None:
        return Metric(None, Reason.CLICKS_UNAVAILABLE)
    return _rate(pm.clicks, pm.impressions, Reason.IMPRESSIONS_UNAVAILABLE)


def video_view_rate(pm: PostMetrics) -> Metric:
    if pm.video_views is None:
        return Metric(None, Reason.VIDEO_VIEWS_UNAVAILABLE)
    return _rate(pm.video_views, pm.reach, Reason.REACH_UNAVAILABLE)


def engagement_velocity(first_24h_engagement: int | None, total_engagement: int | None) -> Metric:
    """Fraction of total engagement earned in the first 24h. Predicts winners early.

    Needs at least two metric snapshots to measure the first-24h figure. With a
    single snapshot (CSV import, one live fetch) the first-24h value is unknown,
    so this returns null with INSUFFICIENT_SNAPSHOTS rather than a fake number.
    """
    if total_engagement is None or total_engagement <= 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    if first_24h_engagement is None:
        return Metric(None, Reason.INSUFFICIENT_SNAPSHOTS)
    return Metric(round(first_24h_engagement / total_engagement, RATIO_DP))


# The primary per-post engagement rate: ERR where reach exists, else ERF.
# The basis is reported so a mixed IG/FB/YouTube feed stays comparable and honest.
def primary_engagement_rate(pm: PostMetrics) -> tuple[Metric, str]:
    """Return (metric, basis) where basis is 'err', 'erf', or 'none'."""
    err = engagement_rate_by_reach(pm)
    if err.ok:
        return err, "err"
    erf = engagement_rate_by_followers(pm)
    if erf.ok:
        return erf, "erf"
    return Metric(None, err.reason), "none"


def compute_post_kpis(pm: PostMetrics) -> dict[str, Metric]:
    """All post-level KPIs as a name -> Metric map (brief Section 8.1 table)."""
    return {
        "engagement_rate_by_reach": engagement_rate_by_reach(pm),
        "engagement_rate_by_followers": engagement_rate_by_followers(pm),
        "engagement_rate_by_impressions": engagement_rate_by_impressions(pm),
        "amplification_rate": amplification_rate(pm),
        "applause_rate": applause_rate(pm),
        "conversation_rate": conversation_rate(pm),
        "save_rate": save_rate(pm),
        "virality_rate": virality_rate(pm),
        "click_through_rate": click_through_rate(pm),
        "video_view_rate": video_view_rate(pm),
    }


# --- Account-level KPIs (brief Section 8.2). Still pure: lists in, Metric out. ---
def mean_metric(values: list[float]) -> Metric:
    if not values:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    return Metric(round(statistics.fmean(values), ROUND_DP))


def median_metric(values: list[float]) -> Metric:
    """Report median alongside mean: the ER distribution is right-skewed."""
    if not values:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    return Metric(round(statistics.median(values), ROUND_DP))


def posting_frequency_per_week(n_posts: int, window_days: float) -> Metric:
    if window_days <= 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    return Metric(round(n_posts / (window_days / 7.0), ROUND_DP))


def posting_consistency(published_ats: list[datetime]) -> Metric:
    """Stddev (in hours) of the gaps between consecutive posts. Lower is steadier."""
    if len(published_ats) < 3:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    ordered = sorted(published_ats)
    gaps_hours = [
        (b - a).total_seconds() / 3600.0 for a, b in zip(ordered, ordered[1:], strict=False)
    ]
    return Metric(round(statistics.stdev(gaps_hours), ROUND_DP))


def follower_growth_rate(f_start: int | None, f_end: int | None) -> Metric:
    """(F_end - F_start) / F_start * 100 over the window."""
    if f_start is None or f_end is None:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    if f_start <= 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    return Metric(round((f_end - f_start) / f_start * 100.0, ROUND_DP))


def net_follower_change(f_start: int | None, f_end: int | None) -> Metric:
    if f_start is None or f_end is None:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    return Metric(float(f_end - f_start))


def delta_pct(current: float | None, previous: float | None) -> Metric:
    """Period-over-period percentage change (brief Section 8.3 WoW/MoM deltas)."""
    if current is None or previous is None:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    if previous == 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    return Metric(round((current - previous) / abs(previous) * 100.0, ROUND_DP))
