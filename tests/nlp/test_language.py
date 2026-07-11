"""Language routing fixtures, including the Tunisian Arabizi layer (brief 9.4)."""

from __future__ import annotations

import pytest

from app.nlp.language import detect_language


def test_arabic_script_detected():
    r = detect_language("منتج رائع شكرا لكم")
    assert r.language == "ar"
    assert r.method == "script"


@pytest.mark.parametrize(
    "text",
    [
        "3ajbetni barcha el video, ya3tik sa7a",  # digit-letters + lexicon
        "behi barcha, yesser",                    # pure lexicon
        "el livraison m3atla yesser, mouch behi",  # Arabizi negative
        "sa7a 3aslema chnowa",                     # digit-letters + lexicon
    ],
)
def test_tunisian_arabizi_detected(text):
    r = detect_language(text)
    assert r.language == "aeb-latn"
    assert r.method == "arabizi_rule"


def test_french_detected():
    r = detect_language("Super produit, je recommande vivement la livraison")
    assert r.language == "fr"


def test_english_detected():
    r = detect_language("Great quality product, will order again for sure")
    assert r.language == "en"


def test_empty_is_other():
    assert detect_language("").language == "other"
    assert detect_language("   ").language == "other"


def test_plain_numbers_are_not_arabizi():
    # digits not used as letters (spaced, not intra-word) must not trip Arabizi
    r = detect_language("price is 300 for 2 items thanks")
    assert r.language != "aeb-latn"


def test_result_confidence_in_range():
    for text in ["منتج رائع", "3ajbetni barcha", "great product", "je recommande"]:
        r = detect_language(text)
        assert 0.0 <= r.confidence <= 1.0
