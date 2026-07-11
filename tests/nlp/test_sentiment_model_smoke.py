"""Real-model smoke test (brief Section 13 sentiment smoke on a pinned mini-set).

Skips entirely when the NLP extras are absent, exactly like the DB integration
tests skip without Postgres. When transformers + weights are present, it exercises
the true cardiffnlp path end to end on a tiny multilingual set.
"""

from __future__ import annotations

import pytest

pytest.importorskip("transformers")
pytest.importorskip("torch")


def test_real_model_end_to_end():
    from app.nlp.sentiment import SentimentAnalyzer, TransformersBackend

    analyzer = SentimentAnalyzer(TransformersBackend())
    res = analyzer.analyze(
        ["I really love this, amazing quality", "This is terrible, very disappointed", "Bonjour"]
    )
    assert len(res) == 3
    for r in res:
        assert r["sentiment"] in ("positive", "neutral", "negative")
        assert 0.0 <= r["score"] <= 1.0
        assert r["model_name"].endswith("twitter-xlm-roberta-base-sentiment")
