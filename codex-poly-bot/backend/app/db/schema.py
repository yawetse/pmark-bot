"""Postgres schema metadata and migration plan.

REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
REQ-DB-006, REQ-DB-008, REQ-ALP-017, REQ-ALP-018, REQ-EXE-016, REQ-OBS-003,
REQ-OBS-004, REQ-UI-014, REQ-DB-010
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import CreateIndex, CreateSchema, CreateTable

from app.domain import ModelProvider


SHARED_SCHEMA = "shared"
MODEL_SCHEMAS = {
    ModelProvider.CLAUDE: "claude",
    ModelProvider.OPENAI: "openai",
}
REQUIRED_SCHEMAS = (SHARED_SCHEMA, "claude", "openai")

metadata = MetaData()
_POSTGRES_DIALECT = postgresql.dialect()


@dataclass(frozen=True)
class MigrationPlan:
    """Serializable migration plan for local and CI validation."""

    schema_names: tuple[str, ...]
    table_names: tuple[str, ...]
    sql: tuple[str, ...]


@dataclass(frozen=True)
class RetentionPolicy:
    """History retention policy.

    `None` means retain indefinitely.

    REQ: REQ-DB-006
    """

    audit_delete_after_days: int | None
    trade_delete_after_days: int | None
    position_delete_after_days: int | None


def provider_schema(provider: ModelProvider) -> str:
    """Return schema name for provider-specific records.

    REQ: REQ-DB-002
    """

    return MODEL_SCHEMAS[provider]


def retention_policy() -> RetentionPolicy:
    """Return v1 indefinite retention settings.

    REQ: REQ-DB-006
    """

    return RetentionPolicy(
        audit_delete_after_days=None,
        trade_delete_after_days=None,
        position_delete_after_days=None,
    )


def _shared_tables() -> list[Table]:
    return [
        Table(
            "config_versions",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("username", String, nullable=False, server_default=text("'__shared__'")),
            Column("version", String, nullable=False),
            Column("active", Boolean, nullable=False),
            Column("payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "environment",
                "username",
                "version",
                name="uq_config_environment_username_version",
            ),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "audit_events",
            metadata,
            Column("id", String, primary_key=True),
            Column("event_type", String, nullable=False),
            Column("actor", String, nullable=False),
            Column("action", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("entity_id", String, nullable=True),
            Column("success", Boolean, nullable=False),
            Column("metadata", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "system_health",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=True),
            Column("component", String, nullable=False),
            Column("status", String, nullable=False),
            Column("message", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "job_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("job_name", String, nullable=False),
            Column("status", String, nullable=False),
            Column("heartbeat_at", DateTime(timezone=True), nullable=True),
            Column("metadata", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_account_registry",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint(
                "environment",
                "account_mode",
                "account_id",
                name="uq_alpaca_env_mode_account",
            ),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "comparison_metric_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("metric_name", String, nullable=False),
            Column("metric_value", Numeric(18, 8), nullable=True),
            Column("unavailable_reason", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "user_preferences",
            metadata,
            Column("id", String, primary_key=True),
            Column("username", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("payload", JSONB, nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "dashboard_market_data_pulls",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("status", String, nullable=False),
            Column("trigger", String, nullable=False),
            Column("source", String, nullable=False),
            Column("candidates", JSONB, nullable=False),
            Column("message", String, nullable=False),
            Column("error_code", String, nullable=True),
            Column("run_id", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "scanner_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("config", JSONB, nullable=False),
            Column("source_pull_ids", JSONB, nullable=False),
            Column("accepted_count", Integer, nullable=False),
            Column("rejected_count", Integer, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "scanner_candidates",
            metadata,
            Column("id", String, primary_key=True),
            Column("scanner_run_id", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("display_name", String, nullable=False),
            Column("symbol", String, nullable=True),
            Column("market_id", String, nullable=True),
            Column("outcome_id", String, nullable=True),
            Column("status", String, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("strategy_names", JSONB, nullable=False),
            Column("price", Numeric(18, 8), nullable=True),
            Column("liquidity", Numeric(18, 8), nullable=True),
            Column("spread", Numeric(18, 8), nullable=True),
            Column("hours_to_resolution", Numeric(18, 8), nullable=True),
            Column("metrics", JSONB, nullable=False),
            Column("source_payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "reasoning_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("scanner_run_id", String, nullable=True),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("config", JSONB, nullable=False),
            Column("provider_count", Integer, nullable=False),
            Column("prompt_count", Integer, nullable=False),
            Column("scored_count", Integer, nullable=False),
            Column("skipped_count", Integer, nullable=False),
            Column("failed_count", Integer, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "reasoning_outputs",
            metadata,
            Column("id", String, primary_key=True),
            Column("reasoning_run_id", String, nullable=False),
            Column("scanner_candidate_id", String, nullable=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("prompt_version", String, nullable=False),
            Column("status", String, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("directional_signal", String, nullable=False),
            Column("signal_strength", Numeric(18, 8), nullable=False),
            Column("confidence", Numeric(18, 8), nullable=True),
            Column("estimated_probability", Numeric(18, 8), nullable=True),
            Column("cost_usd", Numeric(18, 8), nullable=False),
            Column("prompt_tokens", Integer, nullable=False),
            Column("completion_tokens", Integer, nullable=False),
            Column("total_tokens", Integer, nullable=False),
            Column("prompt_payload", JSONB, nullable=False),
            Column("response_payload", JSONB, nullable=False),
            Column("check_results", JSONB, nullable=False),
            Column("output_thesis", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "strategy_consensus_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("reasoning_run_id", String, nullable=True),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("config", JSONB, nullable=False),
            Column("vote_count", Integer, nullable=False),
            Column("approved_count", Integer, nullable=False),
            Column("refused_count", Integer, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "strategy_votes",
            metadata,
            Column("id", String, primary_key=True),
            Column("consensus_run_id", String, nullable=False),
            Column("reasoning_output_id", String, nullable=True),
            Column("scanner_candidate_id", String, nullable=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("strategy_name", String, nullable=False),
            Column("direction", String, nullable=True),
            Column("confidence", Numeric(18, 8), nullable=True),
            Column("status", String, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("inputs_hash", String, nullable=True),
            Column("source_payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "strategy_consensus_outputs",
            metadata,
            Column("id", String, primary_key=True),
            Column("consensus_run_id", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("status", String, nullable=False),
            Column("side", String, nullable=True),
            Column("size_multiplier", Numeric(18, 8), nullable=False),
            Column("signal_count", Integer, nullable=False),
            Column("strategy_names", JSONB, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("source_payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "execution_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("strategy_consensus_run_id", String, nullable=True),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("config", JSONB, nullable=False),
            Column("intent_count", Integer, nullable=False),
            Column("submitted_count", Integer, nullable=False),
            Column("simulated_count", Integer, nullable=False),
            Column("refused_count", Integer, nullable=False),
            Column("reconciliation_count", Integer, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "order_intents",
            metadata,
            Column("id", String, primary_key=True),
            Column("execution_run_id", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("strategy_consensus_output_id", String, nullable=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("side", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("status", String, nullable=False),
            Column("notional_usd", Numeric(18, 8), nullable=False),
            Column("size_multiplier", Numeric(18, 8), nullable=False),
            Column("idempotency_key", String, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("venue_order_id", String, nullable=True),
            Column("risk_payload", JSONB, nullable=False),
            Column("source_payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("idempotency_key", name="uq_shared_order_intent_idempotency"),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "exit_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("config", JSONB, nullable=False),
            Column("open_position_count", Integer, nullable=False),
            Column("triggered_count", Integer, nullable=False),
            Column("simulated_count", Integer, nullable=False),
            Column("submitted_count", Integer, nullable=False),
            Column("refused_count", Integer, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "exit_intents",
            metadata,
            Column("id", String, primary_key=True),
            Column("exit_run_id", String, nullable=False),
            Column("pipeline_run_id", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("position_id", String, nullable=False),
            Column("model_provider", String, nullable=True),
            Column("trigger_type", String, nullable=False),
            Column("status", String, nullable=False),
            Column("side", String, nullable=False),
            Column("quantity", Numeric(18, 8), nullable=True),
            Column("notional_usd", Numeric(18, 8), nullable=False),
            Column("threshold", Numeric(18, 8), nullable=True),
            Column("observed_value", Numeric(18, 8), nullable=True),
            Column("idempotency_key", String, nullable=False),
            Column("refusal_reason", String, nullable=True),
            Column("venue_order_id", String, nullable=True),
            Column("source_payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("idempotency_key", name="uq_shared_exit_intent_idempotency"),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "pipeline_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("trigger", String, nullable=False),
            Column("status", String, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=True),
            Column("metadata", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "pipeline_steps",
            metadata,
            Column("id", String, primary_key=True),
            Column("run_id", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("step_key", String, nullable=False),
            Column("step_order", Integer, nullable=False),
            Column("label", String, nullable=False),
            Column("status", String, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=True),
            Column("message", String, nullable=True),
            Column("metrics", JSONB, nullable=False),
            Column("record_ids", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "tick_summaries",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("window_minutes", Integer, nullable=False),
            Column("window_started_at", DateTime(timezone=True), nullable=False),
            Column("window_ended_at", DateTime(timezone=True), nullable=False),
            Column("latest_run_id", String, nullable=True),
            Column("run_count", Integer, nullable=False),
            Column("status", String, nullable=False),
            Column("model", String, nullable=False),
            Column("prompt_version", String, nullable=False),
            Column("input_hash", String, nullable=False),
            Column("summary_markdown", String, nullable=False),
            Column("key_events", JSONB, nullable=False),
            Column("warnings", JSONB, nullable=False),
            Column("usage", JSONB, nullable=False),
            Column("error_code", String, nullable=True),
            Column("message", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "economics_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("month_key", String, nullable=False),
            Column("trading_realized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("trading_unrealized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("trading_total_pnl_usd", Numeric(18, 8), nullable=False),
            Column("ai_cost_usd", Numeric(18, 8), nullable=False),
            Column("ai_prompt_tokens", Integer, nullable=False),
            Column("ai_completion_tokens", Integer, nullable=False),
            Column("ai_total_tokens", Integer, nullable=False),
            Column("aws_daily_cost_usd", Numeric(18, 8), nullable=False),
            Column("aws_month_to_date_cost_usd", Numeric(18, 8), nullable=False),
            Column("aws_source", String, nullable=False),
            Column("aws_scope", String, nullable=False),
            Column("aws_estimated", Boolean, nullable=False),
            Column("net_after_costs_usd", Numeric(18, 8), nullable=False),
            Column("profitability_status", String, nullable=False),
            Column("payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "ai_usage_events",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("provider", String, nullable=False),
            Column("model", String, nullable=True),
            Column("pipeline_run_id", String, nullable=True),
            Column("pipeline_step", String, nullable=True),
            Column("candidate_id", String, nullable=True),
            Column("prompt_tokens", Integer, nullable=False),
            Column("completion_tokens", Integer, nullable=False),
            Column("cost_usd", Numeric(18, 8), nullable=False),
            Column("usage_source", String, nullable=False),
            Column("cost_source", String, nullable=False),
            Column("response_id", String, nullable=True),
            Column("raw_payload", JSONB, nullable=False),
            Column("imported_at", DateTime(timezone=True), nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "ai_usage_import_runs",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("provider", String, nullable=False),
            Column("status", String, nullable=False),
            Column("source", String, nullable=False),
            Column("period_start", DateTime(timezone=True), nullable=True),
            Column("period_end", DateTime(timezone=True), nullable=True),
            Column("imported_count", Integer, nullable=False),
            Column("error_code", String, nullable=True),
            Column("message", String, nullable=False),
            Column("metadata", JSONB, nullable=False),
            Column("started_at", DateTime(timezone=True), nullable=False),
            Column("completed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_gamma_markets",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("market_id", String, nullable=False),
            Column("condition_id", String, nullable=True),
            Column("slug", String, nullable=True),
            Column("question", String, nullable=False),
            Column("active", Boolean, nullable=False),
            Column("closed", Boolean, nullable=False),
            Column("category", String, nullable=True),
            Column("end_date", DateTime(timezone=True), nullable=True),
            Column("tokens", JSONB, nullable=False),
            Column("tags", JSONB, nullable=False),
            Column("raw_payload", JSONB, nullable=False),
            Column("fetched_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_chain_fill_events",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("exchange_contract", String, nullable=False),
            Column("block_number", Integer, nullable=False),
            Column("block_hash", String, nullable=True),
            Column("log_index", Integer, nullable=False),
            Column("transaction_hash", String, nullable=False),
            Column("maker_address", String, nullable=True),
            Column("taker_address", String, nullable=True),
            Column("asset_id", String, nullable=True),
            Column("market_id", String, nullable=True),
            Column("raw_event", JSONB, nullable=False),
            Column("block_timestamp", DateTime(timezone=True), nullable=True),
            Column("decoded_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_trades",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("market_id", String, nullable=False),
            Column("condition_id", String, nullable=True),
            Column("asset_id", String, nullable=False),
            Column("wallet_address", String, nullable=False),
            Column("side", String, nullable=False),
            Column("price", Numeric(18, 8), nullable=False),
            Column("size", Numeric(18, 8), nullable=False),
            Column("notional_usd", Numeric(18, 8), nullable=False),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("outcome", String, nullable=True),
            Column("role", String, nullable=True),
            Column("transaction_hash", String, nullable=False),
            Column("block_number", Integer, nullable=False),
            Column("raw_event_id", String, nullable=True),
            Column("market_record_id", String, nullable=True),
            Column("traded_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_wallet_positions",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("wallet_address", String, nullable=False),
            Column("market_id", String, nullable=False),
            Column("asset_id", String, nullable=False),
            Column("outcome", String, nullable=True),
            Column("state", String, nullable=False),
            Column("entry_price", Numeric(18, 8), nullable=True),
            Column("exit_price", Numeric(18, 8), nullable=True),
            Column("size", Numeric(18, 8), nullable=False),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("opened_at", DateTime(timezone=True), nullable=True),
            Column("closed_at", DateTime(timezone=True), nullable=True),
            Column("trade_ids", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_wallet_performance_stats",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("wallet_address", String, nullable=False),
            Column("trade_count", Integer, nullable=False),
            Column("win_rate", Numeric(18, 8), nullable=False),
            Column("total_realized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("average_hold_seconds", Integer, nullable=True),
            Column("source", String, nullable=False),
            Column("calculated_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "polymarket_target_wallet_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("min_trade_count", Integer, nullable=False),
            Column("min_win_rate", Numeric(18, 8), nullable=False),
            Column("wallet_count", Integer, nullable=False),
            Column("wallets", JSONB, nullable=False),
            Column("source_stat_ids", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "historical_import_checkpoints",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("source", String, nullable=False),
            Column("cursor_type", String, nullable=False),
            Column("cursor_value", String, nullable=False),
            Column("status", String, nullable=False),
            Column("metadata", JSONB, nullable=False),
            Column("last_success_at", DateTime(timezone=True), nullable=True),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_symbol_preset_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("preset_name", String, nullable=False),
            Column("status", String, nullable=False),
            Column("source", String, nullable=False),
            Column("source_url", String, nullable=True),
            Column("symbols", JSONB, nullable=False),
            Column("symbol_count", Integer, nullable=False),
            Column("effective_at", DateTime(timezone=True), nullable=False),
            Column("refreshed_at", DateTime(timezone=True), nullable=False),
            Column("message", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_historical_orders",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("order_id", String, nullable=False),
            Column("client_order_id", String, nullable=True),
            Column("symbol", String, nullable=False),
            Column("side", String, nullable=False),
            Column("order_type", String, nullable=True),
            Column("status", String, nullable=False),
            Column("quantity", Numeric(18, 8), nullable=True),
            Column("filled_quantity", Numeric(18, 8), nullable=True),
            Column("filled_avg_price", Numeric(18, 8), nullable=True),
            Column("notional", Numeric(18, 8), nullable=True),
            Column("submitted_at", DateTime(timezone=True), nullable=True),
            Column("filled_at", DateTime(timezone=True), nullable=True),
            Column("canceled_at", DateTime(timezone=True), nullable=True),
            Column("raw_payload", JSONB, nullable=False),
            Column("imported_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_historical_fills",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("activity_id", String, nullable=False),
            Column("order_id", String, nullable=True),
            Column("symbol", String, nullable=False),
            Column("side", String, nullable=False),
            Column("quantity", Numeric(18, 8), nullable=False),
            Column("price", Numeric(18, 8), nullable=False),
            Column("notional", Numeric(18, 8), nullable=False),
            Column("filled_at", DateTime(timezone=True), nullable=False),
            Column("raw_payload", JSONB, nullable=False),
            Column("imported_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_historical_positions",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("quantity", Numeric(18, 8), nullable=False),
            Column("average_entry_price", Numeric(18, 8), nullable=True),
            Column("cost_basis", Numeric(18, 8), nullable=True),
            Column("market_value", Numeric(18, 8), nullable=True),
            Column("current_price", Numeric(18, 8), nullable=True),
            Column("unrealized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("raw_payload", JSONB, nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_broker_account_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("account_status", String, nullable=False),
            Column("buying_power", Numeric(18, 8), nullable=True),
            Column("cash", Numeric(18, 8), nullable=True),
            Column("portfolio_value", Numeric(18, 8), nullable=True),
            Column("equity", Numeric(18, 8), nullable=True),
            Column("raw_payload", JSONB, nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "stock_bars",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("timeframe", String, nullable=False),
            Column("bar_start_at", DateTime(timezone=True), nullable=False),
            Column("open_price", Numeric(18, 8), nullable=False),
            Column("high_price", Numeric(18, 8), nullable=False),
            Column("low_price", Numeric(18, 8), nullable=False),
            Column("close_price", Numeric(18, 8), nullable=False),
            Column("volume", Numeric(24, 8), nullable=False),
            Column("trade_count", Integer, nullable=True),
            Column("vwap", Numeric(18, 8), nullable=True),
            Column("source", String, nullable=False),
            Column("raw_payload", JSONB, nullable=False),
            Column("imported_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "alpaca_symbol_pnl_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("open_quantity", Numeric(18, 8), nullable=False),
            Column("average_entry_price", Numeric(18, 8), nullable=True),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("unrealized_pnl_usd", Numeric(18, 8), nullable=False),
            Column("total_pnl_usd", Numeric(18, 8), nullable=False),
            Column("cost_basis", Numeric(18, 8), nullable=False),
            Column("market_value", Numeric(18, 8), nullable=True),
            Column("fill_ids", JSONB, nullable=False),
            Column("position_id", String, nullable=True),
            Column("calculated_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "venue_portfolio_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("account_ref", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("status", String, nullable=False),
            Column("cash_usd", Numeric(18, 8), nullable=True),
            Column("buying_power_usd", Numeric(18, 8), nullable=True),
            Column("account_value_usd", Numeric(18, 8), nullable=True),
            Column("cost_basis_usd", Numeric(18, 8), nullable=True),
            Column("market_value_usd", Numeric(18, 8), nullable=True),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("unrealized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("total_pnl_usd", Numeric(18, 8), nullable=True),
            Column("open_position_count", Integer, nullable=False),
            Column("filled_trade_count", Integer, nullable=False),
            Column("message", String, nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "venue_position_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("portfolio_snapshot_id", String, nullable=False),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("account_ref", String, nullable=False),
            Column("instrument_id", String, nullable=False),
            Column("title", String, nullable=False),
            Column("outcome", String, nullable=True),
            Column("quantity", Numeric(24, 8), nullable=False),
            Column("average_entry_price", Numeric(18, 8), nullable=True),
            Column("current_price", Numeric(18, 8), nullable=True),
            Column("cost_basis_usd", Numeric(18, 8), nullable=True),
            Column("market_value_usd", Numeric(18, 8), nullable=True),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("unrealized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("total_pnl_usd", Numeric(18, 8), nullable=True),
            Column("state", String, nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "venue_confirmed_fills",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("providers", JSONB, nullable=False),
            Column("account_ref", String, nullable=False),
            Column("source_trade_id", String, nullable=False),
            Column("venue_order_id", String, nullable=True),
            Column("instrument_id", String, nullable=False),
            Column("title", String, nullable=False),
            Column("side", String, nullable=False),
            Column("quantity", Numeric(24, 8), nullable=False),
            Column("price", Numeric(18, 8), nullable=False),
            Column("notional_usd", Numeric(18, 8), nullable=False),
            Column("realized_pnl_usd", Numeric(18, 8), nullable=True),
            Column("fee_usd", Numeric(18, 8), nullable=True),
            Column("state", String, nullable=False),
            Column("executed_at", DateTime(timezone=True), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
    ]


def _provider_tables(schema: str) -> list[Table]:
    return [
        Table(
            "trade_decisions",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_identifier", String, nullable=False),
            Column("instrument_type", String, nullable=False),
            Column("signal_inputs", JSONB, nullable=False),
            Column("decision", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("size", Numeric(18, 8), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "positions",
            metadata,
            Column("position_id", String, primary_key=True),
            Column("state", String, nullable=False),
            Column("realized_pnl", Numeric(18, 8), nullable=False),
            Column("unrealized_pnl", Numeric(18, 8), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "order_intents",
            metadata,
            Column("idempotency_key", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("instrument_identifier", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("status", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "strategy_signals",
            metadata,
            Column("id", String, primary_key=True),
            Column("strategy_name", String, nullable=False),
            Column("direction", String, nullable=False),
            Column("inputs_hash", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "position_events",
            metadata,
            Column("idempotency_key", String, primary_key=True),
            Column("position_id", String, nullable=False),
            Column("execution_mode", String, nullable=False),
            Column("prior_state", String, nullable=False),
            Column("new_state", String, nullable=False),
            Column("realized_pnl", Numeric(18, 8), nullable=False),
            Column("unrealized_pnl", Numeric(18, 8), nullable=False),
            Column("reason", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "order_events",
            metadata,
            Column("id", String, primary_key=True),
            Column("order_id", String, nullable=False),
            Column("event_type", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("model_provider", String, nullable=False),
            Column("message", String, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "alpaca_account_snapshots",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("configured_account_id", String, nullable=False),
            Column("broker_account_id", String, nullable=False),
            Column("account_status", String, nullable=False),
            Column("positions", JSONB, nullable=False),
            Column("open_orders", JSONB, nullable=False),
            Column("broker_positions", JSONB, nullable=False),
            Column("postgres_positions", JSONB, nullable=False),
            Column("broker_open_orders", JSONB, nullable=False),
            Column("postgres_open_orders", JSONB, nullable=False),
            Column("buying_power", Numeric(18, 8), nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("freshness_seconds", Integer, nullable=False),
            Column("mismatches", JSONB, nullable=False),
            Column("is_live_safe", Boolean, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
        Table(
            "alpaca_reconciliation_mismatches",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("account_mode", String, nullable=False),
            Column("account_id", String, nullable=False),
            Column("mismatch_reason", String, nullable=False),
            Column("mismatch_details", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=schema,
        ),
    ]


_ALL_TABLES = _shared_tables()
for _schema_name in MODEL_SCHEMAS.values():
    _ALL_TABLES.extend(_provider_tables(_schema_name))

Index(
    "ix_audit_events_environment_created_at",
    metadata.tables["shared.audit_events"].c.environment,
    metadata.tables["shared.audit_events"].c.created_at,
)

Index(
    "ix_economics_snapshots_environment_month_created_at",
    metadata.tables["shared.economics_snapshots"].c.environment,
    metadata.tables["shared.economics_snapshots"].c.month_key,
    metadata.tables["shared.economics_snapshots"].c.created_at,
)

Index(
    "ix_ai_usage_events_environment_provider_created_at",
    metadata.tables["shared.ai_usage_events"].c.environment,
    metadata.tables["shared.ai_usage_events"].c.provider,
    metadata.tables["shared.ai_usage_events"].c.created_at,
)

Index(
    "ix_ai_usage_import_runs_environment_provider_completed",
    metadata.tables["shared.ai_usage_import_runs"].c.environment,
    metadata.tables["shared.ai_usage_import_runs"].c.provider,
    metadata.tables["shared.ai_usage_import_runs"].c.completed_at,
)

Index(
    "ix_tick_summaries_environment_created_at",
    metadata.tables["shared.tick_summaries"].c.environment,
    metadata.tables["shared.tick_summaries"].c.created_at,
)

Index(
    "ix_job_runs_job_name_created_at",
    metadata.tables["shared.job_runs"].c.job_name,
    metadata.tables["shared.job_runs"].c.created_at,
)

Index(
    "ix_dashboard_market_data_pulls_environment_venue_created_at",
    metadata.tables["shared.dashboard_market_data_pulls"].c.environment,
    metadata.tables["shared.dashboard_market_data_pulls"].c.venue,
    metadata.tables["shared.dashboard_market_data_pulls"].c.created_at,
)

Index(
    "ix_pipeline_runs_environment_created_at",
    metadata.tables["shared.pipeline_runs"].c.environment,
    metadata.tables["shared.pipeline_runs"].c.created_at,
)

Index(
    "ix_pipeline_steps_environment_created_at",
    metadata.tables["shared.pipeline_steps"].c.environment,
    metadata.tables["shared.pipeline_steps"].c.created_at,
)

Index(
    "ix_pipeline_steps_environment_run_step_created_at",
    metadata.tables["shared.pipeline_steps"].c.environment,
    metadata.tables["shared.pipeline_steps"].c.run_id,
    metadata.tables["shared.pipeline_steps"].c.step_key,
    metadata.tables["shared.pipeline_steps"].c.created_at,
)

Index(
    "ix_scanner_runs_environment_created_at",
    metadata.tables["shared.scanner_runs"].c.environment,
    metadata.tables["shared.scanner_runs"].c.created_at,
)

Index(
    "ix_polymarket_gamma_markets_environment_market_id",
    metadata.tables["shared.polymarket_gamma_markets"].c.environment,
    metadata.tables["shared.polymarket_gamma_markets"].c.market_id,
)

Index(
    "ix_polymarket_chain_fill_events_environment_block_log",
    metadata.tables["shared.polymarket_chain_fill_events"].c.environment,
    metadata.tables["shared.polymarket_chain_fill_events"].c.block_number,
    metadata.tables["shared.polymarket_chain_fill_events"].c.log_index,
)

Index(
    "ix_polymarket_trades_environment_wallet_traded_at",
    metadata.tables["shared.polymarket_trades"].c.environment,
    metadata.tables["shared.polymarket_trades"].c.wallet_address,
    metadata.tables["shared.polymarket_trades"].c.traded_at,
)

Index(
    "ix_polymarket_wallet_performance_environment_calculated_at",
    metadata.tables["shared.polymarket_wallet_performance_stats"].c.environment,
    metadata.tables["shared.polymarket_wallet_performance_stats"].c.calculated_at,
)

Index(
    "ix_historical_import_checkpoints_environment_source",
    metadata.tables["shared.historical_import_checkpoints"].c.environment,
    metadata.tables["shared.historical_import_checkpoints"].c.source,
)

Index(
    "ix_alpaca_symbol_preset_snapshots_environment_preset_refreshed",
    metadata.tables["shared.alpaca_symbol_preset_snapshots"].c.environment,
    metadata.tables["shared.alpaca_symbol_preset_snapshots"].c.preset_name,
    metadata.tables["shared.alpaca_symbol_preset_snapshots"].c.refreshed_at,
)

Index(
    "ix_scanner_runs_environment_started_at",
    metadata.tables["shared.scanner_runs"].c.environment,
    metadata.tables["shared.scanner_runs"].c.started_at,
)

Index(
    "ix_scanner_candidates_environment_venue_status",
    metadata.tables["shared.scanner_candidates"].c.environment,
    metadata.tables["shared.scanner_candidates"].c.venue,
    metadata.tables["shared.scanner_candidates"].c.status,
)

Index(
    "ix_scanner_candidates_environment_run_created_at",
    metadata.tables["shared.scanner_candidates"].c.environment,
    metadata.tables["shared.scanner_candidates"].c.scanner_run_id,
    metadata.tables["shared.scanner_candidates"].c.created_at,
)

Index(
    "ix_reasoning_runs_environment_started_at",
    metadata.tables["shared.reasoning_runs"].c.environment,
    metadata.tables["shared.reasoning_runs"].c.started_at,
)

Index(
    "ix_reasoning_outputs_environment_run_provider",
    metadata.tables["shared.reasoning_outputs"].c.environment,
    metadata.tables["shared.reasoning_outputs"].c.reasoning_run_id,
    metadata.tables["shared.reasoning_outputs"].c.model_provider,
)

Index(
    "ix_strategy_consensus_runs_environment_started_at",
    metadata.tables["shared.strategy_consensus_runs"].c.environment,
    metadata.tables["shared.strategy_consensus_runs"].c.started_at,
)

Index(
    "ix_strategy_votes_environment_run_provider",
    metadata.tables["shared.strategy_votes"].c.environment,
    metadata.tables["shared.strategy_votes"].c.consensus_run_id,
    metadata.tables["shared.strategy_votes"].c.model_provider,
)

Index(
    "ix_strategy_consensus_outputs_environment_run_provider",
    metadata.tables["shared.strategy_consensus_outputs"].c.environment,
    metadata.tables["shared.strategy_consensus_outputs"].c.consensus_run_id,
    metadata.tables["shared.strategy_consensus_outputs"].c.model_provider,
)

Index(
    "ix_execution_runs_environment_started_at",
    metadata.tables["shared.execution_runs"].c.environment,
    metadata.tables["shared.execution_runs"].c.started_at,
)

Index(
    "ix_order_intents_environment_execution_run_created_at",
    metadata.tables["shared.order_intents"].c.environment,
    metadata.tables["shared.order_intents"].c.execution_run_id,
    metadata.tables["shared.order_intents"].c.created_at,
)

Index(
    "ix_exit_runs_environment_started_at",
    metadata.tables["shared.exit_runs"].c.environment,
    metadata.tables["shared.exit_runs"].c.started_at,
)

Index(
    "ix_exit_intents_environment_exit_run_created_at",
    metadata.tables["shared.exit_intents"].c.environment,
    metadata.tables["shared.exit_intents"].c.exit_run_id,
    metadata.tables["shared.exit_intents"].c.created_at,
)

Index(
    "ix_alpaca_historical_orders_environment_symbol_submitted",
    metadata.tables["shared.alpaca_historical_orders"].c.environment,
    metadata.tables["shared.alpaca_historical_orders"].c.symbol,
    metadata.tables["shared.alpaca_historical_orders"].c.submitted_at,
)

Index(
    "ix_alpaca_historical_fills_environment_symbol_filled",
    metadata.tables["shared.alpaca_historical_fills"].c.environment,
    metadata.tables["shared.alpaca_historical_fills"].c.symbol,
    metadata.tables["shared.alpaca_historical_fills"].c.filled_at,
)

Index(
    "ix_stock_bars_environment_symbol_start",
    metadata.tables["shared.stock_bars"].c.environment,
    metadata.tables["shared.stock_bars"].c.symbol,
    metadata.tables["shared.stock_bars"].c.bar_start_at,
)

Index(
    "ix_alpaca_symbol_pnl_environment_symbol_calculated",
    metadata.tables["shared.alpaca_symbol_pnl_snapshots"].c.environment,
    metadata.tables["shared.alpaca_symbol_pnl_snapshots"].c.symbol,
    metadata.tables["shared.alpaca_symbol_pnl_snapshots"].c.calculated_at,
)

Index(
    "ix_venue_portfolio_environment_venue_observed",
    metadata.tables["shared.venue_portfolio_snapshots"].c.environment,
    metadata.tables["shared.venue_portfolio_snapshots"].c.venue,
    metadata.tables["shared.venue_portfolio_snapshots"].c.observed_at,
)

Index(
    "ix_venue_positions_environment_account_observed",
    metadata.tables["shared.venue_position_snapshots"].c.environment,
    metadata.tables["shared.venue_position_snapshots"].c.account_ref,
    metadata.tables["shared.venue_position_snapshots"].c.observed_at,
)

Index(
    "ix_venue_fills_environment_venue_executed",
    metadata.tables["shared.venue_confirmed_fills"].c.environment,
    metadata.tables["shared.venue_confirmed_fills"].c.venue,
    metadata.tables["shared.venue_confirmed_fills"].c.executed_at,
)


def _ddl(statement) -> str:
    return f"{str(statement.compile(dialect=_POSTGRES_DIALECT)).strip()};"


_DASHBOARD_EVENT_TABLE_NAMES = (
    "shared.config_versions",
    "shared.user_preferences",
    "shared.audit_events",
    "shared.system_health",
    "shared.job_runs",
    "shared.dashboard_market_data_pulls",
    "shared.scanner_runs",
    "shared.reasoning_runs",
    "shared.strategy_consensus_runs",
    "shared.execution_runs",
    "shared.order_intents",
    "shared.exit_runs",
    "shared.exit_intents",
    "shared.pipeline_runs",
    "shared.pipeline_steps",
    "shared.venue_portfolio_snapshots",
    "shared.venue_position_snapshots",
    "shared.venue_confirmed_fills",
)

_DASHBOARD_EVENT_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION shared.notify_dashboard_change()
RETURNS trigger
LANGUAGE plpgsql
AS $dashboard_event$
DECLARE
    row_data jsonb;
    event_environment text;
    event_username text;
BEGIN
    row_data := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    event_environment := COALESCE(
        row_data ->> 'environment',
        row_data #>> '{metadata,environment}'
    );
    IF event_environment IS NULL OR event_environment = '' THEN
        RETURN NULL;
    END IF;

    event_username := NULL;
    IF TG_TABLE_NAME IN ('config_versions', 'user_preferences') THEN
        event_username := NULLIF(row_data ->> 'username', '__shared__');
    ELSIF TG_TABLE_NAME = 'audit_events'
        AND COALESCE(row_data ->> 'action', '') <> 'kill_switch.activate' THEN
        event_username := NULLIF(row_data ->> 'actor', 'scheduler');
        event_username := NULLIF(event_username, 'system');
    END IF;

    PERFORM pg_notify(
        'codex_dashboard_events',
        json_build_object(
            'environment', event_environment,
            'username', event_username
        )::text
    );
    RETURN NULL;
END;
$dashboard_event$;
""".strip()


def _dashboard_event_trigger_sql(table_name: str) -> str:
    trigger_name = "notify_dashboard_change"
    return f"""
DO $dashboard_trigger$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = '{trigger_name}'
          AND tgrelid = '{table_name}'::regclass
    ) THEN
        CREATE TRIGGER {trigger_name}
        AFTER INSERT OR UPDATE OR DELETE ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION shared.notify_dashboard_change();
    END IF;
END;
$dashboard_trigger$;
""".strip()


def migration_plan() -> MigrationPlan:
    """Build SQL statements that create v1 schemas and tables.

    REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
    REQ-DB-008, REQ-DB-010
    """

    schema_sql = tuple(
        _ddl(CreateSchema(schema, if_not_exists=True))
        for schema in REQUIRED_SCHEMAS
    )
    table_sql = tuple(
        _ddl(CreateTable(table, if_not_exists=True))
        for table in _ALL_TABLES
    )
    index_sql = tuple(
        _ddl(CreateIndex(index, if_not_exists=True))
        for table in _ALL_TABLES
        for index in sorted(table.indexes, key=lambda current: current.name or "")
    )
    dashboard_event_sql = (
        _DASHBOARD_EVENT_FUNCTION_SQL,
        *(
            _dashboard_event_trigger_sql(table_name)
            for table_name in _DASHBOARD_EVENT_TABLE_NAMES
        ),
    )
    return MigrationPlan(
        schema_names=REQUIRED_SCHEMAS,
        table_names=tuple(f"{table.schema}.{table.name}" for table in _ALL_TABLES),
        sql=schema_sql + table_sql + index_sql + dashboard_event_sql,
    )


def run_migrations(connection=None) -> MigrationPlan:
    """Run migrations when a connection is supplied, otherwise return the plan.

    REQ: REQ-DB-002, REQ-DB-003
    """

    plan = migration_plan()
    if connection is not None:
        for statement in plan.sql:
            connection.execute(text(statement))
    return plan
