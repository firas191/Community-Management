"""Post, metric snapshot, and comment models (the content time series)."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from config.constants import EMBEDDING_DIM


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id"),
        Index("idx_posts_pub", "account_id", "published_at"),
        Index("idx_posts_hashtags", "hashtags", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    text_content: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    media_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    permalink: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    # 384-dim MiniLM embedding for brand-voice RAG and similarity (Week 6+).
    text_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    account: Mapped["Account"] = relationship(back_populates="posts")  # noqa: F821
    metric_snapshots: Mapped[list["PostMetricSnapshot"]] = relationship(
        back_populates="post"
    )
    comments: Mapped[list["Comment"]] = relationship(back_populates="post")


class PostMetricSnapshot(Base):
    """Append-only time series. One row per fetch, never overwritten (brief 6.2)."""

    __tablename__ = "post_metric_snapshots"
    __table_args__ = (UniqueConstraint("post_id", "captured_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    # Nullable on purpose: owner-private on public sources. Null, never 0.
    reach: Mapped[int | None] = mapped_column(Integer)
    impressions: Mapped[int | None] = mapped_column(Integer)
    video_views: Mapped[int | None] = mapped_column(Integer)
    clicks: Mapped[int | None] = mapped_column(Integer)

    post: Mapped[Post] = relationship(back_populates="metric_snapshots")


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (UniqueConstraint("post_id", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("posts.id"))
    external_id: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of author id: GDPR-friendly by construction (brief 6.2).
    author_hash: Mapped[str | None] = mapped_column(Text)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    post: Mapped[Post] = relationship(back_populates="comments")
