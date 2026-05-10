"""M2 brain tables: candidate_claims + decisions + theses + target_wallets.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NUMERIC_24_8 = sa.Numeric(precision=24, scale=8)


def upgrade() -> None:
    # theses (created first; decisions has FK)
    op.create_table(
        "theses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot", sa.String(16), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(128), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("p_win", NUMERIC_24_8, nullable=False),
        sa.Column("confidence", NUMERIC_24_8, nullable=False),
        sa.Column("size_multiplier", sa.String(8), nullable=False),
        sa.Column("target_price", NUMERIC_24_8, nullable=True),
        sa.Column("stop_price", NUMERIC_24_8, nullable=True),
        sa.Column("horizon_hours", sa.Integer, nullable=True),
        sa.Column("scan_correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "decision_correlation_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_theses_bot_venue_created", "theses", ["bot", "venue", "created_at"])
    op.create_index("ix_theses_pending", "theses", ["bot", "executed_at"])

    op.create_table(
        "candidate_claims",
        sa.Column(
            "scan_correlation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidate_queue.scan_correlation_id"),
            nullable=False,
        ),
        sa.Column("bot", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "decision_correlation_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("scan_correlation_id", "bot", name="pk_candidate_claims"),
    )
    op.create_index("ix_candidate_claims_bot_status", "candidate_claims", ["bot", "status"])

    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bot", sa.String(16), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("market_id", sa.String(128), nullable=False),
        sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("sub_agent", sa.String(32), nullable=True),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("confidence", NUMERIC_24_8, nullable=False),
        sa.Column("p_win", NUMERIC_24_8, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_cached", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", NUMERIC_24_8, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("web_search_used", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_response", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "thesis_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("theses.id"), nullable=True
        ),
    )
    op.create_index("ix_decisions_bot_venue_created", "decisions", ["bot", "venue", "created_at"])
    op.create_index("ix_decisions_correlation", "decisions", ["correlation_id"])
    op.create_index("ix_decisions_thesis_id", "decisions", ["thesis_id"])

    op.create_table(
        "target_wallets",
        sa.Column("address", sa.String(64), primary_key=True),
        sa.Column("total_trades", sa.Integer, nullable=False),
        sa.Column("win_rate", NUMERIC_24_8, nullable=False),
        sa.Column("total_pnl", NUMERIC_24_8, nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("target_wallets")
    op.drop_index("ix_decisions_thesis_id", table_name="decisions")
    op.drop_index("ix_decisions_correlation", table_name="decisions")
    op.drop_index("ix_decisions_bot_venue_created", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_candidate_claims_bot_status", table_name="candidate_claims")
    op.drop_table("candidate_claims")
    op.drop_index("ix_theses_pending", table_name="theses")
    op.drop_index("ix_theses_bot_venue_created", table_name="theses")
    op.drop_table("theses")
