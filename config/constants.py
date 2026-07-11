"""Project-wide constants and mapping tables.

Everything here is configuration, not logic. Free-tier LLM catalogs churn and
platform Insights field names change between API versions (brief Section 6.1),
so all such names are isolated here behind dicts. Logic modules import these
names; they never spell platform fields or model ids inline.
"""

from __future__ import annotations

# --- Platforms (seed rows for the `platforms` table) ---
PLATFORMS: tuple[str, ...] = (
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
    "linkedin",
    "x",
)

# --- Canonical content types (brief posts.content_type) ---
CONTENT_TYPES: tuple[str, ...] = (
    "photo",
    "video",
    "reel",
    "carousel",
    "text",
    "link",
    "short",
)

# Map raw platform-native type strings to our canonical content types.
# Isolated here because each platform names these differently and versions drift.
CONTENT_TYPE_MAP: dict[str, str] = {
    # Facebook / Meta
    "photo": "photo",
    "photos": "photo",
    "image": "photo",
    "video": "video",
    "reels": "reel",
    "reel": "reel",
    "album": "carousel",
    "carousel": "carousel",
    "carousel_album": "carousel",
    "status": "text",
    "text": "text",
    "link": "link",
    "shared_link": "link",
    # Instagram
    "IMAGE": "photo",
    "VIDEO": "video",
    "CAROUSEL_ALBUM": "carousel",
    # YouTube
    "youtube#video": "video",
    "short": "short",
    "shorts": "short",
}

# --- Sentiment + language label vocabularies (brief Section 9) ---
SENTIMENT_LABELS: tuple[str, ...] = ("positive", "neutral", "negative")
# aeb-latn = Tunisian Arabizi (dialect in Latin letters + digits), the differentiator.
LANGUAGE_LABELS: tuple[str, ...] = ("fr", "en", "ar", "aeb-latn", "other")

# --- Recommendation kinds + confidence bands (brief Sections 6.2, 10) ---
RECOMMENDATION_KINDS: tuple[str, ...] = ("best_time", "content_type", "hashtags", "format")
CONFIDENCE_BANDS: tuple[str, ...] = ("high", "medium", "low")

# --- Timezone policy (brief Section 8.3): store UTC, bucket in Africa/Tunis ---
STORAGE_TZ = "UTC"
DISPLAY_TZ_DEFAULT = "Africa/Tunis"

# --- Hashtag extraction (brief Section 7.1) ---
# Captures Latin word chars plus the Arabic Unicode block so Arabic hashtags survive.
HASHTAG_REGEX = r"#[\w؀-ۿ]+"

# --- LLM provider order (brief Section 3.2). Used from Week 6. Names, not clients. ---
LLM_CHAIN_SHORT: tuple[str, ...] = (
    "groq/llama-3.3-70b-versatile",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    "nvidia_nim/meta/llama-3.3-70b-instruct",
    "ollama/llama3.1:8b",
)
LLM_CHAIN_LONGCTX: tuple[str, ...] = (
    "gemini/gemini-2.5-flash",
    "groq/llama-3.3-70b-versatile",
)

# --- NLP model registry (brief Section 9). Names in config, weights loaded by name. ---
SENTIMENT_MODEL_MULTILINGUAL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # load-bearing: pgvector column, topics, similarity, brand-voice RAG

# --- Data-quality thresholds (brief Sections 7.1, 13) ---
# Future-timestamp tolerance: clocks skew slightly; reject only clearly-future rows.
FUTURE_TIMESTAMP_TOLERANCE_MINUTES = 5
