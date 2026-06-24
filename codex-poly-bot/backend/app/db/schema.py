"""Postgres schema metadata and migration plan.

REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
REQ-DB-006, REQ-ALP-017, REQ-ALP-018, REQ-EXE-016, REQ-OBS-003,
REQ-OBS-004
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
            Column("version", String, nullable=False),
            Column("active", Boolean, nullable=False),
            Column("payload", JSONB, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
            UniqueConstraint("environment", "version", name="uq_config_environment_version"),
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
            "market_data_pulls",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("venue", String, nullable=False),
            Column("status", String, nullable=False),
            Column("trigger", String, nullable=False),
            Column("source", String, nullable=False),
            Column("candidates", JSONB, nullable=False),
            Column("message", String, nullable=False),
            Column("run_id", String, nullable=True),
            Column("created_at", DateTime(timezone=True), nullable=False),
            schema=SHARED_SCHEMA,
        ),
        Table(
            "ai_usage_events",
            metadata,
            Column("id", String, primary_key=True),
            Column("environment", String, nullable=False),
            Column("provider", String, nullable=False),
            Column("prompt_tokens", Integer, nullable=False),
            Column("completion_tokens", Integer, nullable=False),
            Column("cost_usd", Numeric(18, 8), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
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


def _ddl(statement) -> str:
    return f"{str(statement.compile(dialect=_POSTGRES_DIALECT)).strip()};"


def migration_plan() -> MigrationPlan:
    """Build SQL statements that create v1 schemas and tables.

    REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005
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
    return MigrationPlan(
        schema_names=REQUIRED_SCHEMAS,
        table_names=tuple(f"{table.schema}.{table.name}" for table in _ALL_TABLES),
        sql=schema_sql + table_sql + index_sql,
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
