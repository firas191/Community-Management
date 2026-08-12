"""Multi-provider LLM gateway with failover, caching, and call logging (Week 6).

The gateway walks a chain of models (primary, long-context, then configured
fallbacks) and returns the first success. Every attempt is timed and recorded, so
the service layer can write one ``llm_calls`` row per attempt and the response
carries which provider answered and at what fallback depth.

litellm is injected as ``completion_fn`` and imported lazily, so importing this
module costs nothing, the whole failover logic is unit-tested with a fake, and the
app boots even when the ``llm`` extra is not installed (the endpoint then returns a
503 with an install hint, like the sentiment model does).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import Settings
from app.config import settings as default_settings
from app.core.logging import get_logger
from app.llm import providers

log = get_logger("llm.gateway")

CompletionFn = Callable[..., object]


class LLMError(RuntimeError):
    """Every model in the chain failed (or the chain was empty)."""


class LLMUnavailableError(RuntimeError):
    """The llm extra (litellm) is not installed. Mapped to HTTP 503 with a hint."""


@dataclass(slots=True)
class Attempt:
    provider: str
    model: str
    status: str  # "ok" | "error"
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


@dataclass(slots=True)
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    fallback_depth: int
    cached: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: list[Attempt] = field(default_factory=list)


def _default_completion_fn() -> CompletionFn:
    """Lazy litellm.completion. Raises LLMUnavailableError if the extra is missing."""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise LLMUnavailableError(
            "litellm is not installed. Install the LLM extra: pip install -e '.[llm]'."
        ) from exc

    litellm.drop_params = True  # silently drop kwargs a given provider does not accept
    return litellm.completion


def _extract(resp: object) -> tuple[str, int | None, int | None, str | None]:
    """Pull text, token counts, and the resolved model from a litellm/OpenAI response."""
    def get(obj: object, key: str) -> object:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    choices = get(resp, "choices") or []
    text = ""
    if choices:
        message = get(choices[0], "message")
        text = (get(message, "content") or "") if message is not None else ""
    usage = get(resp, "usage")
    pt = get(usage, "prompt_tokens") if usage is not None else None
    ct = get(usage, "completion_tokens") if usage is not None else None
    model = get(resp, "model")
    return str(text), (int(pt) if pt is not None else None), (int(ct) if ct is not None else None), (str(model) if model else None)


class LLMGateway:
    """Failover LLM client. Inject ``completion_fn`` in tests; None uses litellm."""

    def __init__(
        self,
        completion_fn: CompletionFn | None = None,
        *,
        settings: Settings | None = None,
        chain: list[str] | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._completion_fn = completion_fn
        self._chain = chain if chain is not None else providers.default_chain(self._settings)

    @property
    def chain(self) -> list[str]:
        return list(self._chain)

    def _fn(self) -> CompletionFn:
        return self._completion_fn or _default_completion_fn()

    def _cache_key(self, messages: list[dict], max_tokens: int, temperature: float) -> str:
        raw = json.dumps(
            {"m": messages, "mt": max_tokens, "t": temperature, "c": self._chain}, sort_keys=True, default=str
        )
        return "cache:llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def complete(
        self,
        messages: list[dict],
        *,
        purpose: str = "general",
        max_tokens: int = 800,
        temperature: float = 0.7,
        use_cache: bool = True,
    ) -> LLMResult:
        """Return the first successful completion in the chain, or raise LLMError."""
        if not self._chain:
            raise LLMError(
                "No LLM providers configured. Set at least one provider key (e.g. GROQ_API_KEY)."
            )

        key = self._cache_key(messages, max_tokens, temperature)
        if use_cache:
            hit = self._cache_get(key)
            if hit is not None:
                return LLMResult(cached=True, attempts=[], **hit)

        fn = self._fn()
        attempts: list[Attempt] = []
        for depth, model in enumerate(self._chain):
            provider = providers.provider_of(model)
            api_key = providers.api_key_for(model, self._settings)
            api_base = self._settings.ollama_base_url if provider == "ollama" else None
            t0 = time.perf_counter()
            try:
                resp = fn(
                    model=model,
                    messages=messages,
                    api_key=api_key,
                    api_base=api_base,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                elapsed = int((time.perf_counter() - t0) * 1000)
                text, pt, ct, resolved = _extract(resp)
                attempts.append(Attempt(provider, model, "ok", elapsed, pt, ct))
                result = LLMResult(
                    text=text, provider=provider, model=resolved or model, latency_ms=elapsed,
                    fallback_depth=depth, prompt_tokens=pt, completion_tokens=ct, attempts=attempts,
                )
                if use_cache:
                    self._cache_set(key, result)
                return result
            except LLMUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001 - any provider failure falls through to the next
                elapsed = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(provider, model, "error", elapsed, error=str(exc)[:300]))
                log.warning("llm_attempt_failed", model=model, depth=depth, error=str(exc)[:200])

        raise LLMError(f"All {len(self._chain)} providers failed for purpose '{purpose}'.")

    # --- cache (optional, degrades silently like the KPI cache) ---
    def _cache_get(self, key: str) -> dict | None:
        try:
            from app.core.cache import cache_get_json

            hit = cache_get_json(key)
            if hit:
                return {k: hit[k] for k in ("text", "provider", "model", "latency_ms", "fallback_depth", "prompt_tokens", "completion_tokens")}
        except Exception:  # noqa: BLE001 - cache is optional
            log.warning("llm_cache_read_failed")
        return None

    def _cache_set(self, key: str, result: LLMResult, ttl: int = 3600) -> None:
        try:
            from app.core.cache import cache_set_json

            cache_set_json(
                key,
                {
                    "text": result.text, "provider": result.provider, "model": result.model,
                    "latency_ms": result.latency_ms, "fallback_depth": result.fallback_depth,
                    "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                },
                ttl,
            )
        except Exception:  # noqa: BLE001 - cache is optional
            log.warning("llm_cache_write_failed")
