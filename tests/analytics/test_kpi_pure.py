"""Hand-computed KPI fixtures (brief Sections 8, 13).

Every expected value here is worked out by hand in the comments so the formulas
can never silently drift. These tests need no database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analytics import kpi
from app.analytics.kpi import Metric, PostMetrics, Reason

# A fully-populated post: L=80, C=10, S=5, Sv=5 -> engagement = 100.
FULL = PostMetrics(
    likes=80, comments=10, shares=5, saves=5,
    reach=1000, impressions=1600, video_views=400, clicks=20, followers=2000,
)


def test_engagement_sum():
    assert FULL.engagement == 100


@pytest.mark.parametrize(
    "func,expected",
    [
        (kpi.engagement_rate_by_reach, 10.0),        # 100/1000*100
        (kpi.engagement_rate_by_followers, 5.0),     # 100/2000*100
        (kpi.engagement_rate_by_impressions, 6.25),  # 100/1600*100
        (kpi.amplification_rate, 0.25),              # 5/2000*100
        (kpi.applause_rate, 4.0),                    # 80/2000*100
        (kpi.conversation_rate, 0.5),                # 10/2000*100
        (kpi.save_rate, 0.5),                        # 5/1000*100
        (kpi.virality_rate, 0.5),                    # 5/1000*100
        (kpi.click_through_rate, 1.25),              # 20/1600*100
        (kpi.video_view_rate, 40.0),                 # 400/1000*100
    ],
)
def test_post_kpis_hand_computed(func, expected):
    result = func(FULL)
    assert result.value == expected
    assert result.reason is None


def test_missing_reach_is_null_with_reason_not_zero():
    pm = PostMetrics(likes=10, reach=None, followers=500)
    err = kpi.engagement_rate_by_reach(pm)
    assert err.value is None
    assert err.reason == Reason.REACH_UNAVAILABLE


def test_zero_denominator_is_null_not_divide_error():
    pm = PostMetrics(likes=10, reach=0)
    err = kpi.engagement_rate_by_reach(pm)
    assert err.value is None
    assert err.reason == Reason.NON_POSITIVE_DENOMINATOR


def test_zero_numerator_over_positive_denominator_is_truthful_zero():
    # A real zero: no engagement over real reach. Must be 0.0, never null.
    pm = PostMetrics(likes=0, comments=0, shares=0, saves=0, reach=1000)
    err = kpi.engagement_rate_by_reach(pm)
    assert err.value == 0.0
    assert err.reason is None


def test_ctr_and_vvr_specific_missing_reasons():
    assert kpi.click_through_rate(PostMetrics(impressions=100)).reason == Reason.CLICKS_UNAVAILABLE
    assert kpi.video_view_rate(PostMetrics(reach=100)).reason == Reason.VIDEO_VIEWS_UNAVAILABLE


def test_primary_engagement_rate_prefers_reach_then_followers():
    with_reach = PostMetrics(likes=100, reach=1000, followers=5000)
    metric, basis = kpi.primary_engagement_rate(with_reach)
    assert basis == "err" and metric.value == 10.0

    no_reach = PostMetrics(likes=100, reach=None, followers=5000)
    metric, basis = kpi.primary_engagement_rate(no_reach)
    assert basis == "erf" and metric.value == 2.0  # 100/5000*100

    neither = PostMetrics(likes=100, reach=None, followers=None)
    metric, basis = kpi.primary_engagement_rate(neither)
    assert basis == "none" and metric.value is None


def test_engagement_velocity():
    assert kpi.engagement_velocity(30, 100).value == 0.3
    assert kpi.engagement_velocity(None, 100).reason == Reason.INSUFFICIENT_SNAPSHOTS
    assert kpi.engagement_velocity(30, 0).reason == Reason.NON_POSITIVE_DENOMINATOR


def test_compute_post_kpis_returns_all_ten():
    kpis = kpi.compute_post_kpis(FULL)
    assert len(kpis) == 10
    assert all(isinstance(v, Metric) for v in kpis.values())


# --- Account-level KPIs ---
def test_mean_and_median():
    assert kpi.mean_metric([10.0, 20.0, 30.0]).value == 20.0
    assert kpi.median_metric([10.0, 20.0, 30.0]).value == 20.0
    assert kpi.median_metric([10.0, 20.0, 30.0, 40.0]).value == 25.0
    assert kpi.mean_metric([]).reason == Reason.INSUFFICIENT_DATA


def test_posting_frequency_per_week():
    # 10 posts over 30 days = 10 / (30/7) = 2.33 posts/week.
    assert kpi.posting_frequency_per_week(10, 30).value == 2.33
    assert kpi.posting_frequency_per_week(5, 0).reason == Reason.NON_POSITIVE_DENOMINATOR


def test_posting_consistency_stddev_of_gaps():
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    times = [base, base + timedelta(hours=24), base + timedelta(hours=48), base + timedelta(hours=96)]
    # gaps in hours = [24, 24, 48]; sample stdev ~ 13.86.
    result = kpi.posting_consistency(times)
    assert result.value == pytest.approx(13.86, abs=0.01)
    assert kpi.posting_consistency(times[:2]).reason == Reason.INSUFFICIENT_DATA


def test_follower_growth_and_net_change():
    assert kpi.follower_growth_rate(1000, 1100).value == 10.0
    assert kpi.net_follower_change(1000, 1100).value == 100.0
    assert kpi.follower_growth_rate(0, 100).reason == Reason.NON_POSITIVE_DENOMINATOR
    assert kpi.follower_growth_rate(None, 100).reason == Reason.INSUFFICIENT_DATA


def test_delta_pct():
    assert kpi.delta_pct(120, 100).value == 20.0
    assert kpi.delta_pct(80, 100).value == -20.0
    assert kpi.delta_pct(100, 0).reason == Reason.NON_POSITIVE_DENOMINATOR
    assert kpi.delta_pct(None, 100).reason == Reason.INSUFFICIENT_DATA
