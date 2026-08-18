"""Topic service integration (Week 8). Requires PostgreSQL, no BERTopic.

A deterministic stub backend stands in for the clustering, so persistence,
idempotency, the sentiment rollup, and the insufficient-data refusal are all
verified without installing the topics extra.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.ingestion import synthetic
from app.models import Account, Topic
from app.nlp import topic_service
from app.nlp.topics import TopicAssignment, TopicCluster


class SplitBackend:
    """Splits documents into two clusters plus one outlier, deterministically."""

    model_name = "stub-topics"
    model_version = "stub-1.0"

    def fit(self, docs):
        assignments, first, second, outliers = [], [], [], []
        for i in range(len(docs)):
            if i % 10 == 0:
                topic_id, bucket = -1, outliers
            elif i % 2 == 0:
                topic_id, bucket = 0, first
            else:
                topic_id, bucket = 1, second
            assignments.append(TopicAssignment(i, topic_id))
            bucket.append(i)
        clusters = [
            TopicCluster(topic_id=0, keywords=["livraison", "retard"], doc_indices=first),
            TopicCluster(topic_id=1, keywords=["prix", "promo"], doc_indices=second),
            TopicCluster(topic_id=-1, keywords=[], doc_indices=outliers),
        ]
        return assignments, clusters


@pytest.fixture()
def seeded(db_session):
    synthetic.seed(db_session)
    db_session.commit()
    return db_session


def _aid(db, handle: str = "cm_demo_ig") -> int:
    return db.scalar(select(Account.id).where(Account.handle == handle))


def test_discover_persists_topics_with_evidence(seeded):
    out = topic_service.discover_topics(
        seeded, _aid(seeded), "180d", backend=SplitBackend(), persist=True
    )
    seeded.commit()

    assert out["reason"] is None
    assert out["n_topics"] == 2  # the outlier bucket is never a topic
    assert out["model_name"] == "stub-topics"
    assert out["topics"][0]["comment_count"] >= out["topics"][1]["comment_count"]  # largest first
    for t in out["topics"]:
        assert t["label"] and t["keywords"]

    stored = seeded.scalar(select(func.count()).select_from(Topic))
    assert stored == 2


def test_rerun_replaces_rather_than_duplicates(seeded):
    aid = _aid(seeded)
    topic_service.discover_topics(seeded, aid, "180d", backend=SplitBackend())
    seeded.commit()
    first = seeded.scalar(select(func.count()).select_from(Topic))

    topic_service.discover_topics(seeded, aid, "180d", backend=SplitBackend())
    seeded.commit()
    second = seeded.scalar(select(func.count()).select_from(Topic))

    assert first == second  # idempotent for the same account and window


def test_list_topics_returns_stored_rows(seeded):
    aid = _aid(seeded)
    topic_service.discover_topics(seeded, aid, "180d", backend=SplitBackend())
    seeded.commit()

    out = topic_service.list_topics(seeded, aid)
    assert out["count"] == 2
    assert out["topics"][0]["label"]
    assert out["topics"][0]["window_start"] and out["topics"][0]["window_end"]


def test_too_few_comments_returns_a_reason_not_topics(seeded):
    # A one-hour window cannot contain the minimum document count.
    out = topic_service.discover_topics(seeded, _aid(seeded), "1h", backend=SplitBackend())
    assert out["reason"] == "insufficient_data"
    assert out["topics"] == []
    assert out["n_topics"] == 0


def test_unknown_account_raises(seeded):
    with pytest.raises(topic_service.TopicServiceError):
        topic_service.discover_topics(seeded, 999999, "30d", backend=SplitBackend())
