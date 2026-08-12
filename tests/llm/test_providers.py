"""Provider resolution and failover-chain assembly (Week 6). Pure, no network."""

from __future__ import annotations

from app.llm import providers
from tests.llm.stubs import make_settings


def test_provider_of():
    assert providers.provider_of("groq/llama-3.3-70b-versatile") == "groq"
    assert providers.provider_of("openrouter/meta-llama/llama-3.1-8b-instruct:free") == "openrouter"
    assert providers.provider_of("gemini/gemini-2.5-flash") == "gemini"


def test_api_key_and_configured():
    s = make_settings(groq_api_key="k", google_api_key="g")
    assert providers.api_key_for("groq/x", s) == "k"
    assert providers.api_key_for("gemini/x", s) == "g"
    assert providers.api_key_for("ollama/x", s) is None  # local, no key
    assert providers.is_configured("groq/x", s) is True
    assert providers.is_configured("openrouter/x", s) is False  # no key set
    assert providers.is_configured("ollama/x", s) is True  # local always ok
    assert providers.is_configured("madeup/x", s) is False  # unknown provider


def test_default_chain_filters_and_dedupes():
    # gemini has no key -> dropped; only groq survives
    s = make_settings(llm_primary="groq/a", llm_longctx="gemini/b", groq_api_key="k")
    assert providers.default_chain(s) == ["groq/a"]

    # both configured -> both, in order
    s2 = make_settings(llm_primary="groq/a", llm_longctx="gemini/b", groq_api_key="k", google_api_key="g")
    assert providers.default_chain(s2) == ["groq/a", "gemini/b"]

    # primary == longctx -> de-duped to one
    s3 = make_settings(llm_primary="groq/a", llm_longctx="groq/a", groq_api_key="k")
    assert providers.default_chain(s3) == ["groq/a"]

    # fallbacks appended; ollama needs no key
    s4 = make_settings(
        llm_primary="groq/a", llm_longctx="gemini/b", llm_fallbacks="openrouter/c,ollama/d",
        groq_api_key="k", google_api_key="g", openrouter_api_key="o",
    )
    assert providers.default_chain(s4) == ["groq/a", "gemini/b", "openrouter/c", "ollama/d"]


def test_status_reports_configured_and_chain():
    s = make_settings(llm_primary="groq/a", llm_longctx="gemini/b", groq_api_key="k")
    st = providers.status(s)
    assert st["configured"] == {"groq": True, "gemini": False, "openrouter": False, "nvidia": False}
    assert st["chain"] == ["groq/a"]
    assert st["ready"] is True

    assert providers.status(make_settings())["ready"] is False
