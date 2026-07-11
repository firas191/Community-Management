"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-10

Hand-authored so the vector extension, GIN index, and platform seed rows are
explicit and deterministic. Mirrors app/models and brief Section 6.2.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op
from config.constants import EMBEDDING_DIM, PLATFORMS

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "platforms",
        sa.Column("id", sa.SmallInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform_id", sa.SmallInteger(), sa.ForeignKey("platforms.id")),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column("followers_count", sa.Integer()),
        sa.Column("is_competitor", sa.Boolean(), server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform_id", "external_id"),
    )

    op.create_table(
        "follower_snapshots",
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id"), primary_key=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("followers_count", sa.Integer(), nullable=False),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id")),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.Text()),
        sa.Column("text_content", sa.Text()),
        sa.Column("hashtags", postgresql.ARRAY(sa.Text())),
        sa.Column("media_count", sa.SmallInteger(), server_default="0"),
        sa.Column("permalink", sa.Text()),
        sa.Column("is_synthetic", sa.Boolean(), server_default=sa.false()),
        sa.Column("text_embedding", Vector(EMBEDDING_DIM)),
        sa.UniqueConstraint("account_id", "external_id"),
    )
    op.create_index("idx_posts_pub", "posts", ["account_id", "published_at"])
    op.create_index(
        "idx_posts_hashtags", "posts", ["hashtags"], postgresql_using="gin"
    )

    op.create_table(
        "post_metric_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("likes", sa.Integer(), server_default="0"),
        sa.Column("comments_count", sa.Integer(), server_default="0"),
        sa.Column("shares", sa.Integer(), server_default="0"),
        sa.Column("saves", sa.Integer(), server_default="0"),
        sa.Column("reach", sa.Integer()),
        sa.Column("impressions", sa.Integer()),
        sa.Column("video_views", sa.Integer()),
        sa.Column("clicks", sa.Integer()),
        sa.UniqueConstraint("post_id", "captured_at"),
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("post_id", sa.BigInteger(), sa.ForeignKey("posts.id")),
        sa.Column("external_id", sa.Text()),
        sa.Column("author_hash", sa.Text()),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("like_count", sa.Integer(), server_default="0"),
        sa.Column("is_synthetic", sa.Boolean(), server_default=sa.false()),
        sa.UniqueConstraint("post_id", "external_id"),
    )

    op.create_table(
        "comment_analyses",
        sa.Column("comment_id", sa.BigInteger(), sa.ForeignKey("comments.id"), primary_key=True),
        sa.Column("language", sa.Text()),
        sa.Column("sentiment", sa.Text(), nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("topic_id", sa.Integer()),
        sa.Column("is_toxic", sa.Boolean()),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id")),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("comment_count", sa.Integer()),
        sa.Column("avg_sentiment", sa.Float()),
        sa.Column("window_start", sa.Date()),
        sa.Column("window_end", sa.Date()),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Text()),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "generated_contents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id")),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("variants", postgresql.JSONB(), nullable=False),
        sa.Column("provider", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("purpose", sa.Text()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.Text()),
        sa.Column("fallback_depth", sa.SmallInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "raw_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_raw_events_captured", "raw_events", ["captured_at"])

    op.create_table(
        "sync_cursors",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("account_external_id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("cursor_value", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source", "account_external_id", "entity_type"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger()),
        sa.Column("conversation_id", sa.Text()),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("reasoning_trace", postgresql.JSONB()),
        sa.Column("tool_call_count", sa.SmallInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed the platform lookup rows (brief config.constants.PLATFORMS).
    platforms_table = sa.table("platforms", sa.column("name", sa.Text()))
    op.bulk_insert(platforms_table, [{"name": name} for name in PLATFORMS])


def downgrade() -> None:
    for table in (
        "agent_runs",
        "sync_cursors",
        "raw_events",
        "llm_calls",
        "generated_contents",
        "recommendations",
        "topics",
        "comment_analyses",
        "comments",
        "post_metric_snapshots",
        "posts",
        "follower_snapshots",
        "accounts",
        "platforms",
    ):
        op.drop_table(table)
    op.execute("DROP EXTENSION IF EXISTS vector")
