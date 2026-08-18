"""Pure topic-layer logic (Week 8). No BERTopic, no DB, no network.

Everything except the clustering itself lives in pure functions precisely so it can
be pinned down without installing the topics extra.
"""

from __future__ import annotations

from app.nlp import topics


def test_label_from_keywords_joins_top_words():
    assert topics.label_from_keywords(["livraison", "retard", "commande", "colis"]) == "livraison / retard / commande"
    assert topics.label_from_keywords(["prix"]) == "prix"
    assert topics.label_from_keywords(["a", "b"], max_words=2) == "a / b"


def test_label_from_keywords_handles_empty_and_blank():
    assert topics.label_from_keywords([]) == "unlabeled"
    assert topics.label_from_keywords(["", "   "]) == "unlabeled"


def test_average_sentiment():
    assert topics.average_sentiment([1.0, 1.0, -1.0]) == round(1 / 3, 4)
    assert topics.average_sentiment([0.0, 0.0]) == 0.0
    assert topics.average_sentiment([]) is None  # nothing to average, not a fake zero


def test_prepare_docs_uses_the_same_preprocessing_as_sentiment():
    out = topics.prepare_docs(["Check https://x.com now @someone", None])
    assert "http" in out[0] and "@user" in out[0]
    assert out[1] == ""  # a None text becomes empty, never a crash


def test_usable_clusters_drops_outliers_and_small_clusters():
    clusters = [
        topics.TopicCluster(topic_id=-1, keywords=[], doc_indices=[0, 1, 2, 3, 4]),  # outliers
        topics.TopicCluster(topic_id=0, keywords=["a"], doc_indices=[5, 6, 7]),      # keep
        topics.TopicCluster(topic_id=1, keywords=["b"], doc_indices=[8]),            # too small
    ]
    keep = topics.usable_clusters(clusters, min_size=3)
    assert [c.topic_id for c in keep] == [0]


def test_cluster_size_property():
    assert topics.TopicCluster(topic_id=2, doc_indices=[1, 2, 3]).size == 3


def test_thresholds_are_documented_constants():
    assert topics.MIN_DOCS_FOR_TOPICS == 20
    assert topics.OUTLIER_TOPIC_ID == -1


def test_backend_protocol_is_satisfied_by_a_stub():
    class StubBackend:
        model_name = "stub-topics"
        model_version = "stub-1.0"

        def fit(self, docs):
            return [], []

    assert isinstance(StubBackend(), topics.TopicBackend)
