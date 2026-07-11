"""Load synthetic dev fixtures into the database.

Run: python -m scripts.seed_dev_data   (or `make seed` inside the api container)

Idempotent: re-running inserts zero duplicates thanks to normalizer upserts.
Every row is flagged is_synthetic=true.
"""

from __future__ import annotations

from app.core.db import session_scope
from app.core.logging import configure_logging, get_logger
from app.ingestion import synthetic

log = get_logger("scripts.seed")


def main() -> None:
    configure_logging()
    with session_scope() as db:
        result = synthetic.seed(db)
    log.info(
        "seed_complete",
        accounts=result.accounts_upserted,
        posts=result.posts_upserted,
        snapshots=result.snapshots_inserted,
        comments=result.comments_upserted,
    )
    print(
        f"Seeded: {result.accounts_upserted} accounts, {result.posts_upserted} posts, "
        f"{result.snapshots_inserted} snapshots, {result.comments_upserted} comments "
        f"(all is_synthetic=true)."
    )


if __name__ == "__main__":
    main()
