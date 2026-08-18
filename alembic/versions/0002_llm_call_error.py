"""add llm_calls.error

Revision ID: 0002_llm_call_error
Revises: 0001_initial
Create Date: 2026-08-18

A failed provider attempt recorded only status='error', so diagnosing why a
failover happened meant grepping container logs. Real causes seen in practice (a
provider retiring a model, a free-tier rate limit) are distinguishable only from
the provider's message, so it is stored on the row and truncated to 500 chars.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_llm_call_error"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "error")
