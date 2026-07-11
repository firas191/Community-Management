"""Preprocessing fixtures (brief Section 9.3). Pure, no models."""

from __future__ import annotations

from app.nlp import preprocessing as pp


def test_mask_mentions_and_urls():
    assert pp.mask_mentions_and_urls("hey @ali see https://x.com now") == "hey @user see http now"
    assert pp.mask_mentions_and_urls("visit www.site.tn") == "visit http"


def test_normalize_repeated_chars_keeps_one_repeat():
    assert pp.normalize_repeated_chars("barchaaaa") == "barchaa"
    assert pp.normalize_repeated_chars("cool!!!!") == "cool!!"
    assert pp.normalize_repeated_chars("ok") == "ok"


def test_normalize_arabic_unifies_alef_and_strips_diacritics():
    assert pp.normalize_arabic("أهلا") == "اهلا"
    assert pp.normalize_arabic("إسلام") == "اسلام"
    # ta marbuta -> ha, diacritics removed
    assert pp.normalize_arabic("جميلَة") == "جميله"


def test_emoji_polarity_score():
    assert pp.emoji_polarity_score("great 😍😍") == 1.0
    assert pp.emoji_polarity_score("awful 😡") == -1.0
    assert pp.emoji_polarity_score("hmm 🤔") == 0.0
    assert pp.emoji_polarity_score("no emoji here") == 0.0
    # mixed positive + negative averages toward zero
    assert pp.emoji_polarity_score("😍😡") == 0.0


def test_extract_emojis():
    assert pp.extract_emojis("love it 😍🔥") == ["😍", "🔥"]
    assert pp.extract_emojis("plain") == []


def test_preprocess_end_to_end_preserves_emoji():
    out = pp.preprocess("@ali barchaaaa!!! 😍 https://x.com")
    assert out == "@user barchaa!! 😍 http"


def test_preprocess_empty():
    assert pp.preprocess("") == ""
    assert pp.preprocess("   ") == ""
