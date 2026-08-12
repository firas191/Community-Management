"""Provider resolution for the LLM gateway (Week 6). Pure functions.

A litellm model string is ``<provider>/<model>`` (e.g. ``groq/llama-3.3-70b-versatile``,
``gemini/gemini-2.5-flash``, ``openrouter/meta-llama/llama-3.1-8b-instruct:free``).
This module maps a model string to its provider, resolves the API key from settings,
decides whether a model is usable (its key is present), and assembles the default
failover chain. No network, no litellm import here.
"""

from __future__ import annotations

from app.config import Settings

# provider prefix -> the Settings attribute holding its key. Ollama is local and
# needs no key, so it is always considered configured.
_PROVIDER_KEY_ATTR: dict[str, str | None] = {
    "groq": "groq_api_key",
    "gemini": "google_api_key",
    "google": "google_api_key",
    "openrouter": "openrouter_api_key",
    "nvidia_nim": "nvidia_api_key",
    "nvidia": "nvidia_api_key",
    "ollama": None,
}


def provider_of(model: str) -> str:
    """The provider prefix of a litellm model string ('groq/llama-3.3' -> 'groq')."""
    return model.split("/", 1)[0].strip().lower()


def api_key_for(model: str, settings: Settings) -> str | None:
    """The configured API key for a model's provider, or None (local / unknown)."""
    attr = _PROVIDER_KEY_ATTR.get(provider_of(model))
    if attr is None:
        return None
    return getattr(settings, attr, "") or None


def is_configured(model: str, settings: Settings) -> bool:
    """True when a model can actually be called: a known local provider, or a key is set."""
    provider = provider_of(model)
    if provider not in _PROVIDER_KEY_ATTR:
        return False
    if _PROVIDER_KEY_ATTR[provider] is None:  # ollama: local, no key needed
        return True
    return api_key_for(model, settings) is not None


def status(settings: Settings) -> dict:
    """Which providers have a key set, and the resulting failover chain. No secrets."""
    configured = {
        "groq": bool(settings.groq_api_key),
        "gemini": bool(settings.google_api_key),
        "openrouter": bool(settings.openrouter_api_key),
        "nvidia": bool(settings.nvidia_api_key),
    }
    chain = default_chain(settings)
    return {"configured": configured, "chain": chain, "ready": bool(chain)}


def default_chain(settings: Settings) -> list[str]:
    """Failover order: primary, long-context, then configured extra fallbacks.

    Duplicates are removed while preserving order, and models whose provider key is
    not set are dropped, so the chain only contains models that can really be tried.
    """
    ordered = [settings.llm_primary, settings.llm_longctx, *settings.llm_fallback_list]
    seen: dict[str, None] = {}
    for m in ordered:
        if m and m not in seen and is_configured(m, settings):
            seen[m] = None
    return list(seen)
