"""Training-data preparation for the Arabizi fine-tune (brief Section 9.2). Pure.

Label normalization to the canonical three classes, a seeded stratified 70/10/20
split, and inverse-frequency class weights for imbalance. No heavy dependencies,
so this is unit-tested; the training script imports these functions.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

CANONICAL: tuple[str, ...] = ("positive", "neutral", "negative")

# TUNIZI is largely positive/negative; map the label spellings datasets use onto
# our canonical set. Extend here rather than branching in the training script.
_LABEL_ALIASES: dict[str, str] = {
    "positive": "positive", "pos": "positive", "p": "positive", "1": "positive",
    "negative": "negative", "neg": "negative", "n": "negative", "0": "negative", "-1": "negative",
    "neutral": "neutral", "neu": "neutral", "mixed": "neutral", "2": "neutral",
}


def normalize_label(raw: object) -> str | None:
    """Map a dataset label to positive/neutral/negative, or None if unknown."""
    if raw is None:
        return None
    return _LABEL_ALIASES.get(str(raw).strip().lower())


@dataclass(slots=True)
class Split:
    train: list
    val: list
    test: list


def stratified_split(
    rows: list[dict], *, label_key: str = "label", ratios: tuple[float, float, float] = (0.7, 0.1, 0.2), seed: int = 42
) -> Split:
    """Seeded, stratified split so each class keeps its proportion in every fold.

    Same seed and input yield an identical split, which is what makes the reported
    numbers reproducible.
    """
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError(f"ratios must sum to 1.0, got {ratios}")
    rng = random.Random(seed)
    by_label: dict[str, list] = {}
    for row in rows:
        by_label.setdefault(row[label_key], []).append(row)

    train: list = []
    val: list = []
    test: list = []
    for _label, items in sorted(by_label.items()):
        items = list(items)
        rng.shuffle(items)
        n = len(items)
        n_train = int(n * ratios[0])
        n_val = int(n * ratios[1])
        train += items[:n_train]
        val += items[n_train : n_train + n_val]
        test += items[n_train + n_val :]
    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return Split(train, val, test)


def class_weights(labels: list[str], classes: tuple[str, ...] = CANONICAL) -> dict[str, float]:
    """Inverse-frequency weights (total / (k * count)), so rarer classes weigh more.

    Absent classes get weight 1.0. The mean weight over present classes is ~1.
    """
    counts = Counter(labels)
    present = [c for c in classes if counts.get(c, 0) > 0]
    total = sum(counts.get(c, 0) for c in classes)
    if not present or total == 0:
        return {c: 1.0 for c in classes}
    k = len(present)
    return {
        c: (round(total / (k * counts[c]), 4) if counts.get(c, 0) > 0 else 1.0) for c in classes
    }
