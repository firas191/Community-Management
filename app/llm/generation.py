"""Post-caption generation on top of the gateway (Week 6). Pure helpers.

Builds the chat messages for "give me N caption options for this brief" and parses
whatever the model returns back into a clean list of strings. Models are
inconsistent (a JSON array, a fenced block, or a numbered list), so the parser
tries several shapes before giving up, and never raises on a malformed reply.
"""

from __future__ import annotations

import json
import re

MAX_VARIANTS = 8

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)
_LIST_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def build_messages(
    brief: str,
    *,
    n: int = 3,
    language: str = "auto",
    tone: str = "friendly",
    platform: str = "instagram",
    brand_context: str | None = None,
) -> list[dict]:
    """Chat messages asking for N caption options as a JSON array of strings."""
    lang_line = (
        "Write in the same language as the brief."
        if language == "auto"
        else f"Write in {language}."
    )
    system = (
        "You are a social media copywriter for a community-management team. "
        "You write concise, engaging captions that fit the platform and brand voice. "
        f"{lang_line} Keep a {tone} tone for {platform}. "
        "Return ONLY a JSON array of strings, one string per caption option, no extra text."
    )
    context = f"\n\nBrand voice reference (recent posts):\n{brand_context}" if brand_context else ""
    user = f"Write {n} distinct caption options for this brief:\n\n{brief}{context}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_variants(text: str, n: int | None = None) -> list[str]:
    """Best-effort parse of a model reply into a list of caption strings."""
    if not text:
        return []
    candidates = _try_json(text)
    if candidates is None:
        fenced = _FENCE_RE.search(text)
        if fenced:
            candidates = _try_json(fenced.group(1))
    if candidates is None:
        array = _ARRAY_RE.search(text)
        if array:
            candidates = _try_json(array.group(0))
    if candidates is None:
        candidates = _from_lines(text)

    cleaned = [c.strip() for c in candidates if isinstance(c, str) and c.strip()]
    # de-dupe, preserve order
    seen: dict[str, None] = {}
    for c in cleaned:
        seen.setdefault(c, None)
    out = list(seen)
    return out[:n] if n else out


def _try_json(text: str) -> list | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("variants", "captions", "options", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return None


def _from_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = _LIST_PREFIX_RE.sub("", raw).strip().strip('"')
        if line:
            lines.append(line)
    return lines


def generate_post_variants(
    gateway,
    brief: str,
    *,
    n: int = 3,
    language: str = "auto",
    tone: str = "friendly",
    platform: str = "instagram",
    brand_context: str | None = None,
    max_tokens: int = 800,
    temperature: float = 0.8,
) -> dict:
    """Generate caption variants and return them with the call metadata."""
    n = max(1, min(n, MAX_VARIANTS))
    messages = build_messages(
        brief, n=n, language=language, tone=tone, platform=platform, brand_context=brand_context
    )
    result = gateway.complete(
        messages, purpose="content_generation", max_tokens=max_tokens, temperature=temperature
    )
    variants = parse_variants(result.text, n)
    return {
        "variants": variants,
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "fallback_depth": result.fallback_depth,
        "cached": result.cached,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "_result": result,  # carried for the service layer to log attempts; stripped by the route
    }
