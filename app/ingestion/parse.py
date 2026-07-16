"""Small shared parsing helpers for the live connectors. Pure, no I/O."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def to_int(value: object) -> int | None:
    """Best-effort int from strings the APIs return (counts come back as strings)."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            return int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


_TZ_NO_COLON_RE = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_iso_dt(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp into aware UTC, else None.

    Handles both YouTube's trailing ``Z`` and Meta's colon-less offset (``+0000``),
    which older Python fromisoformat rejects.
    """
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = _TZ_NO_COLON_RE.sub(r"\1:\2", v)  # +0000 -> +00:00
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_duration_seconds(value: str | None) -> int | None:
    """Seconds from an ISO 8601 duration like 'PT1M30S'. None if unparseable."""
    if not value:
        return None
    m = _DURATION_RE.fullmatch(value)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def chunked(items: Iterable[str], size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
