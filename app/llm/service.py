"""LLM service: generation + observability persistence (Week 6). The DB layer.

Calls the gateway to generate captions, writes one ``llm_calls`` row per attempt
(so failovers are visible in the observability table), and stores the generated
options in ``generated_contents``. When an account is given, its recent posts are
passed to the model as a brand-voice reference.

Transaction boundary follows the project convention: this layer stages rows; the
API route commits.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import generation
from app.llm.gateway import LLMGateway, LLMResult
from app.models import Account, GeneratedContent, LLMCall, Post


class LLMServiceError(ValueError):
    """Bad request (e.g. unknown account). Mapped to HTTP 400/404."""


def log_calls(db: Session, result: LLMResult, purpose: str) -> None:
    """One llm_calls row per attempt, so a failover leaves a visible trail."""
    for depth, att in enumerate(result.attempts):
        db.add(
            LLMCall(
                provider=att.provider,
                model=att.model,
                purpose=purpose,
                prompt_tokens=att.prompt_tokens,
                completion_tokens=att.completion_tokens,
                latency_ms=att.latency_ms,
                status=att.status,
                error=(att.error[:500] if att.error else None),
                fallback_depth=depth,
            )
        )


def _brand_context(db: Session, account_id: int, limit: int = 3) -> str | None:
    """A few of the account's recent captions, used as a brand-voice reference."""
    rows = db.scalars(
        select(Post.text_content)
        .where(Post.account_id == account_id, Post.text_content.is_not(None))
        .order_by(Post.published_at.desc())
        .limit(limit)
    ).all()
    texts = [t.strip() for t in rows if t and t.strip()]
    return "\n".join(f"- {t}" for t in texts) if texts else None


def generate_content(
    db: Session,
    gateway: LLMGateway,
    *,
    brief: str,
    account_id: int | None = None,
    n: int = 3,
    language: str = "auto",
    tone: str = "friendly",
    platform: str = "instagram",
    persist: bool = True,
) -> dict:
    """Generate caption variants, log every attempt, and store the result."""
    brand_context = None
    if account_id is not None:
        acc = db.get(Account, account_id)
        if acc is None:
            raise LLMServiceError(f"Account {account_id} not found.")
        # The account is used only for brand voice; the caller's platform is kept.
        brand_context = _brand_context(db, account_id)

    gen = generation.generate_post_variants(
        gateway, brief, n=n, language=language, tone=tone, platform=platform, brand_context=brand_context
    )
    result: LLMResult = gen.pop("_result")

    if persist:
        log_calls(db, result, purpose="content_generation")
        db.add(
            GeneratedContent(
                account_id=account_id,
                request={"brief": brief, "n": n, "language": language, "tone": tone, "platform": platform},
                variants={"options": gen["variants"]},
                provider=gen["provider"],
                model=gen["model"],
                latency_ms=gen["latency_ms"],
            )
        )

    return {
        "account_id": account_id,
        "brief": brief,
        "platform": platform,
        **gen,
    }
