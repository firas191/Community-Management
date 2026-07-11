"""CSV importer for official exports (brief Sections 6.1, 7).

The guaranteed, no-credentials data path. Reads a Business Suite (or Kaggle)
export, maps its headers via a profile in config/csv_profiles.py, builds unified
records, and hands them to the normalizer. Robust to header drift: it picks the
first present candidate per field and logs headers it could not map.

Timestamps: exports usually carry local wall-clock time with no offset. Naive
timestamps are localized to the display timezone (Africa/Tunis) then converted
to UTC for storage (brief Section 8.3). Timezone-aware values are converted
directly. This choice is recorded in DECISIONS.md.
"""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.normalizer import normalize_and_store
from app.ingestion.records import (
    AccountRecord,
    IngestionResult,
    MetricSnapshotRecord,
    PostRecord,
)
from config.constants import DISPLAY_TZ_DEFAULT, STORAGE_TZ
from config.csv_profiles import get_profile

log = get_logger("ingestion.csv")

_DISPLAY_TZ = ZoneInfo(DISPLAY_TZ_DEFAULT)
_STORAGE_TZ = ZoneInfo(STORAGE_TZ)

# Numeric fields that may be absent. Absent -> None (never 0), so KPIs stay honest.
_NULLABLE_METRICS = ("reach", "impressions", "video_views", "clicks")
_ZERO_DEFAULT_METRICS = ("likes", "comments_count", "shares", "saves")


class CSVImportError(ValueError):
    """Raised when a required column is missing or the file cannot be parsed."""


def _resolve_columns(profile: dict, columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return (canonical->actual header) for present fields, and unmapped file headers."""
    present = set(columns)
    resolved: dict[str, str] = {}
    for canonical, candidates in profile["column_map"].items():
        for cand in candidates:
            if cand in present:
                resolved[canonical] = cand
                break
    mapped_headers = set(resolved.values())
    unmapped = [c for c in columns if c not in mapped_headers]
    return resolved, unmapped


def _to_utc(value: object) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce", utc=False)
    if ts is pd.NaT or pd.isna(ts):
        return None
    dt = ts.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_DISPLAY_TZ)
    return dt.astimezone(_STORAGE_TZ)


def _to_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_dataframe(
    df: pd.DataFrame,
    profile_id: str | None,
    *,
    platform_override: str | None = None,
    default_account_external_id: str | None = None,
    default_account_name: str | None = None,
    is_synthetic: bool = False,
    as_of: datetime | None = None,
) -> tuple[list[AccountRecord], list[PostRecord], list[MetricSnapshotRecord]]:
    """Turn a DataFrame into unified records using the given profile.

    A CSV export is one point-in-time fetch. Its snapshots are stamped with
    `as_of`, which defaults to now. Re-importing the identical file with the same
    `as_of` is fully idempotent (snapshots dedupe on (post_id, captured_at)).
    """
    profile = get_profile(profile_id)
    resolved, unmapped = _resolve_columns(profile, list(df.columns))
    if unmapped:
        log.info("csv_unmapped_headers", profile=profile["id"], headers=unmapped)

    for req in profile["required"]:
        if req not in resolved:
            raise CSVImportError(
                f"Required field '{req}' not found. Looked for headers: "
                f"{profile['column_map'][req]}. File headers: {list(df.columns)}"
            )

    platform = platform_override or profile.get("platform")
    if platform is None:
        raise CSVImportError(
            "Platform unknown. This profile has no default platform; pass platform_override."
        )

    def cell(row: pd.Series, field: str) -> object:
        header = resolved.get(field)
        return row[header] if header is not None else None

    accounts: dict[str, AccountRecord] = {}
    posts: list[PostRecord] = []
    metrics: list[MetricSnapshotRecord] = []
    now = as_of or datetime.now(tz=_STORAGE_TZ)

    for _, row in df.iterrows():
        acct_ext = (
            (str(cell(row, "account_external_id")) if cell(row, "account_external_id") is not None else None)
            or default_account_external_id
        )
        if acct_ext is None or acct_ext == "nan":
            # No account id anywhere: skip. Caller should pass a default for exports
            # that omit the page id.
            log.warning("csv_row_missing_account", profile=profile["id"])
            continue

        if acct_ext not in accounts:
            handle = cell(row, "account_handle")
            name = cell(row, "account_name") or default_account_name
            accounts[acct_ext] = AccountRecord(
                platform=platform,
                external_id=acct_ext,
                handle=str(handle) if handle is not None and not pd.isna(handle) else None,
                display_name=str(name) if name is not None and not pd.isna(name) else None,
            )

        published_at = _to_utc(cell(row, "published_at"))
        if published_at is None:
            log.warning("csv_row_unparseable_time", profile=profile["id"])
            continue

        ext_id = cell(row, "external_id")
        # If the export has no per-post id, synthesize a stable one from account+time.
        if ext_id is None or pd.isna(ext_id):
            ext_id = f"{acct_ext}:{published_at.isoformat()}"
        else:
            ext_id = str(ext_id)

        text = cell(row, "text_content")
        posts.append(
            PostRecord(
                account_external_id=acct_ext,
                platform=platform,
                external_id=ext_id,
                published_at=published_at,
                content_type=(str(cell(row, "content_type")) if cell(row, "content_type") is not None and not pd.isna(cell(row, "content_type")) else None),
                text_content=(str(text) if text is not None and not pd.isna(text) else None),
                permalink=(str(cell(row, "permalink")) if cell(row, "permalink") is not None and not pd.isna(cell(row, "permalink")) else None),
                is_synthetic=is_synthetic,
            )
        )

        # The CSV is a single point-in-time export, so it yields one snapshot per post.
        metrics.append(
            MetricSnapshotRecord(
                post_external_id=ext_id,
                account_external_id=acct_ext,
                platform=platform,
                captured_at=now,
                likes=_to_int(cell(row, "likes")) or 0,
                comments_count=_to_int(cell(row, "comments_count")) or 0,
                shares=_to_int(cell(row, "shares")) or 0,
                saves=_to_int(cell(row, "saves")) or 0,
                reach=_to_int(cell(row, "reach")),
                impressions=_to_int(cell(row, "impressions")),
                video_views=_to_int(cell(row, "video_views")),
                clicks=_to_int(cell(row, "clicks")),
            )
        )

    return list(accounts.values()), posts, metrics


def import_csv_bytes(
    session: Session,
    content: bytes,
    profile_id: str | None = None,
    *,
    platform_override: str | None = None,
    default_account_external_id: str | None = None,
    default_account_name: str | None = None,
    as_of: datetime | None = None,
) -> IngestionResult:
    """Parse raw CSV bytes and store idempotently. Caller controls the transaction."""
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # pragma: no cover - pandas raises many types
        raise CSVImportError(f"Could not parse CSV: {exc}") from exc

    accounts, posts, metrics = parse_dataframe(
        df,
        profile_id,
        platform_override=platform_override,
        default_account_external_id=default_account_external_id,
        default_account_name=default_account_name,
        as_of=as_of,
    )
    return normalize_and_store(
        session,
        source="csv",
        accounts=accounts,
        posts=posts,
        metrics=metrics,
    )
