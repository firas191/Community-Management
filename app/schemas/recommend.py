"""Recommendation response schemas (brief Sections 8.5, 12).

Every recommendation item carries its evidence (n, lift, confidence) so the
dashboard can justify each pick. `reason` is populated instead of a ranking when
there is not enough data, mirroring the KPI engine's null-with-reason rule.
"""

from __future__ import annotations

from pydantic import BaseModel


class Evidence(BaseModel):
    n: int
    mean_er: float
    shrunk_score: float
    lift: float | None = None
    confidence: str | None = None


class CategoryItem(Evidence):
    key: str


class CellItem(Evidence):
    day_of_week: int
    day: str
    hour: int


class DayItem(Evidence):
    day_of_week: int
    day: str


class HourItem(Evidence):
    hour: int


class _Envelope(BaseModel):
    account_id: int
    window: str
    kind: str
    engagement_rate_basis: str
    generated_at: str
    baseline_er: float | None = None
    n_total: int
    reason: str | None = None


class BestTimeResponse(_Envelope):
    timezone: str
    top_cells: list[CellItem]
    by_day: list[DayItem]
    by_hour: list[HourItem]


class CategoryResponse(_Envelope):
    ranked: list[CategoryItem]


class AllRecommendationsResponse(BaseModel):
    account_id: int
    handle: str | None = None
    platform: str | None = None
    window: str
    generated_at: str
    best_time: BestTimeResponse
    content_type: CategoryResponse
    hashtags: CategoryResponse
