"""LLM package (brief Section 11.3, Week 6).

A thin multi-provider gateway over the free-tier LLM providers with automatic
failover, response caching, and full call logging, plus a content-generation
service on top of it. Layering mirrors the rest of the app:

  providers.py   pure: model-string -> provider, key resolution, default chain.
  gateway.py     the failover loop and per-attempt metadata. litellm is injected,
                 so the whole thing is unit-tested without a network call.
  generation.py  pure prompt building and robust variant parsing.
  service.py     the only DB-facing layer: persists llm_calls and generated_contents.
"""
