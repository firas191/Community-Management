"""Pure-function tests for hashtag extraction and content-type mapping.

No database required. Hand-verified expectations.
"""

from __future__ import annotations

from app.ingestion.normalizer import extract_hashtags, map_content_type


def test_extract_hashtags_latin():
    assert extract_hashtags("great #Promo today #FOOD #promo") == ["#promo", "#food"]


def test_extract_hashtags_arabic():
    # Arabic hashtag must survive extraction (brief Section 7.1 regex).
    tags = extract_hashtags("عرض خاص #نجاح والسعر #promo")
    assert "#نجاح" in tags
    assert "#promo" in tags


def test_extract_hashtags_dedupes_and_orders():
    assert extract_hashtags("#a #b #a #c") == ["#a", "#b", "#c"]


def test_extract_hashtags_empty():
    assert extract_hashtags(None) == []
    assert extract_hashtags("no tags here") == []


def test_map_content_type_known():
    assert map_content_type("REELS") == "reel"
    assert map_content_type("carousel_album") == "carousel"
    assert map_content_type("IMAGE") == "photo"
    assert map_content_type("youtube#video") == "video"


def test_map_content_type_passthrough_and_none():
    assert map_content_type("something_new") == "something_new"
    assert map_content_type(None) is None
