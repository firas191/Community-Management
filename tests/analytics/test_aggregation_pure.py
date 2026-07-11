"""Hand-computed aggregation fixtures (brief Sections 8.3, 8.4). No database."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.analytics import aggregation as agg
from app.analytics.kpi import Reason

TZ = "Africa/Tunis"  # UTC+1 year-round


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_sum_timeseries_fills_gaps_with_zeros():
    df = _df(
        [
            {"published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc), "v": 5},
            {"published_at": datetime(2026, 7, 1, 12, tzinfo=timezone.utc), "v": 15},
            {"published_at": datetime(2026, 7, 3, 10, tzinfo=timezone.utc), "v": 10},
        ]
    )
    ts = agg.sum_timeseries(df, "v", "published_at", "day", TZ, name="likes")
    # 07-01 -> 20, 07-02 -> 0 (gap filled), 07-03 -> 10.
    assert ts.labels == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert ts.series[0] == {"name": "likes", "data": [20.0, 0.0, 10.0]}


def test_engagement_rate_timeseries_pools_numerator_and_denominator():
    df = _df(
        [
            {"published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc), "engagement": 60, "reach": 400},
            {"published_at": datetime(2026, 7, 1, 12, tzinfo=timezone.utc), "engagement": 40, "reach": 600},
            {"published_at": datetime(2026, 7, 3, 10, tzinfo=timezone.utc), "engagement": 30, "reach": 600},
        ]
    )
    ts = agg.engagement_rate_timeseries(df, "published_at", "day", TZ)
    # day1: (60+40)/(400+600)*100 = 10.0 ; day2 gap -> 0 ; day3: 30/600*100 = 5.0
    assert ts.labels == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert ts.series[0]["data"] == [10.0, 0.0, 5.0]


def test_weekly_buckets_gap_fill_stay_aligned():
    # Regression: weekly gap-fill must reindex on Periods, not date_range, or the
    # anchor mismatch drops every real bucket to zero. Two posts three weeks apart.
    df = _df(
        [
            {"published_at": datetime(2026, 6, 15, 10, tzinfo=timezone.utc), "engagement": 100, "reach": 1000},
            {"published_at": datetime(2026, 7, 6, 10, tzinfo=timezone.utc), "engagement": 60, "reach": 600},
        ]
    )
    ts = agg.engagement_rate_timeseries(df, "published_at", "week", TZ)
    # Real weeks keep their real rate (10.0 and 10.0); the two gap weeks are 0.
    assert ts.series[0]["data"][0] == 10.0
    assert ts.series[0]["data"][-1] == 10.0
    assert ts.series[0]["data"].count(0.0) == 2  # exactly the two empty middle weeks
    assert ts.labels[0] == "2026-06-15"  # Monday-anchored ISO week label


def test_monthly_sum_buckets():
    df = _df(
        [
            {"published_at": datetime(2026, 5, 20, tzinfo=timezone.utc), "v": 3},
            {"published_at": datetime(2026, 7, 2, tzinfo=timezone.utc), "v": 7},
        ]
    )
    ts = agg.sum_timeseries(df, "v", "published_at", "month", TZ)
    # May=3, June=0 (gap), July=7.
    assert ts.labels == ["2026-05", "2026-06", "2026-07"]
    assert ts.series[0]["data"] == [3.0, 0.0, 7.0]


def test_engagement_rate_timeseries_zero_reach_bucket_is_zero_not_error():
    df = _df([{"published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc), "engagement": 50, "reach": 0}])
    ts = agg.engagement_rate_timeseries(df, "published_at", "day", TZ)
    assert ts.series[0]["data"] == [0.0]


def test_rolling_mean_leading_nones_then_trailing_average():
    assert agg.rolling_mean([10, 20, 30, 40], 2) == [None, 15.0, 25.0, 35.0]
    # window 1 is a no-op passthrough.
    assert agg.rolling_mean([1, 2, 3], 1) == [1, 2, 3]


def test_zscore_hand_computed():
    # baseline [8,10,12]: mean 10, sample std 2. (13-10)/2 = 1.5.
    assert agg.zscore(13, [8, 10, 12]).value == 1.5
    assert agg.zscore(7, [8, 10, 12]).value == -1.5


def test_zscore_guards():
    assert agg.zscore(10, [10]).reason == Reason.INSUFFICIENT_DATA
    assert agg.zscore(10, [5, 5, 5]).reason == Reason.NON_POSITIVE_DENOMINATOR
    assert agg.zscore(None, [1, 2, 3]).reason == Reason.INSUFFICIENT_DATA


def test_unknown_granularity_raises():
    df = _df([{"published_at": datetime(2026, 7, 1, tzinfo=timezone.utc), "v": 1}])
    with pytest.raises(ValueError):
        agg.sum_timeseries(df, "v", "published_at", "fortnight", TZ)


def test_empty_dataframe_returns_empty_series():
    empty = pd.DataFrame(columns=["published_at", "v"])
    ts = agg.sum_timeseries(empty, "v", "published_at", "day", TZ)
    assert ts.labels == [] and ts.series == []
