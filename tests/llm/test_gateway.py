"""Gateway failover, timing, and attempt logging (Week 6). Fake completions, no network."""

from __future__ import annotations

import pytest

from app.llm.gateway import LLMError, LLMGateway
from tests.llm.stubs import always_fail, always_ok, fail_then_ok, make_settings


def _gw(fn, chain, **skeys):
    return LLMGateway(fn, settings=make_settings(**skeys), chain=chain)


def test_primary_success_no_fallback():
    gw = _gw(always_ok("hi"), ["groq/a"], groq_api_key="k")
    r = gw.complete([{"role": "user", "content": "x"}], use_cache=False)
    assert r.text == "hi"
    assert r.provider == "groq"
    assert r.fallback_depth == 0
    assert r.prompt_tokens == 5 and r.completion_tokens == 7
    assert len(r.attempts) == 1 and r.attempts[0].status == "ok"


def test_falls_over_to_second_provider():
    gw = _gw(fail_then_ok({"groq/a"}, "recovered"), ["groq/a", "gemini/b"], groq_api_key="k", google_api_key="g")
    r = gw.complete([{"role": "user", "content": "x"}], use_cache=False)
    assert r.text == "recovered"
    assert r.provider == "gemini"
    assert r.fallback_depth == 1
    # both attempts recorded: the failure then the success
    assert [a.status for a in r.attempts] == ["error", "ok"]
    assert r.attempts[0].error is not None


def test_all_providers_fail_raises():
    gw = _gw(always_fail(), ["groq/a", "gemini/b"], groq_api_key="k", google_api_key="g")
    with pytest.raises(LLMError):
        gw.complete([{"role": "user", "content": "x"}], use_cache=False)


def test_empty_chain_raises():
    gw = LLMGateway(always_ok(), settings=make_settings(), chain=[])
    with pytest.raises(LLMError):
        gw.complete([{"role": "user", "content": "x"}], use_cache=False)


def test_attempt_count_matches_chain_on_total_failure():
    chain = ["groq/a", "gemini/b", "openrouter/c"]
    gw = _gw(always_fail(), chain, groq_api_key="k", google_api_key="g", openrouter_api_key="o")
    try:
        gw.complete([{"role": "user", "content": "x"}], use_cache=False)
    except LLMError:
        pass
    # the gateway tried every model in the chain (verified via a capturing fn)
    seen = []
    gw2 = LLMGateway(lambda **kw: seen.append(kw["model"]) or (_ for _ in ()).throw(RuntimeError()),
                     settings=make_settings(), chain=chain)
    with pytest.raises(LLMError):
        gw2.complete([{"role": "user", "content": "x"}], use_cache=False)
    assert seen == chain
