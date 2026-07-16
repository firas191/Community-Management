"""Meta Graph API connector for Facebook Pages (brief Sections 6.1, 7.1).

Pulls a page's published posts, per-post engagement and insights, and comments.
Insight metric names change between Graph API versions, so they are isolated in
``INSIGHT_METRICS`` (brief note: keep them behind a mapping dict). Missing insights
(a post without reach data, or insufficient permissions) leave the field null,
never 0, so the KPI layer stays honest.

Offline-testable via an injected ``get`` function, like the YouTube connector.
Instagram Business media uses different endpoints; it extends this same pattern
and lands as a follow-up.
"""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.ingestion import http
from app.ingestion.parse import now_utc, parse_iso_dt, to_int
from app.ingestion.records import (
    AccountRecord,
    CommentRecord,
    MetricSnapshotRecord,
    PostRecord,
    RawEventRecord,
)

log = get_logger("ingestion.meta")

DEFAULT_API_VERSION = "v21.0"
DEFAULT_POST_LIMIT = 25

# Insight metric names, isolated so a Graph version bump is a one-line change.
INSIGHT_METRICS = {
    "impressions": "post_impressions",
    "reach": "post_impressions_unique",
    "clicks": "post_clicks",
}

# Facebook status_type -> our canonical content type. The normalizer maps further.
_FB_TYPE = {
    "added_photos": "photo",
    "added_video": "video",
    "shared_story": "link",
    "mobile_status_update": "text",
    "published_story": "text",
    "created_note": "text",
}


class MetaConnector:
    source = "facebook"

    def __init__(
        self,
        access_token: str,
        page_ids: list[str],
        *,
        get: http.GetJson | None = None,
        api_version: str = DEFAULT_API_VERSION,
        post_limit: int = DEFAULT_POST_LIMIT,
    ) -> None:
        self.access_token = access_token
        self.page_ids = page_ids
        self._get = get or http.get_json
        self.base = f"https://graph.facebook.com/{api_version}"
        self.post_limit = post_limit
        self.raw_events: list[RawEventRecord] = []
        self._post_account: dict[str, str] = {}

    def _call(self, path: str, params: dict) -> dict:
        return self._get(f"{self.base}/{path}", params={**params, "access_token": self.access_token})

    def fetch_accounts(self) -> list[AccountRecord]:
        accounts: list[AccountRecord] = []
        for pid in self.page_ids:
            data = self._call(pid, {"fields": "name,username,followers_count,fan_count"})
            self.raw_events.append(RawEventRecord(self.source, "account", pid, data))
            followers = to_int(data.get("followers_count"))
            if followers is None:
                followers = to_int(data.get("fan_count"))
            accounts.append(
                AccountRecord(
                    platform="facebook",
                    external_id=pid,
                    handle=data.get("username"),
                    display_name=data.get("name"),
                    followers_count=followers,
                )
            )
        return accounts

    def fetch_posts(self, account_external_id: str, since: datetime) -> list[PostRecord]:
        data = self._call(
            f"{account_external_id}/published_posts",
            {
                "fields": "id,message,created_time,permalink_url,status_type",
                "limit": self.post_limit,
                "since": int(since.timestamp()),
            },
        )
        posts: list[PostRecord] = []
        for item in data.get("data", []):
            published = parse_iso_dt(item.get("created_time"))
            if published is None or published <= since:
                continue
            pid = item["id"]
            self._post_account[pid] = account_external_id
            self.raw_events.append(RawEventRecord(self.source, "post", pid, item))
            status = item.get("status_type")
            posts.append(
                PostRecord(
                    platform="facebook",
                    account_external_id=account_external_id,
                    external_id=pid,
                    published_at=published,
                    content_type=_FB_TYPE.get(status, status),
                    text_content=item.get("message"),
                    permalink=item.get("permalink_url"),
                )
            )
        return posts

    def fetch_metrics(self, post_external_ids: list[str]) -> list[MetricSnapshotRecord]:
        now = now_utc()
        metrics: list[MetricSnapshotRecord] = []
        for pid in post_external_ids:
            account = self._post_account.get(pid)
            if account is None:
                continue
            eng = self._call(pid, {"fields": "likes.summary(true),comments.summary(true),shares"})
            likes = to_int(eng.get("likes", {}).get("summary", {}).get("total_count")) or 0
            comments = to_int(eng.get("comments", {}).get("summary", {}).get("total_count")) or 0
            shares = to_int((eng.get("shares") or {}).get("count")) or 0

            reach = impressions = clicks = None
            try:
                ins = self._call(
                    f"{pid}/insights", {"metric": ",".join(INSIGHT_METRICS.values())}
                )
                values = {
                    row["name"]: (row.get("values") or [{}])[0].get("value")
                    for row in ins.get("data", [])
                }
                reach = to_int(values.get(INSIGHT_METRICS["reach"]))
                impressions = to_int(values.get(INSIGHT_METRICS["impressions"]))
                clicks = to_int(values.get(INSIGHT_METRICS["clicks"]))
            except http.HTTPError as exc:
                log.info("insights_unavailable", post=pid, detail=str(exc)[:120])

            self.raw_events.append(RawEventRecord(self.source, "metric", pid, {"engagement": eng}))
            metrics.append(
                MetricSnapshotRecord(
                    post_external_id=pid,
                    account_external_id=account,
                    platform="facebook",
                    captured_at=now,
                    likes=likes,
                    comments_count=comments,
                    shares=shares,
                    saves=0,
                    reach=reach,
                    impressions=impressions,
                    video_views=None,
                    clicks=clicks,
                )
            )
        return metrics

    def fetch_comments(self, post_external_id: str, since: datetime) -> list[CommentRecord]:
        account = self._post_account.get(post_external_id, "")
        data = self._call(
            f"{post_external_id}/comments",
            {"fields": "id,message,created_time,from,like_count", "limit": 50, "order": "reverse_chronological"},
        )
        comments: list[CommentRecord] = []
        for item in data.get("data", []):
            published = parse_iso_dt(item.get("created_time"))
            if published is not None and published <= since:
                continue
            frm = item.get("from") or {}
            self.raw_events.append(RawEventRecord(self.source, "comment", item.get("id"), item))
            comments.append(
                CommentRecord(
                    post_external_id=post_external_id,
                    account_external_id=account,
                    platform="facebook",
                    external_id=item.get("id"),
                    text_content=item.get("message", "") or "",
                    published_at=published,
                    like_count=to_int(item.get("like_count")) or 0,
                    author_external_id=frm.get("id"),
                )
            )
        return comments
