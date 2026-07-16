"""Ingestion request/response schemas (brief Section 12)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CSVImportResponse(BaseModel):
    source: str
    profile: str
    accounts_upserted: int
    posts_upserted: int
    snapshots_inserted: int
    comments_upserted: int
    rows_skipped: int
    skip_reasons: dict[str, int] = Field(default_factory=dict)


class ConnectorRunResponse(BaseModel):
    source: str
    accounts_upserted: int
    posts_upserted: int
    snapshots_inserted: int
    comments_upserted: int
    rows_skipped: int
    skip_reasons: dict[str, int] = Field(default_factory=dict)


class CursorStatus(BaseModel):
    source: str
    account_external_id: str
    entity_type: str
    cursor_value: datetime | None
    updated_at: datetime | None


class IngestionStatusResponse(BaseModel):
    row_counts: dict[str, int]  # table name -> row count
    cursors: list[CursorStatus]
