"""Platform, account, and follower snapshot models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform_id", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    # Denormalized latest value only. Truth is follower_snapshots (see DECISIONS.md).
    followers_count: Mapped[int | None] = mapped_column(Integer)
    is_competitor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    platform: Mapped[Platform] = relationship()
    posts: Mapped[list["Post"]] = relationship(back_populates="account")  # noqa: F821


class FollowerSnapshot(Base):
    __tablename__ = "follower_snapshots"

    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), primary_key=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    followers_count: Mapped[int] = mapped_column(Integer, nullable=False)
