"""Training-data prep tests (brief Section 9.2). Pure, no model."""

from __future__ import annotations

import pytest

from app.nlp.training.data import class_weights, normalize_label, stratified_split


def test_normalize_label():
    assert normalize_label("POS") == "positive"
    assert normalize_label("1") == "positive"
    assert normalize_label("-1") == "negative"
    assert normalize_label("neg") == "negative"
    assert normalize_label("neu") == "neutral"
    assert normalize_label("garbage") is None
    assert normalize_label(None) is None


def test_stratified_split_is_deterministic_and_proportional():
    rows = [{"text": f"p{i}", "label": "positive"} for i in range(10)]
    rows += [{"text": f"n{i}", "label": "negative"} for i in range(10)]
    s1 = stratified_split(rows, seed=42)
    s2 = stratified_split(rows, seed=42)
    # same seed -> identical split (reproducible reported numbers)
    assert [r["text"] for r in s1.train] == [r["text"] for r in s2.train]
    # per class of 10 -> 7 train / 1 val / 2 test
    assert len(s1.train) == 14
    assert len(s1.val) == 2
    assert len(s1.test) == 4
    # each fold keeps both classes
    assert {r["label"] for r in s1.train} == {"positive", "negative"}
    assert {r["label"] for r in s1.test} == {"positive", "negative"}


def test_stratified_split_rejects_bad_ratios():
    with pytest.raises(ValueError):
        stratified_split([{"label": "positive"}], ratios=(0.5, 0.2, 0.2))


def test_class_weights_inverse_frequency():
    labels = ["positive"] * 8 + ["negative"] * 2
    w = class_weights(labels)
    # total 10, 2 present classes -> pos 10/(2*8)=0.625, neg 10/(2*2)=2.5, neutral absent -> 1.0
    assert w["positive"] == 0.625
    assert w["negative"] == 2.5
    assert w["neutral"] == 1.0


def test_class_weights_empty():
    assert class_weights([]) == {"positive": 1.0, "neutral": 1.0, "negative": 1.0}
