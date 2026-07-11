"""Language routing with the Tunisian Arabizi layer (brief Section 9.4). Pure.

The hard, valuable case is Tunisian Arabizi: dialect written in Latin letters and
digits ("3ajbetni barcha el video", "ya3tik sa7a"). Off-the-shelf detectors call
it random Latin languages. This module adds a deterministic rule layer on top of
a generic detector:

  1. If the text is mostly Arabic script -> ``ar``.
  2. If it is Latin script AND (uses digits as letters intra-word, e.g. 3/7/9,
     OR contains curated Tunisian tokens like "barcha", "behi", "sa7a") ->
     ``aeb-latn`` (Tunisian Arabizi).
  3. Otherwise a base detector picks ``fr`` / ``en``; anything else is ``other``.

The base detector is pluggable. langdetect is used when available (pure Python,
no download); a lightweight heuristic is the offline fallback. fastText lid.176
can be swapped in behind ``_base_detect`` without touching the rule layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config.constants import LANGUAGE_LABELS

# Arabizi digits that stand in for Arabic letters (2=ء 3=ع 5=خ 6=ط 7=ح 8=غ 9=ق).
_ARABIZI_DIGITS = "235679"
# A Latin letter adjacent to an Arabizi digit inside a token: "sa7a", "3ajbetni".
_ARABIZI_INTRAWORD_RE = re.compile(r"[a-z][" + _ARABIZI_DIGITS + r"]|[" + _ARABIZI_DIGITS + r"][a-z]", re.I)
_ARABIC_CHAR_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
_LATIN_CHAR_RE = re.compile(r"[a-zA-Z]")
_WORD_RE = re.compile(r"[a-z0-9]+", re.I)

# Curated Tunisian dialect / Arabizi tokens. High precision markers; extend freely.
_TUNISIAN_LEXICON: frozenset[str] = frozenset({
    "barcha", "barsha", "yesser", "behi", "bahi", "sa7a", "sahha", "3aslema",
    "aslema", "inshallah", "nchallah", "ychallah", "ya3tik", "yaatik", "mte3",
    "mtaa", "famma", "fama", "chnowa", "chnia", "3andi", "3andek", "mouch",
    "mch", "mech", "nheb", "n7eb", "brabbi", "3la", "3ala", "w9tach", "waqtach",
    "chwaya", "barka", "labes", "labas", "sahbi", "7aja", "kifach", "bech",
    "besh", "5ir", "khir", "mabrouk", "3aychek", "aychek", "tbarkallah", "3aslama",
    "yezzi", "3adi", "9alb", "9added", "wenou", "3avec", "taw", "tawa", "hedha",
    "hetha", "familia", "semhili", "3achra", "mrigel", "zeda", "zada",
})

_FRENCH_HINTS = frozenset({
    "le", "la", "les", "je", "tu", "est", "une", "des", "pas", "tres", "merci",
    "bonjour", "produit", "livraison", "trop", "bien", "vraiment", "avec", "pour",
    "vous", "nous", "recommande", "qualite", "commande", "super",
})
_ENGLISH_HINTS = frozenset({
    "the", "you", "this", "that", "great", "good", "bad", "love", "hate", "price",
    "quality", "order", "again", "worth", "amazing", "thanks", "please", "very",
    "will", "not", "really", "delivery", "product",
})
_FRENCH_ACCENTS_RE = re.compile(r"[éèêàâçùûîïôœ]", re.I)


@dataclass(frozen=True, slots=True)
class LanguageResult:
    language: str  # one of config.constants.LANGUAGE_LABELS
    confidence: float
    method: str  # 'script', 'arabizi_rule', 'base_detector', 'heuristic'

    def __post_init__(self) -> None:
        if self.language not in LANGUAGE_LABELS:
            raise ValueError(f"Unknown language label '{self.language}'.")


def _script_ratios(text: str) -> tuple[float, float]:
    """Return (arabic_ratio, latin_ratio) over alphabetic-ish characters."""
    arabic = len(_ARABIC_CHAR_RE.findall(text))
    latin = len(_LATIN_CHAR_RE.findall(text))
    total = arabic + latin
    if total == 0:
        return 0.0, 0.0
    return arabic / total, latin / total


def _arabizi_signal(text: str) -> float:
    """Strength of the Arabizi signal in [0, 1]: lexicon hits + digit-letters."""
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return 0.0
    lexicon_hits = sum(1 for w in words if w in _TUNISIAN_LEXICON)
    intraword_hits = len(_ARABIZI_INTRAWORD_RE.findall(text))
    signal = min(1.0, (lexicon_hits * 0.6) + (intraword_hits * 0.5))
    return round(signal, 4)


def _base_detect(text: str) -> LanguageResult:
    """Generic fr/en/ar/other detection. Tries langdetect, else a heuristic."""
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        best = detect_langs(text)[0]
        lang = best.lang if best.lang in ("fr", "en", "ar") else "other"
        return LanguageResult(lang, round(float(best.prob), 4), "base_detector")
    except Exception:
        return _heuristic_detect(text)


def _heuristic_detect(text: str) -> LanguageResult:
    words = {w.lower() for w in _WORD_RE.findall(text)}
    fr = len(words & _FRENCH_HINTS) + (1 if _FRENCH_ACCENTS_RE.search(text) else 0)
    en = len(words & _ENGLISH_HINTS)
    if fr == 0 and en == 0:
        return LanguageResult("other", 0.3, "heuristic")
    return LanguageResult("fr" if fr >= en else "en", 0.5, "heuristic")


def detect_language(text: str) -> LanguageResult:
    """Route a single comment to fr / en / ar / aeb-latn / other."""
    if not text or not text.strip():
        return LanguageResult("other", 0.0, "heuristic")

    arabic_ratio, latin_ratio = _script_ratios(text)
    if arabic_ratio >= 0.4 and arabic_ratio >= latin_ratio:
        return LanguageResult("ar", round(0.6 + 0.4 * arabic_ratio, 4), "script")

    if latin_ratio > 0:
        signal = _arabizi_signal(text)
        if signal >= 0.5:
            return LanguageResult("aeb-latn", round(min(0.99, 0.6 + signal * 0.3), 4), "arabizi_rule")
        base = _base_detect(text)
        # A weak Arabizi signal nudges an otherwise-ambiguous Latin text.
        if signal > 0 and base.language in ("other", "en") and base.confidence < 0.8:
            return LanguageResult("aeb-latn", round(0.55 + signal * 0.2, 4), "arabizi_rule")
        return base

    return LanguageResult("other", 0.3, "heuristic")


def detect_batch(texts: list[str]) -> list[LanguageResult]:
    return [detect_language(t) for t in texts]
