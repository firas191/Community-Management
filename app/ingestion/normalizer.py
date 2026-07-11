"""Normalizer: unified records -> PostgreSQL, idempotently (brief Section 7.1).

Responsibilities:
  - Hashtag extraction (regex captures Latin and Arabic hashtags).
  - Content-type mapping via config table (no inline platform strings).
  - Author hashing (raw author ids never stored).
  - Idempotent upserts: re-running a job inserts zero duplicates.
      posts/accounts/comments -> ON CONFLICT DO UPDATE
      metric snapshots        -> ON CONFLICT DO NOTHING (a snapshot is immutable)
  - Data-quality guards from quality.py; rejected rows counted with a reason.

The normalizer resolves platform and account ids once and caches them, so a
batch of posts does one lookup per account, not one per row.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import author_hash
from app.ingestion import quality
from app.ingestion.records import (
    AccountRecord,
    CommentRecord,
    IngestionResult,
    MetricSnapshotRecord,
    PostRecord,
)
from app.models import Account, Comment, Platform, Post, PostMetricSnapshot
from config.constants import CONTENT_TYPE_MAP, HASHTAG_REGEX

log = get_logger("ingestion.normalizer")
_HASHTAG_RE = re.compile(HASHTAG_REGEX, re.UNICODE)


def extract_hashtags(text: str | None) -> list[str]:
    """Return lowercased unique hashtags in order of first appearance."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for match in _HASHTAG_RE.findall(text):
        tag = match.lower()
        seen.setdefault(tag, None)
    return list(seen.keys())


def map_content_type(raw: str | None) -> str | None:
    """Map a platform-native type to a canonical content type, else pass through lower."""
    if raw is None:
        return None
    key = raw.strip()
    if key in CONTENT_TYPE_MAP:
        return CONTENT_TYPE_MAP[key]
    return CONTENT_TYPE_MAP.get(key.lower(), key.lower() or None)


class Normalizer:
    def __init__(self, session: Session, source: str) -> None:
        self.db = session
        self.source = source
        self._platform_ids: dict[str, int] = {}
        self._account_ids: dict[tuple[str, str], int] = {}  # (platform, external_id)->id
        self._post_ids: dict[tuple[str, str, str], int] = {}  # (platform,acct,post)->id

    # --- id resolution ---
    def _platform_id(self, name: str) -> int:
        if name not in self._platform_ids:
            pid = self.db.scalar(select(Platform.id).where(Platform.name == name))
            if pid is None:
                raise ValueError(f"Unknown platform '{name}'. Seed it in platforms first.")
            self._platform_ids[name] = pid
        return self._platform_ids[name]

    def _account_id(self, platform: str, external_id: str) -> int | None:
        key = (platform, external_id)
        if key in self._account_ids:
            return self._account_ids[key]
        pid = self._platform_id(platform)
        aid = self.db.scalar(
            select(Account.id).where(
                Account.platform_id == pid, Account.external_id == external_id
            )
        )
        if aid is not None:
            self._account_ids[key] = aid
        return aid

    # --- upserts ---
    def upsert_accounts(self, accounts: list[AccountRecord], result: IngestionResult) -> None:
        for acc in accounts:
            pid = self._platform_id(acc.platform)
            stmt = (
                pg_insert(Account)
                .values(
                    platform_id=pid,
                    external_id=acc.external_id,
                    handle=acc.handle,
                    display_name=acc.display_name,
                    followers_count=acc.followers_count,
                    is_competitor=acc.is_competitor,
                )
                .on_conflict_do_update(
                    index_elements=["platform_id", "external_id"],
                    set_={
                        "handle": acc.handle,
                        "display_name": acc.display_name,
                        "followers_count": acc.followers_count,
                        "is_competitor": acc.is_competitor,
                    },
                )
                .returning(Account.id)
            )
            aid = self.db.execute(stmt).scalar_one()
            self._account_ids[(acc.platform, acc.external_id)] = aid
            result.accounts_upserted += 1

    def upsert_posts(self, posts: list[PostRecord], result: IngestionResult) -> None:
        for post in posts:
            verdict = quality.check_post(post)
            if not verdict.ok:
                result.note_skip(verdict.reject_reason or "post_rejected")
                continue
            aid = self._account_id(post.platform, post.account_external_id)
            if aid is None:
                result.note_skip("unknown_account")
                continue
            hashtags = post.hashtags if post.hashtags is not None else extract_hashtags(
                post.text_content
            )
            stmt = (
                pg_insert(Post)
                .values(
                    account_id=aid,
                    external_id=post.external_id,
                    published_at=post.published_at,
                    content_type=map_content_type(post.content_type),
                    text_content=post.text_content,
                    hashtags=hashtags,
                    media_count=post.media_count,
                    permalink=post.permalink,
                    is_synthetic=post.is_synthetic,
                )
                .on_conflict_do_update(
                    index_elements=["account_id", "external_id"],
                    set_={
                        "published_at": post.published_at,
                        "content_type": map_content_type(post.content_type),
                        "text_content": post.text_content,
                        "hashtags": hashtags,
                        "media_count": post.media_count,
                        "permalink": post.permalink,
                    },
                )
                .returning(Post.id)
            )
            post_id = self.db.execute(stmt).scalar_one()
            self._post_ids[(post.platform, post.account_external_id, post.external_id)] = post_id
            result.posts_upserted += 1

    def _resolve_post_id(self, platform: str, account_external_id: str, post_external_id: str) -> int | None:
        key = (platform, account_external_id, post_external_id)
        if key in self._post_ids:
            return self._post_ids[key]
        aid = self._account_id(platform, account_external_id)
        if aid is None:
            return None
        pid = self.db.scalar(
            select(Post.id).where(
                Post.account_id == aid, Post.external_id == post_external_id
            )
        )
        if pid is not None:
            self._post_ids[key] = pid
        return pid

    def insert_metrics(
        self, metrics: list[MetricSnapshotRecord], result: IngestionResult
    ) -> None:
        for m in metrics:
            verdict = quality.check_metric(m)
            if not verdict.ok:
                result.note_skip(verdict.reject_reason or "metric_rejected")
                continue
            if verdict.flags:
                for f in verdict.flags:
                    log.warning("data_quality_flag", flag=f, post=m.post_external_id)
            post_id = self._resolve_post_id(
                m.platform, m.account_external_id, m.post_external_id
            )
            if post_id is None:
                result.note_skip("unknown_post")
                continue
            stmt = (
                pg_insert(PostMetricSnapshot)
                .values(
                    post_id=post_id,
                    captured_at=m.captured_at,
                    likes=m.likes,
                    comments_count=m.comments_count,
                    shares=m.shares,
                    saves=m.saves,
                    reach=m.reach,
                    impressions=m.impressions,
                    video_views=m.video_views,
                    clicks=m.clicks,
                )
                # A snapshot at a given instant is immutable: do nothing on conflict.
                .on_conflict_do_nothing(index_elements=["post_id", "captured_at"])
            )
            res = self.db.execute(stmt)
            if res.rowcount:
                result.snapshots_inserted += 1
            else:
                result.note_skip("duplicate_snapshot")

    def upsert_comments(
        self, comments: list[CommentRecord], result: IngestionResult
    ) -> None:
        for c in comments:
            post_id = self._resolve_post_id(
                c.platform, c.account_external_id, c.post_external_id
            )
            if post_id is None:
                result.note_skip("unknown_post")
                continue
            hashed = author_hash(c.author_external_id) if c.author_external_id else None
            stmt = (
                pg_insert(Comment)
                .values(
                    post_id=post_id,
                    external_id=c.external_id,
                    author_hash=hashed,
                    text_content=c.text_content,
                    published_at=c.published_at,
                    like_count=c.like_count,
                    is_synthetic=c.is_synthetic,
                )
                .on_conflict_do_update(
                    index_elements=["post_id", "external_id"],
                    set_={"like_count": c.like_count, "text_content": c.text_content},
                )
            )
            self.db.execute(stmt)
            result.comments_upserted += 1


def normalize_and_store(
    session: Session,
    source: str,
    *,
    accounts: list[AccountRecord] | None = None,
    posts: list[PostRecord] | None = None,
    metrics: list[MetricSnapshotRecord] | None = None,
    comments: list[CommentRecord] | None = None,
) -> IngestionResult:
    """Store a batch idempotently and return a summary. Caller controls the transaction."""
    result = IngestionResult(source=source)
    norm = Normalizer(session, source)
    if accounts:
        norm.upsert_accounts(accounts, result)
    if posts:
        norm.upsert_posts(posts, result)
    if metrics:
        norm.insert_metrics(metrics, result)
    if comments:
        norm.upsert_comments(comments, result)
    log.info(
        "ingestion_summary",
        source=source,
        accounts=result.accounts_upserted,
        posts=result.posts_upserted,
        snapshots=result.snapshots_inserted,
        comments=result.comments_upserted,
        skipped=result.rows_skipped,
        skip_reasons=result.skip_reasons,
    )
    return result
