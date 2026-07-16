"""Connector sync runner (brief Sections 7.1, 7.2).

Orchestrates one incremental sync for a connector:
  fetch accounts -> for each account fetch posts since its cursor -> fetch metric
  snapshots for those posts -> fetch comments -> store idempotently -> archive raw
  payloads -> advance the per-account cursors.

Never a full re-fetch: each account/entity has a cursor in `sync_cursors`. Re-runs
are safe because the normalizer upserts. The caller owns the transaction, matching
the CSV path (the API route and the Celery task each commit).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.base import Connector
from app.ingestion.normalizer import normalize_and_store
from app.ingestion.parse import now_utc
from app.ingestion.records import IngestionResult, RawEventRecord
from app.models import RawEvent, SyncCursor

log = get_logger("ingestion.sync")

DEFAULT_FIRST_SYNC_DAYS = 90
COMMENT_POST_CAP = 25  # cap comment fetches per run to respect API quota


class ConnectorConfigError(ValueError):
    """A connector was requested but its credentials/targets are not configured."""


def _get_cursor(db: Session, source: str, account_external_id: str, entity_type: str) -> datetime | None:
    return db.scalar(
        select(SyncCursor.cursor_value).where(
            SyncCursor.source == source,
            SyncCursor.account_external_id == account_external_id,
            SyncCursor.entity_type == entity_type,
        )
    )


def _set_cursor(db: Session, source: str, account_external_id: str, entity_type: str, value: datetime) -> None:
    stmt = (
        pg_insert(SyncCursor)
        .values(source=source, account_external_id=account_external_id, entity_type=entity_type, cursor_value=value)
        .on_conflict_do_update(
            index_elements=["source", "account_external_id", "entity_type"],
            set_={"cursor_value": value},
        )
    )
    db.execute(stmt)


def _archive_raw(db: Session, events: list[RawEventRecord]) -> None:
    for e in events:
        db.execute(
            pg_insert(RawEvent).values(
                source=e.source, entity_type=e.entity_type, external_id=e.external_id, payload=e.payload
            )
        )


def run_connector(
    db: Session, connector: Connector, *, account_external_ids: list[str] | None = None
) -> IngestionResult:
    """Run one incremental sync. Does not commit; the caller controls the transaction."""
    now = now_utc()
    default_since = now - timedelta(days=DEFAULT_FIRST_SYNC_DAYS)

    accounts = connector.fetch_accounts()
    account_ids = account_external_ids or [a.external_id for a in accounts]

    posts = []
    for aid in account_ids:
        since = _get_cursor(db, connector.source, aid, "posts") or default_since
        posts.extend(connector.fetch_posts(aid, since))

    post_ids = [p.external_id for p in posts]
    metrics = connector.fetch_metrics(post_ids) if post_ids else []

    post_account = getattr(connector, "_post_account", {})
    comments = []
    # Cap comment fetching PER account, not globally, so every account gets
    # coverage even when another account has far more posts in the same run.
    fetched_per_account: dict[str, int] = {}
    for p in posts:
        aid = post_account.get(p.external_id, "")
        if fetched_per_account.get(aid, 0) >= COMMENT_POST_CAP:
            continue
        fetched_per_account[aid] = fetched_per_account.get(aid, 0) + 1
        since_c = _get_cursor(db, connector.source, aid, "comments") or default_since
        comments.extend(connector.fetch_comments(p.external_id, since_c))

    result = normalize_and_store(
        db, source=connector.source, accounts=accounts, posts=posts, metrics=metrics, comments=comments
    )
    _archive_raw(db, connector.raw_events)

    for aid in account_ids:
        _set_cursor(db, connector.source, aid, "posts", now)
        _set_cursor(db, connector.source, aid, "comments", now)

    log.info(
        "connector_run",
        source=connector.source,
        accounts=len(account_ids),
        posts=len(posts),
        metrics=len(metrics),
        comments=len(comments),
    )
    return result


def build_connector(name: str) -> Connector:
    """Construct a connector by name from settings. Raises ConnectorConfigError."""
    from app.config import settings

    key = name.lower()
    if key == "youtube":
        from app.ingestion.youtube_connector import YouTubeConnector

        if not settings.youtube_api_key:
            raise ConnectorConfigError("YOUTUBE_API_KEY is not set.")
        if not settings.youtube_channel_id_list:
            raise ConnectorConfigError("YOUTUBE_CHANNEL_IDS is empty. Set channel ids to ingest.")
        return YouTubeConnector(settings.youtube_api_key, settings.youtube_channel_id_list)

    if key in ("meta", "facebook"):
        from app.ingestion.meta_connector import MetaConnector

        if not settings.meta_page_access_token:
            raise ConnectorConfigError("META_PAGE_ACCESS_TOKEN is not set.")
        if not settings.meta_page_id_list:
            raise ConnectorConfigError("META_PAGE_IDS is empty. Set page ids to ingest.")
        return MetaConnector(settings.meta_page_access_token, settings.meta_page_id_list)

    raise ConnectorConfigError(f"Unknown connector '{name}'. Known connectors: youtube, meta.")
