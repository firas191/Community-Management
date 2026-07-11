"""Temporal aggregation and cross-platform normalization (brief Sections 8.3, 8.4).

Pure pandas. A DataFrame goes in, chart-ready structures come out. No database
access here. Timestamps arrive tz-aware in UTC (storage tz) and are bucketed in
the display timezone (Africa/Tunis) so a "Thursday evening" bucket matches the
Tunisian market, per the brief timezone policy.

Bucketing works entirely in pandas Period space and gap-fills by reindexing onto
a period_range built from the same periods. Mixing to_period() with date_range()
misaligns weekly/monthly buckets (different anchors), so this module never does
that: buckets and the gap-fill range are both Periods.

Chart contract (brief Section 7.3): every timeseries is
`{"labels": [...], "series": [{"name": ..., "data": [...]}]}` and gaps are filled
with explicit zeros so a missing bucket never renders as a break in the line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.analytics.kpi import Metric, Reason

# pandas Period aliases. Week ends Sunday so start_time is Monday (ISO weeks).
_PERIOD_ALIAS: dict[str, str] = {"hour": "h", "day": "D", "week": "W-SUN", "month": "M"}
_LABEL_FMT: dict[str, str] = {
    "hour": "%Y-%m-%d %H:00",
    "day": "%Y-%m-%d",
    "week": "%Y-%m-%d",
    "month": "%Y-%m",
}
VALID_GRANULARITIES = tuple(_PERIOD_ALIAS)


@dataclass(slots=True)
class TimeSeries:
    labels: list[str] = field(default_factory=list)
    series: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"labels": self.labels, "series": self.series}


def _alias(granularity: str) -> str:
    if granularity not in _PERIOD_ALIAS:
        raise ValueError(f"Unknown granularity '{granularity}'. Use one of {list(_PERIOD_ALIAS)}.")
    return _PERIOD_ALIAS[granularity]


def _bucket_period(published: pd.Series, granularity: str, tz: str) -> pd.Series:
    """Convert timestamps to display-tz Periods (the bucket each row falls in)."""
    local = pd.to_datetime(published, utc=True).dt.tz_convert(ZoneInfo(tz)).dt.tz_localize(None)
    return local.dt.to_period(_alias(granularity))


def _reindex_full(series: pd.Series, alias: str, fill: float) -> pd.Series:
    """Fill gaps by reindexing onto a contiguous period_range of the same freq."""
    if len(series) <= 1:
        return series
    full = pd.period_range(series.index.min(), series.index.max(), freq=alias)
    return series.reindex(full, fill_value=fill)


def _labels(index: pd.PeriodIndex, granularity: str) -> list[str]:
    return [p.start_time.strftime(_LABEL_FMT[granularity]) for p in index]


def sum_timeseries(
    df: pd.DataFrame,
    value_col: str,
    published_col: str,
    granularity: str,
    tz: str,
    *,
    name: str | None = None,
    fill_gaps: bool = True,
) -> TimeSeries:
    """Sum `value_col` into time buckets, gap-filled with zeros."""
    if df.empty:
        return TimeSeries()
    alias = _alias(granularity)
    work = pd.DataFrame(
        {"bucket": _bucket_period(df[published_col], granularity, tz), "v": df[value_col].astype(float)}
    )
    grouped = work.groupby("bucket")["v"].sum().sort_index()
    if fill_gaps:
        grouped = _reindex_full(grouped, alias, 0.0)
    data = [round(float(v), 2) for v in grouped.to_numpy()]
    return TimeSeries(labels=_labels(grouped.index, granularity), series=[{"name": name or value_col, "data": data}])


def engagement_rate_timeseries(
    df: pd.DataFrame,
    published_col: str,
    granularity: str,
    tz: str,
    *,
    engagement_col: str = "engagement",
    denom_col: str = "reach",
    name: str = "engagement_rate",
    fill_gaps: bool = True,
) -> TimeSeries:
    """Bucket-level engagement rate = sum(engagement) / sum(denominator) * 100.

    Rate is computed on the summed numerator and denominator per bucket, which is
    the correct pooled rate (never a mean of per-post ratios). A bucket whose
    denominator is zero or missing renders as 0.0.
    """
    if df.empty:
        return TimeSeries()
    alias = _alias(granularity)
    work = pd.DataFrame(
        {
            "bucket": _bucket_period(df[published_col], granularity, tz),
            "eng": df[engagement_col].astype(float),
            "den": pd.to_numeric(df[denom_col], errors="coerce"),
        }
    )
    agg = work.groupby("bucket").agg(eng=("eng", "sum"), den=("den", "sum")).sort_index()
    eng = agg["eng"].to_numpy(dtype=float)
    den = agg["den"].to_numpy(dtype=float)
    # Safe divide: buckets with a zero/NaN denominator stay 0.0, no warning raised.
    rate = np.divide(eng, den, out=np.zeros_like(eng), where=den > 0) * 100.0
    ts = pd.Series(rate, index=agg.index)
    if fill_gaps:
        ts = _reindex_full(ts, alias, 0.0)
    data = [round(float(v), 2) for v in ts.to_numpy()]
    return TimeSeries(labels=_labels(ts.index, granularity), series=[{"name": name, "data": data}])


def rolling_mean(data: list[float], window: int) -> list[float | None]:
    """Trailing rolling mean (brief Section 8.3). First (window-1) points are None."""
    if window <= 1:
        return list(data)
    s = pd.Series(data, dtype="float64").rolling(window=window, min_periods=window).mean()
    return [None if pd.isna(v) else round(float(v), 2) for v in s]


def zscore(current: float | None, baseline: list[float]) -> Metric:
    """Standard score of `current` against its own trailing baseline (brief 8.4).

    "Instagram is +1.3 sigma vs its own 90-day history" is the statistically
    correct answer to "which platform is doing better", not a raw cross-platform
    comparison. Needs at least two baseline points and non-zero variance.
    """
    if current is None:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    clean = [float(v) for v in baseline if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if len(clean) < 2:
        return Metric(None, Reason.INSUFFICIENT_DATA)
    mu = float(np.mean(clean))
    sigma = float(np.std(clean, ddof=1))
    if sigma == 0:
        return Metric(None, Reason.NON_POSITIVE_DENOMINATOR)
    return Metric(round((current - mu) / sigma, 2))
