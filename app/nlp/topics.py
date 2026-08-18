"""Topic modeling boundary (brief Section 9.3, Week 8). The model layer.

Same shape as the sentiment layer: clustering sits behind a ``TopicBackend``
Protocol so the whole pipeline (load comments -> cluster -> label -> roll up
sentiment -> store) is unit-testable with a stub, and nothing here imports
BERTopic at module import time.

BERTopic is **not** installed in the application image. It pulls umap-learn and
hdbscan, which depend on numba, which caps numpy below 2.1 while this project
pins numpy 2.2.1 for the KPI engine. Rather than downgrade a pin the analytics
layer depends on, BERTopic lives in an optional ``topics`` extra: the endpoints
ship and are tested, and without the extra they answer 503 with an install hint
(the same contract the sentiment endpoints have without the ``nlp`` extra).

Everything except the clustering itself is pure and tested: label generation from
keywords, the sentiment rollup per cluster, and the minimum-size filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.core.logging import get_logger
from app.nlp.preprocessing import preprocess

log = get_logger("nlp.topics")

TOPIC_MODEL_NAME = "bertopic-multilingual"
TOPIC_MODEL_VERSION = "bertopic-1.0"
MIN_DOCS_FOR_TOPICS = 20  # below this, clustering is noise rather than signal
MIN_TOPIC_SIZE = 3        # a cluster smaller than this is not a topic
TOP_KEYWORDS = 8
OUTLIER_TOPIC_ID = -1     # BERTopic's convention for "did not fit a cluster"


class TopicsUnavailableError(RuntimeError):
    """The topics extra (bertopic) is not installed. Mapped to HTTP 503 with a hint."""


@dataclass(frozen=True, slots=True)
class TopicAssignment:
    """One document's cluster id. ``-1`` means outlier (no topic)."""

    index: int
    topic_id: int


@dataclass(slots=True)
class TopicCluster:
    """A discovered topic: its keywords and the documents that fell in it."""

    topic_id: int
    keywords: list[str] = field(default_factory=list)
    doc_indices: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.doc_indices)


@runtime_checkable
class TopicBackend(Protocol):
    model_name: str
    model_version: str

    def fit(self, docs: list[str]) -> tuple[list[TopicAssignment], list[TopicCluster]]:
        """Cluster documents, returning per-doc assignments and the clusters found."""
        ...


def label_from_keywords(keywords: list[str], max_words: int = 3) -> str:
    """A short human label from a cluster's top keywords.

    Deliberately deterministic rather than LLM-generated: a topic label that
    changes between runs makes trends impossible to follow. The LLM naming step
    from the brief can be layered on later without touching this contract.
    """
    words = [w.strip() for w in keywords if w and w.strip()][:max_words]
    return " / ".join(words) if words else "unlabeled"


def average_sentiment(scores: list[float]) -> float | None:
    """Mean of per-comment net sentiment in [-1, 1]. None when there is nothing to average."""
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def prepare_docs(texts: list[str]) -> list[str]:
    """Clean texts with the same preprocessing the sentiment model sees.

    Reusing one function keeps topics and sentiment describing the same text,
    so a topic's sentiment rollup is not computed over differently-cleaned input.
    """
    return [preprocess(t or "") for t in texts]


def usable_clusters(clusters: list[TopicCluster], min_size: int = MIN_TOPIC_SIZE) -> list[TopicCluster]:
    """Drop the outlier bucket and clusters too small to be a real topic."""
    return [
        c for c in clusters
        if c.topic_id != OUTLIER_TOPIC_ID and c.size >= min_size
    ]


class BERTopicBackend:
    """Real backend. Imports BERTopic lazily, on first fit, never at import time."""

    model_name = TOPIC_MODEL_NAME
    model_version = TOPIC_MODEL_VERSION

    def __init__(self, min_topic_size: int = MIN_TOPIC_SIZE, language: str = "multilingual"):
        self._min_topic_size = min_topic_size
        self._language = language
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from bertopic import BERTopic
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise TopicsUnavailableError(
                "bertopic is not installed. Install the topics extra: pip install -e '.[topics]'."
            ) from exc
        log.info("loading_topic_model", model=self.model_name)
        self._model = BERTopic(
            language=self._language,
            min_topic_size=self._min_topic_size,
            calculate_probabilities=False,
            verbose=False,
        )
        return self._model

    def fit(self, docs: list[str]) -> tuple[list[TopicAssignment], list[TopicCluster]]:
        model = self._load()
        topic_ids, _ = model.fit_transform(docs)

        assignments = [TopicAssignment(i, int(t)) for i, t in enumerate(topic_ids)]
        grouped: dict[int, list[int]] = {}
        for a in assignments:
            grouped.setdefault(a.topic_id, []).append(a.index)

        clusters: list[TopicCluster] = []
        for topic_id, indices in grouped.items():
            keywords: list[str] = []
            if topic_id != OUTLIER_TOPIC_ID:
                keywords = [w for w, _score in (model.get_topic(topic_id) or [])][:TOP_KEYWORDS]
            clusters.append(TopicCluster(topic_id=topic_id, keywords=keywords, doc_indices=indices))
        return assignments, clusters


def get_default_backend() -> BERTopicBackend:
    """The production backend. Tests inject a stub instead."""
    return BERTopicBackend()
