"""Pure recommendation-engine tests (brief Section 8.5). Hand-computed, no DB.

Each expected number is worked out by hand in the comments so the production math
is pinned to an independent calculation, not to itself.
"""

from __future__ import annotations

from app.analytics import recommend
from app.analytics.recommend import Reason


def test_confidence_tiers():
    assert recommend.confidence_for(8) == "high"
    assert recommend.confidence_for(20) == "high"
    assert recommend.confidence_for(7) == "medium"
    assert recommend.confidence_for(4) == "medium"
    assert recommend.confidence_for(3) == "low"
    assert recommend.confidence_for(2) == "low"
    assert recommend.confidence_for(1) is None
    assert recommend.confidence_for(0) is None


def test_lift():
    assert recommend.lift(6.0, 3.0) == 2.0
    assert recommend.lift(3.0, 3.0) == 1.0
    assert recommend.lift(1.5, 3.0) == 0.5
    assert recommend.lift(5.0, 0.0) is None  # non-positive baseline -> None


def test_shrunk_mean_pulls_small_groups_toward_baseline():
    # values=[10,10], baseline=2, k=5 -> (20 + 5*2)/(2+5) = 30/7 = 4.2857
    assert round(recommend.shrunk_mean([10.0, 10.0], 2.0, k=5.0), 4) == 4.2857
    # empty group returns the baseline unchanged
    assert recommend.shrunk_mean([], 2.0) == 2.0


def test_extract_hashtags_dedupes_lowercases_and_handles_unicode():
    assert recommend.extract_hashtags("Love #Tunisia and #tunisia #Foot!") == ["tunisia", "foot"]
    assert recommend.extract_hashtags(None) == []
    assert recommend.extract_hashtags("no tags here") == []
    assert recommend.extract_hashtags("#تونس test") == ["تونس"]


def test_rank_categories_shrinkage_ranks_and_reports_evidence():
    # video: [10,12] (n=2, mean 11); image: [2,2,2,2] (n=4, mean 2); carousel: [8] (n=1, dropped)
    # baseline = (10+12+2+2+2+2+8)/7 = 38/7 = 5.4286
    obs = [
        ("video", 10.0), ("video", 12.0),
        ("image", 2.0), ("image", 2.0), ("image", 2.0), ("image", 2.0),
        ("carousel", 8.0),
    ]
    out = recommend.rank_categories(obs)
    assert out["baseline_er"] == 5.4286
    assert out["n_total"] == 7
    keys = [r["key"] for r in out["ranked"]]
    assert keys == ["video", "image"]  # carousel dropped (n=1 < 2)

    video = out["ranked"][0]
    assert video["n"] == 2
    assert video["mean_er"] == 11.0
    # shrunk = (22 + 5*5.4286)/(2+5) = 49.1429/7 = 7.0204
    assert video["shrunk_score"] == 7.0204
    assert video["lift"] == 2.03  # 11 / 5.4286
    assert video["confidence"] == "low"

    image = out["ranked"][1]
    assert image["confidence"] == "medium"  # n=4
    assert image["lift"] == 0.37  # 2 / 5.4286


def test_rank_categories_insufficient_and_no_signal():
    assert recommend.rank_categories([]) == {
        "baseline_er": None, "n_total": 0, "ranked": [], "reason": Reason.INSUFFICIENT_DATA,
    }
    zero = recommend.rank_categories([("a", 0.0), ("b", 0.0)])
    assert zero["reason"] == Reason.NO_ENGAGEMENT_SIGNAL


def test_recommend_hashtags_from_posts():
    posts = [("#promo big sale", 10.0), ("#promo again", 12.0), ("#boring day", 1.0)]
    out = recommend.recommend_hashtags(posts)
    keys = [r["key"] for r in out["ranked"]]
    assert keys == ["promo"]  # boring used once (n=1) -> dropped
    assert out["ranked"][0]["n"] == 2
    assert out["ranked"][0]["mean_er"] == 11.0


def test_recommend_hashtags_none_present():
    out = recommend.recommend_hashtags([("no tags", 5.0), ("still none", 4.0)])
    assert out["reason"] == Reason.NO_HASHTAGS
    assert out["ranked"] == []


def test_recommend_best_time_cells_days_hours():
    # (dow, hour, er). Monday=0.
    # Mon 18h: [10,12] n=2 mean 11 ; Mon 9h: [2] n=1 (dropped cell) ; Tue 18h: [3,3] n=2 mean 3
    # baseline = (10+12+2+3+3)/5 = 6.0
    obs = [(0, 18, 10.0), (0, 18, 12.0), (0, 9, 2.0), (1, 18, 3.0), (1, 18, 3.0)]
    out = recommend.recommend_best_time(obs)
    assert out["baseline_er"] == 6.0
    assert out["n_total"] == 5
    assert out["reason"] is None

    top = out["top_cells"][0]
    assert top["day"] == "Monday" and top["day_of_week"] == 0 and top["hour"] == 18
    assert top["n"] == 2 and top["mean_er"] == 11.0
    # shrunk = (22 + 5*6)/(2+5) = 52/7 = 7.4286
    assert top["shrunk_score"] == 7.4286
    assert top["lift"] == 1.83  # 11/6
    assert top["confidence"] == "low"
    # the single-post Monday-9h cell is not surfaced
    assert all(not (c["day_of_week"] == 0 and c["hour"] == 9) for c in out["top_cells"])

    # marginals: Monday is the best day, 18h is the best hour
    assert out["by_day"][0]["day_of_week"] == 0
    assert out["by_hour"][0]["hour"] == 18


def test_recommend_best_time_insufficient():
    out = recommend.recommend_best_time([(0, 12, 5.0)])
    assert out["reason"] == Reason.INSUFFICIENT_DATA
    assert out["top_cells"] == []
