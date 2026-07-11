"""Social-text preprocessing (brief Section 9.3). Pure functions, no models.

The cardiffnlp sentiment models were trained on tweets with a specific
convention: @mentions become ``@user`` and URLs become ``http``. Matching that
convention at inference time measurably improves accuracy, so ``preprocess`` does
exactly that. Emojis carry sentiment, so they are preserved for the model and
also scored separately for the emoji-analytics feature.

Everything here is deterministic and unit-tested. No network, no model, no clock.
"""

from __future__ import annotations

import re
import unicodedata

# --- Patterns (Unicode ranges as \u escapes so nothing invisible hides in source) ---
_MENTION_RE = re.compile(r"@\w+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_REPEAT_RE = re.compile(r"(.)\1{2,}")  # 3+ of the same char in a row
_ZERO_WIDTH_RE = re.compile("[​-‏‪-‮⁦-⁩﻿]")
_ARABIC_DIACRITICS_RE = re.compile("[ً-ْٰـ]")  # harakat + superscript alef + tatweel

# Arabic letter normalization: unify alef/hamza variants and common finals.
_ARABIC_NORMALIZE = {
    "أ": "ا",  # أ -> ا
    "إ": "ا",  # إ -> ا
    "آ": "ا",  # آ -> ا
    "ٱ": "ا",  # ٱ -> ا
    "ى": "ي",  # ى -> ي
    "ئ": "ي",  # ئ -> ي
    "ؤ": "و",  # ؤ -> و
    "ة": "ه",  # ة -> ه
}

# Arabizi transliteration reference (digit-as-letter -> Arabic). Documented and
# exposed for the fine-tuned Arabizi model (Week 4). Model A keeps the raw text,
# because stripping the digits would destroy the signal a specialist model uses.
ARABIZI_DIGIT_MAP = {
    "2": "ء", "3": "ع", "5": "خ", "6": "ط",
    "7": "ح", "8": "غ", "9": "ق",
}

# Curated emoji -> polarity in {-1, 0, +1}. Small and high-precision on purpose:
# it powers the emoji-analytics widget and breaks ties, it is not the classifier.
EMOJI_POLARITY: dict[str, int] = {
    "😀": 1, "😁": 1, "😂": 1, "🤣": 1, "😊": 1, "😍": 1, "🥰": 1, "😘": 1,
    "👍": 1, "👏": 1, "🙏": 1, "❤️": 1, "❤": 1, "💕": 1, "💚": 1, "🔥": 1,
    "🎉": 1, "✨": 1, "😎": 1, "🥳": 1, "💯": 1, "😇": 1, "🤩": 1,
    "😐": 0, "😶": 0, "🤔": 0, "😴": 0, "🙂": 0,
    "😞": -1, "😔": -1, "😢": -1, "😭": -1, "😠": -1, "😡": -1, "🤬": -1,
    "👎": -1, "💔": -1, "🤮": -1, "😤": -1, "😩": -1, "😒": -1, "🙄": -1, "😳": -1,
}
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f0ff❤]"
)


def strip_zero_width(text: str) -> str:
    return _ZERO_WIDTH_RE.sub("", text)


def normalize_repeated_chars(text: str, keep: int = 2) -> str:
    """Collapse 3+ repeats to ``keep`` (default 2), preserving one repeat as an
    intensity signal: ``barchaaaa`` -> ``barchaa``."""
    return _REPEAT_RE.sub(lambda m: m.group(1) * keep, text)


def normalize_arabic(text: str) -> str:
    """Unify alef/hamza variants, drop diacritics and tatweel. The ``ة -> ه`` and
    ``ى -> ي`` choices are documented here and applied consistently."""
    text = _ARABIC_DIACRITICS_RE.sub("", text)
    return "".join(_ARABIC_NORMALIZE.get(ch, ch) for ch in text)


def mask_mentions_and_urls(text: str) -> str:
    """@handle -> @user, any URL -> http (the cardiffnlp training convention)."""
    text = _URL_RE.sub("http", text)
    return _MENTION_RE.sub("@user", text)


def extract_emojis(text: str) -> list[str]:
    return _EMOJI_RE.findall(text)


def emoji_polarity_score(text: str) -> float:
    """Net emoji polarity in [-1, 1]. 0 when there are no scored emojis."""
    scores = [EMOJI_POLARITY[e] for e in extract_emojis(text) if e in EMOJI_POLARITY]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def preprocess(text: str, *, for_model: bool = True) -> str:
    """Clean a comment for the sentiment model.

    Steps: NFC unicode normalize, strip zero-width marks, mask mentions/URLs,
    collapse character floods, normalize Arabic letters. Emojis are preserved
    (they carry sentiment). Whitespace is squeezed. Returns the cleaned string.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = strip_zero_width(text)
    if for_model:
        text = mask_mentions_and_urls(text)
    text = normalize_repeated_chars(text)
    text = normalize_arabic(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
