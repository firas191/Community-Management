"""Synthetic fixture generator (brief Section 6.1.5). DEV FIXTURES ONLY.

Seeded and reproducible. Statistically realistic: log-normal engagement,
day-of-week seasonality, platform-specific baselines. Every row it produces
carries is_synthetic=true, so the API can exclude it and it is never shown as
real (brief quality bar).

Comment text mixes French, English, Modern Standard Arabic, and Tunisian
Arabizi so the Week 3+ NLP pipeline has all four registers to work on.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ingestion.normalizer import normalize_and_store
from app.ingestion.records import (
    AccountRecord,
    CommentRecord,
    IngestionResult,
    MetricSnapshotRecord,
    PostRecord,
)

# Platform engagement baselines: (median_engagement, sigma, exposes_reach).
# Public YouTube hides reach, so its snapshots leave reach None (brief 6.1.1).
_PLATFORM_BASELINE = {
    "instagram": (220, 0.8, True),
    "facebook": (140, 0.9, True),
    "youtube": (900, 1.0, False),
}

_CONTENT_TYPES = {
    "instagram": ["photo", "carousel", "reel", "video"],
    "facebook": ["photo", "text", "link", "video"],
    "youtube": ["video", "short"],
}

# Day-of-week multipliers (Mon=0..Sun=6). Thursday/Sunday evenings run hot.
_DOW_MULT = [0.9, 0.95, 1.0, 1.15, 1.1, 0.85, 1.05]
_HASHTAG_POOL = ["#tunisie", "#promo", "#livraison", "#food", "#نجاح", "#offre", "#tunis"]

# Representative multilingual comments with a rough intended polarity.
_COMMENTS = [
    ("3ajbetni barcha el video, ya3tik sa7a", "aeb-latn"),  # Arabizi positive
    ("behi barcha, thanks", "aeb-latn"),
    ("el livraison m3atla yesser, mouch behi", "aeb-latn"),  # Arabizi negative
    ("Super produit, je recommande vivement", "fr"),
    ("Livraison trop lente, tres decu", "fr"),
    ("Great quality, will order again", "en"),
    ("Not worth the price honestly", "en"),
    ("منتج رائع شكرا لكم", "ar"),  # Arabic positive
    ("الخدمة سيئة جدا", "ar"),  # Arabic negative
    ("ok", "en"),
]


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def build_fixtures(
    seed: int = 42,
    n_days: int = 90,
    posts_per_account: int = 40,
) -> tuple[list[AccountRecord], list[PostRecord], list[MetricSnapshotRecord], list[CommentRecord]]:
    """Return reproducible synthetic records. Same seed -> identical output."""
    rng = _rng(seed)
    now = datetime.now(timezone.utc)

    accounts = [
        AccountRecord(platform="instagram", external_id="syn_ig_1", handle="cm_demo_ig",
                      display_name="Community Management Demo IG", followers_count=8200),
        AccountRecord(platform="facebook", external_id="syn_fb_1", handle="cm_demo_fb",
                      display_name="Community Management Demo FB", followers_count=15400),
        AccountRecord(platform="youtube", external_id="syn_yt_1", handle="cm_demo_yt",
                      display_name="Community Management Demo YT", followers_count=3100),
    ]

    posts: list[PostRecord] = []
    metrics: list[MetricSnapshotRecord] = []
    comments: list[CommentRecord] = []

    for acc in accounts:
        median, sigma, exposes_reach = _PLATFORM_BASELINE[acc.platform]
        ctypes = _CONTENT_TYPES[acc.platform]
        for i in range(posts_per_account):
            day_offset = rng.uniform(0, n_days)
            published = now - timedelta(
                days=day_offset, hours=rng.uniform(0, 23), minutes=rng.uniform(0, 59)
            )
            dow_mult = _DOW_MULT[published.weekday()]
            hour_mult = 1.2 if 18 <= published.hour <= 21 else 1.0
            base = rng.lognormvariate(0, sigma) * median * dow_mult * hour_mult

            likes = max(0, int(base))
            comments_n = max(0, int(base * rng.uniform(0.03, 0.09)))
            shares = max(0, int(base * rng.uniform(0.01, 0.04)))
            saves = max(0, int(base * rng.uniform(0.0, 0.05))) if acc.platform == "instagram" else 0
            reach = int(base / rng.uniform(0.02, 0.06)) if exposes_reach else None
            impressions = int(reach * rng.uniform(1.1, 1.6)) if reach is not None else None
            video_views = int(base * rng.uniform(2, 6)) if "video" in ctypes else None

            tags = rng.sample(_HASHTAG_POOL, k=rng.randint(0, 3))
            ext_id = f"{acc.external_id}_p{i}"
            posts.append(
                PostRecord(
                    account_external_id=acc.external_id,
                    platform=acc.platform,
                    external_id=ext_id,
                    published_at=published,
                    content_type=rng.choice(ctypes),
                    text_content=f"Demo post {i} " + " ".join(tags),
                    permalink=f"https://example.com/{acc.external_id}/{i}",
                    media_count=rng.randint(1, 5),
                    is_synthetic=True,
                    hashtags=[t.lower() for t in tags] or None,
                )
            )
            metrics.append(
                MetricSnapshotRecord(
                    post_external_id=ext_id,
                    account_external_id=acc.external_id,
                    platform=acc.platform,
                    captured_at=now,
                    likes=likes,
                    comments_count=comments_n,
                    shares=shares,
                    saves=saves,
                    reach=reach,
                    impressions=impressions,
                    video_views=video_views,
                    clicks=int(base * rng.uniform(0.0, 0.03)) if reach is not None else None,
                )
            )
            for j in range(min(comments_n, 4)):
                text, _lang = rng.choice(_COMMENTS)
                comments.append(
                    CommentRecord(
                        post_external_id=ext_id,
                        account_external_id=acc.external_id,
                        platform=acc.platform,
                        external_id=f"{ext_id}_c{j}",
                        text_content=text,
                        published_at=published + timedelta(hours=rng.uniform(0.1, 48)),
                        like_count=rng.randint(0, 12),
                        author_external_id=f"user_{rng.randint(1, 500)}",
                        is_synthetic=True,
                    )
                )

    return accounts, posts, metrics, comments


def seed(session: Session, seed_value: int = 42) -> IngestionResult:
    """Generate fixtures and store them idempotently. Caller controls the transaction."""
    accounts, posts, metrics, comments = build_fixtures(seed=seed_value)
    return normalize_and_store(
        session,
        source="synthetic",
        accounts=accounts,
        posts=posts,
        metrics=metrics,
        comments=comments,
    )
