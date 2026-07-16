"""Sentiment model boundary and analyzer (brief Section 9.2). The model layer.

Design goal: the whole pipeline (preprocess -> language route -> classify ->
assemble) is testable without downloading a 1 GB transformer. That is achieved by
putting inference behind a ``SentimentBackend`` Protocol. The real backend
(``TransformersBackend``) lazy-loads cardiffnlp/twitter-xlm-roberta-base-sentiment
on first use; a stub backend is injected in tests. Nothing here imports
transformers at module import time, so the app boots without the NLP extras.

Routing (Week 3): fr / en / ar and unknown go to Model A (the multilingual
baseline). Tunisian Arabizi (aeb-latn) also uses Model A for now, flagged
``needs_arabizi_specialist`` so the dashboard knows the label is provisional. The
fine-tuned Arabizi model (Model B) replaces that path in Week 4 without changing
this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, runtime_checkable

from app.core.logging import get_logger
from app.nlp.language import detect_batch
from app.nlp.preprocessing import emoji_polarity_score, preprocess
from config.constants import SENTIMENT_LABELS, SENTIMENT_MODEL_MULTILINGUAL

log = get_logger("nlp.sentiment")

SENTIMENT_MODEL_VERSION = "xlmr-base-multilingual-1.0"
ARABIZI_MODEL_VERSION = "tunizi-arabizi-1.0"  # Model B (Week 4), used when configured
MAX_LENGTH = 128
# Normalize whatever a model calls its classes into our stable three labels.
_LABEL_MAP = {
    "negative": "negative", "neg": "negative", "label_0": "negative",
    "neutral": "neutral", "neu": "neutral", "label_1": "neutral",
    "positive": "positive", "pos": "positive", "label_2": "positive",
}


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str  # one of SENTIMENT_LABELS
    score: float  # confidence of the predicted class in [0, 1]


@runtime_checkable
class SentimentBackend(Protocol):
    model_name: str
    model_version: str

    def predict(self, texts: list[str]) -> list[Prediction]:
        """Classify already-preprocessed texts into positive/neutral/negative."""
        ...


def normalize_label(raw: str) -> str:
    label = _LABEL_MAP.get(raw.strip().lower())
    if label is None or label not in SENTIMENT_LABELS:
        raise ValueError(f"Unmappable sentiment label from model: {raw!r}")
    return label


class TransformersBackend:
    """Real Model A. Lazy-loads the multilingual transformer on first predict."""

    def __init__(
        self, model_name: str = SENTIMENT_MODEL_MULTILINGUAL, model_version: str = SENTIMENT_MODEL_VERSION
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover - exercised only without extras
            raise RuntimeError(
                "Sentiment model needs the NLP extras. Install with "
                "`pip install -e \".[nlp]\"` (transformers + torch)."
            ) from exc
        log.info("loading_sentiment_model", model=self.model_name)
        self._pipe = pipeline(
            "text-classification", model=self.model_name, tokenizer=self.model_name, top_k=1
        )
        return self._pipe

    def predict(self, texts: list[str]) -> list[Prediction]:
        if not texts:
            return []
        pipe = self._load()
        raw = pipe(texts, truncation=True, max_length=MAX_LENGTH, batch_size=32)
        out: list[Prediction] = []
        for item in raw:
            top = item[0] if isinstance(item, list) else item
            out.append(Prediction(normalize_label(top["label"]), round(float(top["score"]), 4)))
        return out


@lru_cache
def get_default_backend() -> TransformersBackend:
    """Cached Model A backend. Patched or overridden in tests via SentimentAnalyzer."""
    return TransformersBackend()


@lru_cache
def get_default_arabizi_backend() -> TransformersBackend | None:
    """Cached fine-tuned Arabizi backend (Model B), or None if not configured.

    Set `ARABIZI_MODEL` to a local path (a mounted volume) or a HuggingFace id.
    When unset, the analyzer falls back to Model A for Arabizi.
    """
    from app.config import settings

    if not settings.arabizi_model:
        return None
    return TransformersBackend(settings.arabizi_model, ARABIZI_MODEL_VERSION)


_UNSET = object()


class SentimentAnalyzer:
    """Wires preprocessing + language routing + one or two sentiment backends.

    Tunisian Arabizi (aeb-latn) routes to `arabizi_backend` (Model B) when one is
    available, else it falls back to `backend` (Model A) and is flagged
    `needs_arabizi_specialist`. Every other language always uses `backend`. The
    routing layer never changes; only whether Model B is present.
    """

    def __init__(self, backend: SentimentBackend | None = None, arabizi_backend: object = _UNSET) -> None:
        self.backend = backend or get_default_backend()
        self.arabizi_backend = (
            get_default_arabizi_backend() if arabizi_backend is _UNSET else arabizi_backend
        )

    def analyze(self, texts: list[str]) -> list[dict]:
        if not texts:
            return []
        cleaned = [preprocess(t) for t in texts]
        languages = detect_batch(texts)  # detect on raw text: better Arabizi signal
        use_specialist = self.arabizi_backend is not None
        route_to_specialist = [use_specialist and lang.language == "aeb-latn" for lang in languages]

        # Predict each group with its backend, preserving input order.
        predictions: list[tuple[Prediction, SentimentBackend]] = [None] * len(texts)  # type: ignore[list-item]
        main_idx = [i for i, spec in enumerate(route_to_specialist) if not spec]
        spec_idx = [i for i, spec in enumerate(route_to_specialist) if spec]
        for i, pred in zip(main_idx, self.backend.predict([cleaned[i] for i in main_idx]), strict=True):
            predictions[i] = (pred, self.backend)
        if spec_idx:
            spec_preds = self.arabizi_backend.predict([cleaned[i] for i in spec_idx])
            for i, pred in zip(spec_idx, spec_preds, strict=True):
                predictions[i] = (pred, self.arabizi_backend)

        results: list[dict] = []
        for i, (raw, lang) in enumerate(zip(texts, languages, strict=True)):
            pred, backend = predictions[i]
            results.append(
                {
                    "text": raw,
                    "language": lang.language,
                    "language_confidence": lang.confidence,
                    "language_method": lang.method,
                    "sentiment": pred.label,
                    "score": pred.score,
                    "model_name": backend.model_name,
                    "model_version": backend.model_version,
                    # Provisional only when Arabizi was NOT handled by a specialist.
                    "needs_arabizi_specialist": lang.language == "aeb-latn" and not use_specialist,
                    "emoji_polarity": emoji_polarity_score(raw),
                }
            )
        return results
