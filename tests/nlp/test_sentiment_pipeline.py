"""Sentiment analyzer pipeline (routing + assembly) with a stub backend."""

from __future__ import annotations

import pytest

from app.nlp.sentiment import SentimentAnalyzer
from tests.nlp.stubs import StubBackend, UnavailableBackend


def test_analyze_routes_language_and_sentiment():
    a = SentimentAnalyzer(StubBackend())
    res = a.analyze(["3ajbetni barcha el video", "Not worth the price honestly", "منتج رائع"])
    assert res[0]["language"] == "aeb-latn"
    assert res[0]["needs_arabizi_specialist"] is True
    assert res[0]["sentiment"] == "positive"
    assert res[1]["sentiment"] == "negative"
    assert res[2]["language"] == "ar"
    assert all(r["model_name"] == "stub-model" for r in res)
    assert all(r["model_version"] == "stub-1.0" for r in res)


def test_analyze_empty_list_returns_empty():
    assert SentimentAnalyzer(StubBackend()).analyze([]) == []


def test_emoji_polarity_travels_through():
    res = SentimentAnalyzer(StubBackend()).analyze(["love it 😍🔥"])
    assert res[0]["emoji_polarity"] == 1.0


def test_non_arabizi_not_flagged():
    res = SentimentAnalyzer(StubBackend()).analyze(["Great product overall"])
    assert res[0]["needs_arabizi_specialist"] is False


def test_model_unavailable_raises_runtimeerror():
    with pytest.raises(RuntimeError):
        SentimentAnalyzer(UnavailableBackend()).analyze(["hello world"])
