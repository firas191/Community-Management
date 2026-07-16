"""Hand-computed evaluation metrics (brief Section 9.2). Pure, no model."""

from __future__ import annotations

from app.nlp.training import metrics


def test_accuracy():
    assert metrics.accuracy(["positive", "negative", "neutral"], ["positive", "negative", "positive"]) == round(2 / 3, 4)
    assert metrics.accuracy([], []) == 0.0


def test_per_class_metrics_hand_computed():
    y_true = ["positive", "positive", "negative", "negative", "neutral"]
    y_pred = ["positive", "negative", "negative", "negative", "neutral"]
    pc = metrics.per_class_metrics(y_true, y_pred)
    # positive: tp=1, fp=0, fn=1 -> P=1.0, R=0.5, F1=0.6667
    assert pc["positive"].precision == 1.0
    assert pc["positive"].recall == 0.5
    assert pc["positive"].f1 == 0.6667
    assert pc["positive"].support == 2
    # negative: tp=2, fp=1, fn=0 -> P=0.6667, R=1.0, F1=0.8
    assert pc["negative"].f1 == 0.8
    # neutral: tp=1 -> F1=1.0
    assert pc["neutral"].f1 == 1.0


def test_macro_f1_averages_over_all_labels():
    y_true = ["positive", "positive", "negative", "negative", "neutral"]
    y_pred = ["positive", "negative", "negative", "negative", "neutral"]
    assert metrics.macro_f1(y_true, y_pred) == round((0.6667 + 1.0 + 0.8) / 3, 4)


def test_confusion_matrix():
    cm = metrics.confusion_matrix(["positive", "negative", "positive"], ["negative", "negative", "positive"])
    assert cm["positive"]["negative"] == 1
    assert cm["positive"]["positive"] == 1
    assert cm["negative"]["negative"] == 1


def test_per_language_f1_groups_and_scores():
    y_true = ["positive", "negative", "positive", "negative"]
    y_pred = ["positive", "negative", "negative", "negative"]
    langs = ["aeb-latn", "aeb-latn", "en", "en"]
    per = metrics.per_language_f1(y_true, y_pred, langs)
    assert per["aeb-latn"]["accuracy"] == 1.0
    assert per["aeb-latn"]["support"] == 2
    assert per["en"]["accuracy"] == 0.5


def test_summary_bundle():
    s = metrics.summary(["positive", "negative"], ["positive", "positive"])
    assert set(s) == {"accuracy", "macro_f1", "per_class", "confusion_matrix"}
    assert s["accuracy"] == 0.5
