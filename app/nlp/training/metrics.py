"""Sentiment evaluation metrics (brief Section 9.2). Pure Python, no sklearn.

Multiclass precision/recall/F1, macro-F1, accuracy, confusion matrix, and the
per-language F1 breakdown that is the report's headline table. Macro-F1 is the
primary metric because the classes are imbalanced. Everything here is unit-tested
against hand-computed values, so the numbers in the report can be trusted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

LABELS: tuple[str, ...] = ("positive", "neutral", "negative")


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


def confusion_matrix(y_true: list[str], y_pred: list[str], labels: tuple[str, ...] = LABELS) -> dict:
    """true_label -> {pred_label -> count}."""
    m = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred, strict=True):
        if t in m and p in m[t]:
            m[t][p] += 1
    return m


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def per_class_metrics(
    y_true: list[str], y_pred: list[str], labels: tuple[str, ...] = LABELS
) -> dict[str, ClassMetrics]:
    out: dict[str, ClassMetrics] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        precision, recall, f1 = _prf(tp, fp, fn)
        out[label] = ClassMetrics(round(precision, 4), round(recall, 4), round(f1, 4), support)
    return out


def macro_f1(y_true: list[str], y_pred: list[str], labels: tuple[str, ...] = LABELS) -> float:
    """Unweighted mean F1 over all labels (matches sklearn macro, zero_division=0)."""
    pc = per_class_metrics(y_true, y_pred, labels)
    return round(sum(pc[label].f1 for label in labels) / len(labels), 4)


def accuracy(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return 0.0
    correct = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    return round(correct / len(y_true), 4)


def per_language_f1(
    y_true: list[str], y_pred: list[str], languages: list[str], labels: tuple[str, ...] = LABELS
) -> dict[str, dict]:
    """Macro-F1, accuracy, and support grouped by language. The 'money' table:
    the delta on aeb-latn before vs after fine-tuning is the headline result."""
    groups: dict[str, tuple[list[str], list[str]]] = {}
    for t, p, lang in zip(y_true, y_pred, languages, strict=True):
        groups.setdefault(lang, ([], []))
        groups[lang][0].append(t)
        groups[lang][1].append(p)
    return {
        lang: {
            "macro_f1": macro_f1(yt, yp, labels),
            "accuracy": accuracy(yt, yp),
            "support": len(yt),
        }
        for lang, (yt, yp) in groups.items()
    }


def summary(y_true: list[str], y_pred: list[str], labels: tuple[str, ...] = LABELS) -> dict:
    """A full metric bundle for reports and MLflow logging."""
    pc = per_class_metrics(y_true, y_pred, labels)
    return {
        "accuracy": accuracy(y_true, y_pred),
        "macro_f1": macro_f1(y_true, y_pred, labels),
        "per_class": {k: asdict(v) for k, v in pc.items()},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels),
    }
