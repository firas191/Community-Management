"""Test doubles for the LLM layer: a fake settings object and fake completions."""

from __future__ import annotations

from types import SimpleNamespace


def make_settings(**over) -> SimpleNamespace:
    """A minimal stand-in for Settings with just the fields the LLM layer reads."""
    base = dict(
        groq_api_key="", google_api_key="", openrouter_api_key="", nvidia_api_key="",
        ollama_base_url="http://ollama:11434", llm_primary="", llm_longctx="", llm_fallbacks="",
    )
    base.update(over)
    ns = SimpleNamespace(**base)
    ns.llm_fallback_list = [m.strip() for m in ns.llm_fallbacks.split(",") if m.strip()]
    return ns


def fake_response(content: str, model: str, pt: int = 5, ct: int = 7) -> SimpleNamespace:
    """An OpenAI/litellm-shaped response object."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
        model=model,
    )


def always_ok(text: str = "hello"):
    def fn(**kwargs):
        return fake_response(text, kwargs["model"])
    return fn


def fail_then_ok(fail_models: set[str], text: str = "hello"):
    def fn(**kwargs):
        if kwargs["model"] in fail_models:
            raise RuntimeError(f"boom for {kwargs['model']}")
        return fake_response(text, kwargs["model"])
    return fn


def always_fail():
    def fn(**kwargs):
        raise RuntimeError(f"boom for {kwargs['model']}")
    return fn
