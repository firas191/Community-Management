"""Deterministic stub sentiment backend for tests (no model download)."""

from __future__ import annotations

from app.nlp.sentiment import Prediction

_POS = ("great", "bien", "super", "3ajbetni", "behi", "ya3tik", "recommande", "رائع", "love")
_NEG = ("bad", "decu", "déçu", "m3atla", "not worth", "سيئة", "lente", "hate", "terrible")


class StubBackend:
    """Keyword-driven, deterministic. Implements the SentimentBackend Protocol."""

    model_name = "stub-model"
    model_version = "stub-1.0"

    def predict(self, texts: list[str]) -> list[Prediction]:
        out: list[Prediction] = []
        for t in texts:
            low = t.lower()
            if any(k in low for k in _POS):
                out.append(Prediction("positive", 0.95))
            elif any(k in low for k in _NEG):
                out.append(Prediction("negative", 0.90))
            else:
                out.append(Prediction("neutral", 0.60))
        return out


class UnavailableBackend:
    """Simulates the NLP extras being absent: predict raises like the real loader."""

    model_name = "unavailable"
    model_version = "n/a"

    def predict(self, texts: list[str]) -> list[Prediction]:
        raise RuntimeError("Sentiment model needs the NLP extras. Install with `pip install -e \".[nlp]\"`.")
