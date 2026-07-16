"""YouTube Data API v3 connector (brief Sections 6.1.1, 7.1).

The default live source: public channels need no permission, only an API key.
It pulls channel info, the uploads playlist, per-video statistics, and top-level
comment threads, and maps them to the unified records the normalizer stores.

Reach and impressions are owner-private on public channels, so metric snapshots
leave them null (never 0). Engagement rates then use views/followers downstream,
and reach-based KPIs return null-with-reason, per the honesty rule.

The connector is offline-testable: it calls an injected ``get`` function (default
the resilient HTTP client), so tests feed canned API payloads with no network.
"""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.ingestion import http
from app.ingestion.parse import (
    chunked,
    iso_duration_seconds,
    now_utc,
    parse_iso_dt,
    to_int,
)
from app.ingestion.records import (
    AccountRecord,
    CommentRecord,
    MetricSnapshotRecord,
    PostRecord,
    RawEventRecord,
)

log = get_logger("ingestion.youtube")

BASE = "https://www.googleapis.com/youtube/v3"
SHORT_MAX_SECONDS = 60
DEFAULT_POST_PAGES = 2  # up to 100 recent videos per channel per run (quota-friendly)
DEFAULT_COMMENT_PAGES = 2


class YouTubeConnector:
    source = "youtube"

    def __init__(
        self,
        api_key: str,
        channel_ids: list[str],
        *,
        get: http.GetJson | None = None,
        post_pages: int = DEFAULT_POST_PAGES,
        comment_pages: int = DEFAULT_COMMENT_PAGES,
    ) -> None:
        self.api_key = api_key
        self.channel_ids = channel_ids
        self._get = get or http.get_json
        self.post_pages = post_pages
        self.comment_pages = comment_pages
        self.raw_events: list[RawEventRecord] = []
        self._uploads: dict[str, str | None] = {}
        self._post_account: dict[str, str] = {}
        self._stats_cache: dict[str, dict] = {}

    def _call(self, path: str, params: dict) -> dict:
        return self._get(f"{BASE}/{path}", params={**params, "key": self.api_key})

    def fetch_accounts(self) -> list[AccountRecord]:
        if not self.channel_ids:
            return []
        accounts: list[AccountRecord] = []
        for batch in chunked(self.channel_ids, 50):
            data = self._call(
                "channels",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
            )
            for item in data.get("items", []):
                cid = item["id"]
                self._uploads[cid] = (
                    item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                )
                snippet, stats = item.get("snippet", {}), item.get("statistics", {})
                self.raw_events.append(RawEventRecord(self.source, "account", cid, item))
                accounts.append(
                    AccountRecord(
                        platform="youtube",
                        external_id=cid,
                        handle=snippet.get("customUrl") or snippet.get("title"),
                        display_name=snippet.get("title"),
                        followers_count=to_int(stats.get("subscriberCount")),
                    )
                )
        return accounts

    def _uploads_playlist(self, channel_id: str) -> str | None:
        if channel_id not in self._uploads:
            data = self._call("channels", {"part": "contentDetails", "id": channel_id})
            items = data.get("items", [])
            self._uploads[channel_id] = (
                items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if items
                else None
            )
        return self._uploads[channel_id]

    def fetch_posts(self, account_external_id: str, since: datetime) -> list[PostRecord]:
        playlist = self._uploads_playlist(account_external_id)
        if not playlist:
            return []

        # Walk the uploads playlist (newest first) until we cross the cursor.
        candidates: list[tuple[str, datetime]] = []
        token, pages, stop = None, 0, False
        while pages < self.post_pages and not stop:
            params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50}
            if token:
                params["pageToken"] = token
            data = self._call("playlistItems", params)
            for item in data.get("items", []):
                cd = item.get("contentDetails", {})
                vid = cd.get("videoId")
                published = parse_iso_dt(cd.get("videoPublishedAt"))
                if not vid or published is None:
                    continue
                if published <= since:
                    stop = True
                    continue
                candidates.append((vid, published))
            token = data.get("nextPageToken")
            pages += 1
            if not token:
                break

        details = self._videos([v for v, _ in candidates])
        posts: list[PostRecord] = []
        for vid, published in candidates:
            d = details.get(vid, {})
            snippet = d.get("snippet", {})
            self._stats_cache[vid] = d.get("statistics", {})
            self._post_account[vid] = account_external_id
            seconds = iso_duration_seconds(d.get("contentDetails", {}).get("duration"))
            content_type = "short" if seconds is not None and seconds <= SHORT_MAX_SECONDS else "video"
            title = snippet.get("title", "") or ""
            desc = snippet.get("description", "") or ""
            self.raw_events.append(RawEventRecord(self.source, "post", vid, d or {"videoId": vid}))
            posts.append(
                PostRecord(
                    platform="youtube",
                    account_external_id=account_external_id,
                    external_id=vid,
                    published_at=published,
                    content_type=content_type,
                    text_content=(f"{title}\n{desc}".strip() if desc else title) or None,
                    permalink=f"https://www.youtube.com/watch?v={vid}",
                )
            )
        return posts

    def _videos(self, video_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for batch in chunked(video_ids, 50):
            data = self._call(
                "videos",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(batch), "maxResults": 50},
            )
            for item in data.get("items", []):
                out[item["id"]] = item
        return out

    def fetch_metrics(self, post_external_ids: list[str]) -> list[MetricSnapshotRecord]:
        # Reuse stats already fetched during fetch_posts; only call the API for the rest.
        missing = [v for v in post_external_ids if v not in self._stats_cache]
        for vid, item in self._videos(missing).items():
            self._stats_cache[vid] = item.get("statistics", {})
        now = now_utc()
        metrics: list[MetricSnapshotRecord] = []
        for vid in post_external_ids:
            account = self._post_account.get(vid)
            if account is None:
                continue  # cannot resolve the post without its account
            st = self._stats_cache.get(vid, {})
            self.raw_events.append(RawEventRecord(self.source, "metric", vid, {"statistics": st}))
            metrics.append(
                MetricSnapshotRecord(
                    post_external_id=vid,
                    account_external_id=account,
                    platform="youtube",
                    captured_at=now,
                    likes=to_int(st.get("likeCount")) or 0,
                    comments_count=to_int(st.get("commentCount")) or 0,
                    shares=0,
                    saves=0,
                    reach=None,  # owner-private on public channels
                    impressions=None,
                    video_views=to_int(st.get("viewCount")),
                )
            )
        return metrics

    def fetch_comments(self, post_external_id: str, since: datetime) -> list[CommentRecord]:
        account = self._post_account.get(post_external_id, "")
        comments: list[CommentRecord] = []
        token, pages, stop = None, 0, False
        while pages < self.comment_pages and not stop:
            params = {
                "part": "snippet",
                "videoId": post_external_id,
                "maxResults": 100,
                "order": "time",
                "textFormat": "plainText",
            }
            if token:
                params["pageToken"] = token
            try:
                data = self._call("commentThreads", params)
            except http.HTTPError as exc:
                # Comments disabled on a video is a 403, not an error worth failing on.
                log.info("comments_unavailable", video=post_external_id, detail=str(exc)[:120])
                break
            for item in data.get("items", []):
                top = item.get("snippet", {}).get("topLevelComment", {})
                sn = top.get("snippet", {})
                published = parse_iso_dt(sn.get("publishedAt"))
                if published is not None and published <= since:
                    stop = True
                    continue
                self.raw_events.append(
                    RawEventRecord(self.source, "comment", top.get("id"), item)
                )
                comments.append(
                    CommentRecord(
                        post_external_id=post_external_id,
                        account_external_id=account,
                        platform="youtube",
                        external_id=top.get("id"),
                        text_content=sn.get("textDisplay", "") or "",
                        published_at=published,
                        like_count=to_int(sn.get("likeCount")) or 0,
                        author_external_id=(sn.get("authorChannelId", {}) or {}).get("value"),
                    )
                )
            token = data.get("nextPageToken")
            pages += 1
            if not token:
                break
        return comments
