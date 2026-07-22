"""Recommendation engine (brief Section 8.5). Pure functions only.

Turns a set of posts and their engagement rates into explainable recommendations:
best time to post, best content type, and best hashtags. Every recommendation
carries its evidence: the sample size ``n``, the ``lift`` over the account's own
baseline, and a ``confidence`` tier. No recommendation is ever a bare number.

Two honesty rules, mirroring the KPI engine:

1. Small samples do not win by luck. Each group's ranking score is a shrinkage
   estimate that pulls a thin group toward the overall mean, so "one lucky post
   at 3am" cannot beat a well-sampled slot. The raw mean is still reported.
2. Not enough data returns a reason, never a fabricated pick. A group below the
   minimum sample size is disclosed with ``confidence=None``; a whole request
   with too little data returns ``reason="insufficient_data"``.

No database, no pandas, no clock in this module. The service layer feeds it lists
of ``(key, engagement_rate)`` tuples and stores the returned dicts as-is.
"""

from __future__ import annotations

import re
from collections import defaultdict

ER_DP = 4  # engagement-rate values are percentages; keep 4 dp for stable ranking
LIFT_DP = 2

# Sample-size thresholds for the confidence tiers. Below CONF_MIN_N a group is
# too thin to surface as a recommendation at all.
CONF_HIGH_N = 8
CONF_MED_N = 4
CONF_MIN_N = 2

# Shrinkage pseudo-count. A group's ranking score is
#   (sum(er) + K * baseline) / (n + K)
# so a group with n << K sits near the baseline and cannot top the list on noise.
# K = 5 means a slot needs on the order of five posts before its own mean carries.
SHRINKAGE_K = 5.0

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


class Reason:
    """Stable, dashboard-facing reason codes for an empty recommendation."""

    INSUFFICIENT_DATA = "insufficient_data"
    NO_ENGAGEMENT_SIGNAL = "no_engagement_signal"
    NO_HASHTAGS = "no_hashtags"


def confidence_for(n: int) -> str | None:
    """Confidence tier from a sample size. None below the minimum (too thin)."""
    if n >= CONF_HIGH_N:
        return "high"
    if n >= CONF_MED_N:
        return "medium"
    if n >= CONF_MIN_N:
        return "low"
    return None


def lift(value: float, baseline: float) -> float | None:
    """How many times the baseline a value is. None when the baseline is non-positive."""
    if baseline <= 0:
        return None
    return round(value / baseline, LIFT_DP)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def shrunk_mean(values: list[float], baseline: float, k: float = SHRINKAGE_K) -> float:
    """Shrinkage estimate: pulls a small group toward the baseline (James-Stein flavor)."""
    n = len(values)
    if n == 0:
        return baseline
    return (sum(values) + k * baseline) / (n + k)


def extract_hashtags(text: str | None) -> list[str]:
    """Unique, lowercased hashtags in a post, order preserved. Unicode-aware (Arabic ok)."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for tag in _HASHTAG_RE.findall(text):
        seen.setdefault(tag.lower(), None)
    return list(seen)


def _summarize(values: list[float], baseline: float, k: float) -> dict:
    """Evidence bundle for one group: n, raw mean, shrinkage score, lift, confidence."""
    n = len(values)
    mean_er = round(_mean(values), ER_DP)
    return {
        "n": n,
        "mean_er": mean_er,
        "shrunk_score": round(shrunk_mean(values, baseline, k), ER_DP),
        "lift": lift(mean_er, baseline),
        "confidence": confidence_for(n),
    }


def rank_categories(
    observations: list[tuple[str, float]],
    *,
    min_n: int = CONF_MIN_N,
    top_k: int | None = None,
    k_shrink: float = SHRINKAGE_K,
) -> dict:
    """Rank category keys by shrinkage-adjusted engagement rate, with evidence.

    ``observations`` is a list of ``(category, engagement_rate)``. Used for both
    content-type and hashtag recommendations. Categories below ``min_n`` samples
    are excluded from the ranking (disclosed via the counts), and if nothing
    qualifies the result carries a reason instead of a pick.
    """
    if len(observations) < min_n:
        return {"baseline_er": None, "n_total": len(observations), "ranked": [], "reason": Reason.INSUFFICIENT_DATA}

    baseline = _mean([er for _, er in observations])
    if baseline <= 0:
        return {"baseline_er": round(baseline, ER_DP), "n_total": len(observations), "ranked": [], "reason": Reason.NO_ENGAGEMENT_SIGNAL}

    groups: dict[str, list[float]] = defaultdict(list)
    for key, er in observations:
        groups[key].append(er)

    ranked = []
    for key, values in groups.items():
        if len(values) < min_n:
            continue
        item = {"key": key, **_summarize(values, baseline, k_shrink)}
        ranked.append(item)

    ranked.sort(key=lambda d: d["shrunk_score"], reverse=True)
    if top_k is not None:
        ranked = ranked[:top_k]

    return {
        "baseline_er": round(baseline, ER_DP),
        "n_total": len(observations),
        "ranked": ranked,
        "reason": None if ranked else Reason.INSUFFICIENT_DATA,
    }


def recommend_hashtags(
    posts: list[tuple[str | None, float]],
    *,
    min_n: int = CONF_MIN_N,
    top_k: int | None = 10,
    k_shrink: float = SHRINKAGE_K,
) -> dict:
    """Best hashtags by engagement lift. ``posts`` is ``(text, engagement_rate)``.

    Each post contributes its engagement rate to every unique hashtag it uses, so a
    hashtag's ``n`` is the number of posts that used it. Ranking and evidence then
    follow ``rank_categories``.
    """
    observations: list[tuple[str, float]] = []
    for text, er in posts:
        for tag in extract_hashtags(text):
            observations.append((tag, er))
    if not observations:
        return {"baseline_er": None, "n_total": 0, "ranked": [], "reason": Reason.NO_HASHTAGS}
    return rank_categories(observations, min_n=min_n, top_k=top_k, k_shrink=k_shrink)


def recommend_best_time(
    observations: list[tuple[int, int, float]],
    *,
    min_n: int = CONF_MIN_N,
    top_k: int = 5,
    k_shrink: float = SHRINKAGE_K,
) -> dict:
    """Best day/hour slots to post, plus day and hour marginals, all with evidence.

    ``observations`` is a list of ``(day_of_week, hour, engagement_rate)`` where
    day_of_week is 0=Monday..6=Sunday and hour is 0..23 in the display timezone.
    Cells are ranked by a shrinkage-adjusted mean so a thin slot cannot win on a
    single lucky post. Day-of-week and hour marginals aggregate more data per
    bucket and are the more robust guidance when cells are sparse.
    """
    if len(observations) < min_n:
        return {"baseline_er": None, "n_total": len(observations), "top_cells": [], "by_day": [], "by_hour": [], "reason": Reason.INSUFFICIENT_DATA}

    baseline = _mean([er for _, _, er in observations])
    if baseline <= 0:
        return {"baseline_er": round(baseline, ER_DP), "n_total": len(observations), "top_cells": [], "by_day": [], "by_hour": [], "reason": Reason.NO_ENGAGEMENT_SIGNAL}

    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    by_day: dict[int, list[float]] = defaultdict(list)
    by_hour: dict[int, list[float]] = defaultdict(list)
    for dow, hour, er in observations:
        cells[(dow, hour)].append(er)
        by_day[dow].append(er)
        by_hour[hour].append(er)

    top_cells = []
    for (dow, hour), values in cells.items():
        if len(values) < min_n:
            continue
        top_cells.append(
            {"day_of_week": dow, "day": DAY_NAMES[dow], "hour": hour, **_summarize(values, baseline, k_shrink)}
        )
    top_cells.sort(key=lambda d: d["shrunk_score"], reverse=True)
    top_cells = top_cells[:top_k]

    day_rows = [
        {"day_of_week": d, "day": DAY_NAMES[d], **_summarize(v, baseline, k_shrink)}
        for d, v in sorted(by_day.items())
    ]
    hour_rows = [
        {"hour": h, **_summarize(v, baseline, k_shrink)} for h, v in sorted(by_hour.items())
    ]

    return {
        "baseline_er": round(baseline, ER_DP),
        "n_total": len(observations),
        "top_cells": top_cells,
        "by_day": sorted(day_rows, key=lambda d: d["shrunk_score"], reverse=True),
        "by_hour": sorted(hour_rows, key=lambda d: d["shrunk_score"], reverse=True),
        "reason": None if top_cells else Reason.INSUFFICIENT_DATA,
    }
