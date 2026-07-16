"""Meta (Facebook Page) connector mapping tests with canned payloads. No network."""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingestion.meta_connector import MetaConnector

_PAGE = {"name": "Demo Bakery", "username": "demobakery", "followers_count": 15400}
_POSTS = {
    "data": [
        {
            "id": "p1",
            "message": "Fresh bread #bakery",
            "created_time": "2026-07-01T19:00:00+0000",
            "permalink_url": "https://facebook.com/p1",
            "status_type": "added_photos",
        },
        {
            "id": "p2",
            "message": "Older status",
            "created_time": "2026-05-01T10:00:00+0000",
            "status_type": "mobile_status_update",
        },
    ]
}
_ENG_P1 = {
    "likes": {"summary": {"total_count": 142}},
    "comments": {"summary": {"total_count": 18}},
    "shares": {"count": 7},
}
_ENG_P2 = {
    "likes": {"summary": {"total_count": 50}},
    "comments": {"summary": {"total_count": 5}},
}
_INSIGHTS = {
    "data": [
        {"name": "post_impressions", "values": [{"value": 3400}]},
        {"name": "post_impressions_unique", "values": [{"value": 2100}]},
        {"name": "post_clicks", "values": [{"value": 25}]},
    ]
}
_COMMENTS = {
    "data": [
        {
            "id": "cm1",
            "message": "Super produit, je recommande",
            "created_time": "2026-07-02T08:00:00+0000",
            "from": {"id": "user123", "name": "X"},
            "like_count": 3,
        }
    ]
}
_ROUTES = {
    "PAGE1": _PAGE,
    "published_posts": _POSTS,
    "p1": _ENG_P1,
    "p2": _ENG_P2,
    "insights": _INSIGHTS,
    "comments": _COMMENTS,
}


def _get(url, *, params=None, headers=None):
    return _ROUTES[url.rsplit("/", 1)[-1]]


def _conn():
    return MetaConnector("TOKEN", ["PAGE1"], get=_get)


def _since(y=2026, m=1, d=1):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_fetch_accounts():
    acc = _conn().fetch_accounts()[0]
    assert acc.platform == "facebook"
    assert acc.external_id == "PAGE1"
    assert acc.handle == "demobakery"
    assert acc.followers_count == 15400


def test_fetch_posts_maps_type_and_parses_offset_timestamp():
    c = _conn()
    posts = {p.external_id: p for p in c.fetch_posts("PAGE1", _since())}
    assert set(posts) == {"p1", "p2"}
    assert posts["p1"].content_type == "photo"   # added_photos
    assert posts["p2"].content_type == "text"    # mobile_status_update
    assert posts["p1"].published_at.year == 2026


def test_fetch_posts_respects_cursor():
    c = _conn()
    posts = c.fetch_posts("PAGE1", _since(2026, 6, 1))  # excludes p2 (2026-05-01)
    assert {p.external_id for p in posts} == {"p1"}


def test_fetch_metrics_maps_insight_names():
    c = _conn()
    c.fetch_posts("PAGE1", _since())
    m = {x.post_external_id: x for x in c.fetch_metrics(["p1"])}
    assert m["p1"].likes == 142
    assert m["p1"].comments_count == 18
    assert m["p1"].shares == 7
    assert m["p1"].reach == 2100          # post_impressions_unique
    assert m["p1"].impressions == 3400    # post_impressions
    assert m["p1"].clicks == 25
    assert m["p1"].account_external_id == "PAGE1"


def test_fetch_comments():
    c = _conn()
    c.fetch_posts("PAGE1", _since())
    comments = c.fetch_comments("p1", _since())
    assert len(comments) == 1
    assert comments[0].text_content.startswith("Super produit")
    assert comments[0].author_external_id == "user123"
    assert comments[0].account_external_id == "PAGE1"
