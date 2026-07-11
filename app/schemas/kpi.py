"""KPI request/response schemas (brief Section 12).

Every KPI is a `MetricOut`: a value or an explicit null with a stable reason. The
dashboard renders `reason` when `value` is null, so a hidden platform field reads
as "not exposed", never as a misleading zero.
"""

from __future__ import annotations

from pydantic import BaseModel


class MetricOut(BaseModel):
    value: float | None = None
    reason: str | None = None


class FollowersOut(BaseModel):
    value: int | None = None
    basis: str  # 'snapshot' | 'account_latest' | 'unavailable'


class PostRef(BaseModel):
    post_id: int
    engagement_rate: float | None = None
    permalink: str | None = None


class OverviewDeltas(BaseModel):
    total_engagement_pct: MetricOut
    avg_engagement_rate_pct: MetricOut
    n_posts_pct: MetricOut


class KPIOverviewResponse(BaseModel):
    account_id: int
    handle: str | None = None
    platform: str | None = None
    window: str
    generated_at: str
    engagement_rate_basis: str  # 'err' | 'erf' | 'none'
    followers: FollowersOut
    n_posts: int
    posting_frequency_per_week: MetricOut
    total_engagement: int
    avg_engagement_rate: MetricOut
    median_engagement_rate: MetricOut
    posting_consistency_hours: MetricOut
    deltas: OverviewDeltas
    best_post: PostRef | None = None
    worst_post: PostRef | None = None


class TimeSeriesResponse(BaseModel):
    account_id: int
    metric: str
    granularity: str
    labels: list[str]
    series: list[dict]  # [{"name": str, "data": [float|None, ...]}]


class PlatformRow(BaseModel):
    platform: str
    n_posts: int
    engagement_rate_basis: str
    avg_engagement_rate: MetricOut
    median_engagement_rate: MetricOut
    total_engagement: int
    zscore_vs_90d_baseline: MetricOut


class ByPlatformResponse(BaseModel):
    window: str
    generated_at: str
    note: str
    platforms: list[PlatformRow]


class TopPostItem(BaseModel):
    post_id: int
    published_at: str
    content_type: str | None = None
    permalink: str | None = None
    score: float
    score_basis: str
    engagement: int
    kpis: dict[str, MetricOut]


class TopPostsResponse(BaseModel):
    account_id: int
    metric: str
    limit: int
    count: int
    posts: list[TopPostItem]
