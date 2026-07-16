"""Connector sync runner integration (brief 7.1, 7.2). Requires PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.ingestion.sync import ConnectorConfigError, build_connector, run_connector
from app.ingestion.youtube_connector import YouTubeConnector
from app.models import Account, Comment, Post, PostMetricSnapshot, RawEvent, SyncCursor

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
            "snippet": {"title": "Short", "description": ""},
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


def test_run_connector_stores_all_entities(db_session):
    result = run_connector(db_session, _conn())
    db_session.commit()
    assert result.accounts_upserted == 1
    assert result.posts_upserted == 2
    assert result.snapshots_inserted == 2
    assert result.comments_upserted >= 1
    assert db_session.scalar(select(func.count()).select_from(Account)) == 1
    assert db_session.scalar(select(func.count()).select_from(Post)) == 2
    assert db_session.scalar(select(func.count()).select_from(PostMetricSnapshot)) == 2
    assert db_session.scalar(select(func.count()).select_from(Comment)) >= 1


def test_cursors_and_raw_events_written(db_session):
    run_connector(db_session, _conn())
    db_session.commit()
    cursor = db_session.scalar(
        select(SyncCursor.cursor_value).where(
            SyncCursor.source == "youtube", SyncCursor.entity_type == "posts"
        )
    )
    assert cursor is not None
    assert db_session.scalar(select(func.count()).select_from(RawEvent)) > 0


def test_second_run_is_incremental_and_idempotent(db_session):
    run_connector(db_session, _conn())
    db_session.commit()
    # Cursor is now ~now; the fixture videos predate it, so nothing new is fetched.
    result2 = run_connector(db_session, _conn())
    db_session.commit()
    assert result2.posts_upserted == 0
    assert db_session.scalar(select(func.count()).select_from(Post)) == 2  # no duplicates


def test_build_connector_guards(monkeypatch):
    # Force empty config so the guards fire regardless of the local .env.
    from app.config import settings

    for attr in ("youtube_api_key", "youtube_channel_ids", "meta_page_access_token", "meta_page_ids"):
        monkeypatch.setattr(settings, attr, "")
    with pytest.raises(ConnectorConfigError):
        build_connector("youtube")
    with pytest.raises(ConnectorConfigError):
        build_connector("meta")
    with pytest.raises(ConnectorConfigError):
        build_connector("nope")
