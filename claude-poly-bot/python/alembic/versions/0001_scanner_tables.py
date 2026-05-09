"""Initial scanner tables: candidate_queue + market_scans.

Revision ID: 0001
Revises:
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_queue",
        sa.Column("scan_correlation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(128), nullable=False),
        sa.Column("market_snapshot", sa.JSON, nullable=False),
        sa.Column("book_snapshot", sa.JSON, nullable=True),
        sa.Column("scan_score", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_candidate_queue_venue_created", "candidate_queue", ["venue", "created_at"])

    op.create_table(
        "market_scans",
        sa.Column("scan_correlation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched", sa.Integer, nullable=False),
        sa.Column("accepted", sa.Integer, nullable=False),
        sa.Column("rejected", sa.Integer, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_market_scans_venue_started", "market_scans", ["venue", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_market_scans_venue_started", table_name="market_scans")
    op.drop_table("market_scans")
    op.drop_index("ix_candidate_queue_venue_created", table_name="candidate_queue")
    op.drop_table("candidate_queue")
