"""YouTube connector mapping tests with canned API payloads. No network."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.youtube_connector import YouTubeConnector

_CHANNELS = {
    "items": [
        {
            "id": "UC_chan1",
            "snippet": {"title": "Demo TN", "customUrl": "@demotn"},
            "statistics": {"subscriberCount": "12000"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU_uploads1"}},
        }
    ]
}
_PLAYLIST = {
    "items": [
        {"contentDetails": {"videoId": "vid1", "videoPublishedAt": "2026-07-01T10:00:00Z"}},
        {"contentDetails": {"videoId": "vid2", "videoPublishedAt": "2026-06-20T08:00:00Z"}},
    ]
}
_VIDEOS = {
    "items": [
        {
            "id": "vid1",
            "snippet": {"title": "Great video", "description": "3ajbetni barcha"},
            "statistics": {"viewCount": "1000", "likeCount": "120", "commentCount": "8"},
            "contentDetails": {"duration": "PT5M30S"},
        },
        {
            "id": "vid2",
            "snippet": {"title": "Short one", "description": ""},
            "statistics": {"viewCount": "500", "likeCount": "40", "commentCount": "3"},
            "contentDetails": {"duration": "PT45S"},
        },
    ]
}
_THREADS = {
    "items": [
        {
            "snippet": {
                "topLevelComment": {
                    "id": "c1",
                    "snippet": {
                        "textDisplay": "behi barcha",
                        "authorChannelId": {"value": "UCauthor1"},
                        "likeCount": 5,
                        "publishedAt": "2026-07-02T09:00:00Z",
                    },
                }
            }
        }
    ]
}
_ROUTES = {"channels": _CHANNELS, "playlistItems": _PLAYLIST, "videos": _VIDEOS, "commentThreads": _THREADS}


def _get(url, *, params=None, headers=None):
    return _ROUTES[url.rsplit("/", 1)[-1]]


def _conn():
    return YouTubeConnector("KEY", ["UC_chan1"], get=_get, post_pages=1, comment_pages=1)


def _since(y=2026, m=1, d=1):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_fetch_accounts():
    acc = _conn().fetch_accounts()[0]
    assert acc.platform == "youtube"
    assert acc.external_id == "UC_chan1"
    assert acc.handle == "@demotn"
    assert acc.followers_count == 12000


def test_fetch_posts_maps_content_type_text_and_permalink():
    c = _conn()
    c.fetch_accounts()
    posts = {p.external_id: p for p in c.fetch_posts("UC_chan1", _since())}
    assert set(posts) == {"vid1", "vid2"}
    assert posts["vid1"].content_type == "video"      # 5m30s
    assert posts["vid2"].content_type == "short"      # 45s
    assert "Great video" in posts["vid1"].text_content
    assert posts["vid1"].permalink.endswith("watch?v=vid1")


def test_fetch_posts_respects_cursor():
    c = _conn()
    c.fetch_accounts()
    posts = c.fetch_posts("UC_chan1", _since(2026, 6, 25))  # excludes vid2 (2026-06-20)
    assert {p.external_id for p in posts} == {"vid1"}


def test_fetch_metrics_reach_null_views_set_account_resolved():
    c = _conn()
    c.fetch_accounts()
    c.fetch_posts("UC_chan1", _since())
    metrics = {m.post_external_id: m for m in c.fetch_metrics(["vid1", "vid2"])}
    assert metrics["vid1"].video_views == 1000
    assert metrics["vid1"].likes == 120
    assert metrics["vid1"].reach is None  # owner-private on public channels
    assert metrics["vid1"].impressions is None
    assert metrics["vid1"].account_external_id == "UC_chan1"


def test_fetch_comments():
    c = _conn()
    c.fetch_accounts()
    c.fetch_posts("UC_chan1", _since())
    comments = c.fetch_comments("vid1", _since())
    assert len(comments) == 1
    assert comments[0].text_content == "behi barcha"
    assert comments[0].author_external_id == "UCauthor1"
    assert comments[0].account_external_id == "UC_chan1"


def test_raw_events_accumulate():
    c = _conn()
    c.fetch_accounts()
    c.fetch_posts("UC_chan1", _since())
    kinds = {e.entity_type for e in c.raw_events}
    assert {"account", "post"} <= kinds
