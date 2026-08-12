"""Prompt building and robust variant parsing (Week 6). Pure."""

from __future__ import annotations

from app.llm import generation
from app.llm.gateway import LLMResult


def test_build_messages_shapes_the_request():
    msgs = generation.build_messages("Launch our new menu", n=3, tone="playful", platform="instagram")
    assert msgs[0]["role"] == "system" and "instagram" in msgs[0]["content"]
    assert "playful" in msgs[0]["content"]
    assert msgs[1]["role"] == "user" and "Launch our new menu" in msgs[1]["content"]
    assert "3" in msgs[1]["content"]


def test_parse_variants_json_array():
    assert generation.parse_variants('["a", "b", "c"]') == ["a", "b", "c"]


def test_parse_variants_fenced_block():
    assert generation.parse_variants('```json\n["x", "y"]\n```') == ["x", "y"]


def test_parse_variants_dict_with_key():
    assert generation.parse_variants('{"variants": ["p", "q"]}') == ["p", "q"]


def test_parse_variants_numbered_lines_fallback():
    text = "1. First option\n2) Second option\n- Third option"
    assert generation.parse_variants(text) == ["First option", "Second option", "Third option"]


def test_parse_variants_dedupes_and_limits():
    assert generation.parse_variants('["a", "a", "b", "c"]') == ["a", "b", "c"]
    assert generation.parse_variants('["a", "b", "c"]', 2) == ["a", "b"]


def test_parse_variants_empty():
    assert generation.parse_variants("") == []


class _StubGateway:
    def __init__(self, text: str):
        self._text = text

    def complete(self, messages, *, purpose="general", max_tokens=800, temperature=0.7, use_cache=True):
        return LLMResult(text=self._text, provider="groq", model="groq/a", latency_ms=12, fallback_depth=0)


def test_generate_post_variants_returns_parsed_with_metadata():
    gen = generation.generate_post_variants(_StubGateway('["one", "two", "three"]'), "brief", n=3)
    assert gen["variants"] == ["one", "two", "three"]
    assert gen["provider"] == "groq"
    assert gen["model"] == "groq/a"
    assert gen["latency_ms"] == 12
    assert "_result" in gen  # carried for the service layer to log
