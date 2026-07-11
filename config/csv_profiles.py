"""CSV column-mapping profiles for the importer (brief Sections 6.1, 7).

A "profile" maps the messy, human-facing column headers of an official export
to our canonical field names. Meta renames these headers across export versions
and locales, so mappings live here as data, not in importer logic.

Each profile declares:
  - id:            stable profile key requested by the API / importer
  - source:        human label of the export it targets
  - datetime_fmt:  strptime format if timestamps are not ISO (None = let pandas infer)
  - column_map:    { canonical_field: [candidate header, alternate header, ...] }
                   The importer picks the first candidate present in the file.
  - required:      canonical fields that must resolve or the import is rejected

Canonical post fields consumed by the normalizer:
  external_id, published_at, content_type, text_content, permalink,
  likes, comments_count, shares, saves, reach, impressions, video_views, clicks,
  account_external_id, account_handle, account_name

Reach/impressions are owner-private on public sources; when a header is absent
the field resolves to None and the KPI layer returns null-with-reason. Never 0.
"""

from __future__ import annotations

from typing import Any

# Meta Business Suite post-level performance export.
# Headers below cover the common English export plus known alternates. Adjust the
# candidate lists against a real file; the importer logs unmapped headers so gaps
# surface immediately (see brief note: "column mapping profiles per export type").
META_BUSINESS_SUITE_POSTS: dict[str, Any] = {
    "id": "meta_business_suite_posts",
    "source": "Meta Business Suite - post performance export",
    "datetime_fmt": None,
    "column_map": {
        "external_id": ["Post ID", "post_id", "Publication ID"],
        "account_external_id": ["Page ID", "page_id", "Account ID"],
        "account_handle": ["Page username", "Username"],
        "account_name": ["Page name", "page_name", "Account name"],
        "published_at": ["Publish time", "Time", "Date", "Publication time"],
        "content_type": ["Post type", "Type", "Media type"],
        "text_content": ["Title", "Description", "Message", "Caption"],
        "permalink": ["Permalink", "Link", "Post link", "URL"],
        "likes": ["Reactions", "Likes", "Like reactions", "Total reactions"],
        "comments_count": ["Comments", "Comment count"],
        "shares": ["Shares", "Share count"],
        "saves": ["Saves", "Saved"],
        "reach": ["Reach", "Post reach", "Accounts reached"],
        "impressions": ["Impressions", "Post impressions"],
        "video_views": ["Video views", "3-second video views", "Plays"],
        "clicks": ["Link clicks", "Clicks", "Post clicks"],
    },
    "required": ["external_id", "published_at"],
    "platform": "facebook",
}

# Instagram export shares most Business Suite headers but exposes saves and
# uses IG media-type vocabulary. Modeled as its own profile for clarity.
META_BUSINESS_SUITE_IG_POSTS: dict[str, Any] = {
    "id": "meta_business_suite_ig_posts",
    "source": "Meta Business Suite - Instagram post export",
    "datetime_fmt": None,
    "column_map": {
        "external_id": ["Post ID", "Media ID", "id"],
        "account_external_id": ["Account ID", "IG User ID", "Page ID"],
        "account_handle": ["Username", "Handle"],
        "account_name": ["Account name", "Name"],
        "published_at": ["Publish time", "Time", "Timestamp"],
        "content_type": ["Media type", "Post type", "Type"],
        "text_content": ["Caption", "Description", "Title"],
        "permalink": ["Permalink", "Link", "URL"],
        "likes": ["Likes", "Reactions"],
        "comments_count": ["Comments", "Comment count"],
        "shares": ["Shares"],
        "saves": ["Saves", "Saved"],
        "reach": ["Reach", "Accounts reached"],
        "impressions": ["Impressions"],
        "video_views": ["Video views", "Plays", "Reels plays"],
        "clicks": ["Website clicks", "Link clicks", "Clicks"],
    },
    "required": ["external_id", "published_at"],
    "platform": "instagram",
}

# Generic Kaggle engagement dataset profile for KPI/forecasting volume backtests
# (brief Section 6.1.1). Only fields KPI code needs; unknown columns are ignored.
KAGGLE_ENGAGEMENT_GENERIC: dict[str, Any] = {
    "id": "kaggle_engagement_generic",
    "source": "Kaggle social media engagement dataset (backtesting only)",
    "datetime_fmt": None,
    "column_map": {
        "external_id": ["post_id", "id", "Post ID"],
        "account_external_id": ["account_id", "user_id", "page_id"],
        "account_handle": ["username", "handle", "account"],
        "account_name": ["account_name", "name"],
        "published_at": ["timestamp", "date", "published_at", "post_time"],
        "content_type": ["type", "media_type", "content_type"],
        "text_content": ["text", "caption", "content", "message"],
        "permalink": ["url", "permalink", "link"],
        "likes": ["likes", "like_count", "reactions"],
        "comments_count": ["comments", "comment_count", "num_comments"],
        "shares": ["shares", "share_count", "retweets"],
        "saves": ["saves", "bookmarks"],
        "reach": ["reach"],
        "impressions": ["impressions", "views"],
        "video_views": ["video_views", "plays"],
        "clicks": ["clicks", "link_clicks"],
    },
    "required": ["published_at"],
    "platform": None,  # resolved from a request param or defaulted at import
}

PROFILES: dict[str, dict[str, Any]] = {
    p["id"]: p
    for p in (
        META_BUSINESS_SUITE_POSTS,
        META_BUSINESS_SUITE_IG_POSTS,
        KAGGLE_ENGAGEMENT_GENERIC,
    )
}

DEFAULT_PROFILE_ID = "meta_business_suite_posts"


def get_profile(profile_id: str | None) -> dict[str, Any]:
    """Return a profile by id, or the default. Raise on unknown id."""
    if profile_id is None:
        return PROFILES[DEFAULT_PROFILE_ID]
    if profile_id not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"Unknown CSV profile '{profile_id}'. Known profiles: {known}")
    return PROFILES[profile_id]
