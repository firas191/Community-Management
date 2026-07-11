"""Idempotency integration tests (brief Section 7.1).

Requires PostgreSQL (ON CONFLICT, ARRAY, pgvector). Skipped automatically when
no database is reachable; runs for real inside `docker compose` (make test).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.ingestion import synthetic
from app.ingestion.csv_importer import import_csv_bytes
from app.models import Comment, Post, PostMetricSnapshot

CSV = (
    b"Post ID,Page ID,Page name,Publish time,Post type,Title,Reach,Reactions,Comments,Shares\n"
    b"100,page_9,Demo,2026-07-03 19:30:00,Photo,Hello #promo,1000,80,10,4\n"
    b"101,page_9,Demo,2026-07-04 08:00:00,Reels,Second #food,500,40,5,2\n"
)


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_csv_import_is_idempotent(db_session):
    # A CSV export is one fetch. Same file + same as_of = fully idempotent.
    as_of = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
    import_csv_bytes(db_session, CSV, profile_id="meta_business_suite_posts", as_of=as_of)
    db_session.commit()
    posts_after_first = _count(db_session, Post)
    snaps_after_first = _count(db_session, PostMetricSnapshot)

    # Re-import the exact same file with the same as_of. No new rows.
    import_csv_bytes(db_session, CSV, profile_id="meta_business_suite_posts", as_of=as_of)
    db_session.commit()

    assert _count(db_session, Post) == posts_after_first == 2
    assert _count(db_session, PostMetricSnapshot) == snaps_after_first == 2


def test_synthetic_seed_flags_and_idempotent(db_session):
    synthetic.seed(db_session)
    db_session.commit()
    posts_first = _count(db_session, Post)
    comments_first = _count(db_session, Comment)
    assert posts_first == 120  # 3 accounts x 40 posts
    assert comments_first > 0

    # Every synthetic post carries the flag; none is presented as real.
    non_synth = db_session.scalar(
        select(func.count()).select_from(Post).where(Post.is_synthetic.is_(False))
    )
    assert non_synth == 0

    synthetic.seed(db_session)
    db_session.commit()
    assert _count(db_session, Post) == posts_first
    assert _count(db_session, Comment) == comments_first
