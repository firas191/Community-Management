"""Shared pytest fixtures.

Pure-function tests need no infrastructure and always run. Integration tests
that exercise PostgreSQL-specific behavior (ON CONFLICT upserts, ARRAY, JSONB,
pgvector) use the `db_session` fixture. That fixture DROPS every table, so it
must never touch the live application database.

Safety model (defense in depth, all three layers must agree):
1. Integration tests run only against `TEST_DATABASE_URL`. They never fall back
   to `DATABASE_URL`, which is the live app database.
2. `TEST_DATABASE_URL` must differ from `DATABASE_URL` and its database name
   must contain "test". Otherwise the suite fails loudly, it does not wipe.
3. The `db_session` fixture re-checks the target name immediately before every
   `drop_all`, so a misconfigured engine can never delete real data.

Set `CM_ALLOW_DB_WIPE=1` only if you deliberately want to override these
guards (for example a disposable CI database not named "test").
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def _live_database_url() -> str | None:
    """The application database. Destructive fixtures must never target this."""
    return os.environ.get("DATABASE_URL")


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL")


def _allow_wipe() -> bool:
    return os.environ.get("CM_ALLOW_DB_WIPE") == "1"


def _assert_safe_to_wipe(url: str) -> None:
    """Raise if `url` looks like anything other than a dedicated test database."""
    if _allow_wipe():
        return
    name = (make_url(url).database or "").lower()
    live = _live_database_url()
    if live and url == live:
        raise RuntimeError(
            "Refusing to drop schema: TEST_DATABASE_URL equals DATABASE_URL "
            "(the live application database)."
        )
    if "test" not in name:
        raise RuntimeError(
            f"Refusing to drop schema on database '{name}': its name does not "
            "contain 'test'. Point TEST_DATABASE_URL at a dedicated test database."
        )


@pytest.fixture(scope="session")
def _engine():
    url = _test_database_url()
    if not url:
        pytest.skip(
            "Integration tests need a dedicated test database. Set TEST_DATABASE_URL "
            "to a database whose name contains 'test'. These fixtures DROP every "
            "table, so they never fall back to DATABASE_URL (the live app database)."
        )

    # Fail loudly on a dangerous configuration rather than silently wiping data.
    try:
        _assert_safe_to_wipe(url)
    except RuntimeError as exc:
        pytest.fail(str(exc), pytrace=False)

    engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_name = make_url(url).database or url
        pytest.skip(f"Test database not reachable: {db_name!r}.")
    return engine


@pytest.fixture()
def db_session(_engine):
    """Fresh schema per test in an isolated savepoint-less transaction.

    Creates the extension + tables + platform seed, yields a session, then rolls
    the schema back by dropping it. Kept simple over speed: the suite is small.
    """
    from app.core.db import Base
    from config.constants import PLATFORMS

    # Import models so metadata is populated.
    import app.models  # noqa: F401

    # Belt and suspenders: re-check the target right before any destructive op.
    _assert_safe_to_wipe(str(_engine.url))

    with _engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)

    Session = sessionmaker(bind=_engine, expire_on_commit=False)
    session = Session()
    # Seed platform lookup rows.
    from app.models import Platform

    session.add_all([Platform(name=name) for name in PLATFORMS])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        _assert_safe_to_wipe(str(_engine.url))
        Base.metadata.drop_all(_engine)
