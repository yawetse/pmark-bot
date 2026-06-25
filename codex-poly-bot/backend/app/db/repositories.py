"""Repository contracts and local in-memory repository implementation.

REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
REQ-DB-007, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018, REQ-EXE-016,
REQ-OBS-003, REQ-OBS-004
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.domain import (
    Environment,
    ModelProvider,
    OrderEvent,
    OrderEventType,
    PositionTransition,
    TradeDecision,
)
from app.db.schema import MODEL_SCHEMAS, SHARED_SCHEMA, provider_schema


class PersistenceUnavailableError(RuntimeError):
    """Raised when persistence is unavailable for a live-sensitive path."""


class SchemaViolationError(ValueError):
    """Raised when a repository is used with the wrong schema."""


@dataclass
class DatabaseState:
    """Local repository state used by tests and dry-run development."""

    available: bool = True
    fail_on_tables: set[str] = field(default_factory=set)
    fail_on_read_tables: set[str] = field(default_factory=set)
    tables: dict[str, list[dict]] = field(default_factory=dict)

    def insert(self, table_name: str, row: dict) -> dict:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        self.tables.setdefault(table_name, []).append(row)
        return row

    def rows(self, table_name: str) -> list[dict]:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        return self.tables.setdefault(table_name, [])


@dataclass(frozen=True)
class PersistenceGate:
    """Live-order persistence gate result.

    REQ: REQ-DB-007
    """

    live_order_allowed: bool
    degraded: bool
    reason: str | None = None
    system_health: dict | None = None
    log_event: dict | None = None


def live_order_persistence_gate(state: DatabaseState) -> PersistenceGate:
    """Block live order placement when persistence is unavailable.

    REQ: REQ-DB-007
    """

    if state.available:
        return PersistenceGate(
            live_order_allowed=True,
            degraded=False,
            system_health={
                "component": "postgres",
                "status": "healthy",
                "message": "Postgres persistence is available",
            },
            log_event={
                "event_name": "postgres.persistence.available",
                "level": "info",
            },
        )
    reason = "Postgres persistence is unavailable"
    return PersistenceGate(
        live_order_allowed=False,
        degraded=True,
        reason=reason,
        system_health={
            "component": "postgres",
            "status": "degraded",
            "message": reason,
        },
        log_event={
            "event_name": "postgres.persistence.unavailable",
            "level": "error",
            "message": reason,
        },
    )


class UnitOfWork:
    """Transaction boundary placeholder for repository operations.

    REQ: REQ-DB-001, REQ-DB-007
    """

    def __init__(self, state: DatabaseState):
        self.state = state
        self.committed = False
        self.rolled_back = False
        self._snapshot: dict[str, list[dict]] | None = None

    def __enter__(self) -> UnitOfWork:
        if not self.state.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        self._snapshot = deepcopy(self.state.tables)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.rollback()

    def commit(self) -> None:
        if not self.state.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        self.committed = True

    def rollback(self) -> None:
        if self._snapshot is not None:
            self.state.tables = deepcopy(self._snapshot)
        self.rolled_back = True


@dataclass(frozen=True)
class AlpacaAccountRegistrationResult:
    """Duplicate Alpaca account validation result.

    REQ: REQ-ALP-016
    """

    live_trading_allowed: bool
    refusal_reason: str | None = None


@dataclass(frozen=True)
class AlpacaReconciliationSnapshot:
    """Alpaca account state snapshot for reconciliation.

    REQ: REQ-ALP-017, REQ-ALP-018
    """

    account_id: str
    positions: dict[str, Decimal]
    open_orders: tuple[str, ...]
    buying_power: Decimal
    completed: bool = True
    environment: Environment | None = None
    model_provider: ModelProvider | None = None
    account_mode: str | None = None
    configured_account_id: str | None = None
    broker_account_id: str | None = None
    account_status: str = "active"
    broker_positions: dict[str, Decimal] = field(default_factory=dict)
    postgres_positions: dict[str, Decimal] = field(default_factory=dict)
    broker_open_orders: tuple[str, ...] = ()
    postgres_open_orders: tuple[str, ...] = ()
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    freshness_seconds: int = 0
    mismatches: tuple[str, ...] = ()
    is_live_safe: bool = True


@dataclass(frozen=True)
class AlpacaReconciliationResult:
    """Result of comparing broker and persisted Alpaca state."""

    live_order_allowed: bool
    mismatch_reason: str | None = None
    mismatch_details: dict | None = None


@dataclass(frozen=True)
class OrderEventHandlingResult:
    """Persisted order event and shared audit row.

    REQ: REQ-EXE-016, REQ-OBS-003
    """

    order_event: dict
    audit_event: dict


def _json_ready(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class SharedRepositories:
    """Repositories for shared-schema records.

    REQ: REQ-DB-003, REQ-OBS-003, REQ-OBS-004
    """

    schema_name = SHARED_SCHEMA

    def __init__(self, state: DatabaseState):
        self.state = state

    def ensure_schema(self, schema_name: str) -> None:
        if schema_name != SHARED_SCHEMA:
            raise SchemaViolationError("shared records must use the shared schema")

    def record_config_version(self, *, environment: Environment, version: str, payload: dict, active: bool = True) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.config_versions",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "version": version,
                "active": active,
                "payload": payload,
                "created_at": datetime.now(UTC),
            },
        )

    def record_system_health(
        self,
        *,
        component: str,
        status: str,
        message: str | None = None,
        environment: Environment | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.system_health",
            {
                "id": str(uuid4()),
                "environment": environment.value if environment else None,
                "component": component,
                "status": status,
                "message": message,
                "created_at": datetime.now(UTC),
            },
        )

    def record_ai_usage_event(
        self,
        *,
        environment: Environment,
        provider: ModelProvider,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: Decimal,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.ai_usage_events",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "provider": provider.value,
                "prompt_tokens": max(0, int(prompt_tokens)),
                "completion_tokens": max(0, int(completion_tokens)),
                "cost_usd": Decimal(str(cost_usd)),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def record_economics_snapshot(
        self,
        *,
        environment: Environment,
        month_key: str,
        trading_realized_pnl_usd: Decimal,
        trading_unrealized_pnl_usd: Decimal,
        trading_total_pnl_usd: Decimal,
        ai_cost_usd: Decimal,
        ai_prompt_tokens: int,
        ai_completion_tokens: int,
        ai_total_tokens: int,
        aws_daily_cost_usd: Decimal,
        aws_month_to_date_cost_usd: Decimal,
        aws_source: str,
        aws_scope: str,
        aws_estimated: bool,
        net_after_costs_usd: Decimal,
        profitability_status: str,
        payload: dict,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.economics_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "month_key": month_key,
                "trading_realized_pnl_usd": Decimal(str(trading_realized_pnl_usd)),
                "trading_unrealized_pnl_usd": Decimal(str(trading_unrealized_pnl_usd)),
                "trading_total_pnl_usd": Decimal(str(trading_total_pnl_usd)),
                "ai_cost_usd": Decimal(str(ai_cost_usd)),
                "ai_prompt_tokens": max(0, int(ai_prompt_tokens)),
                "ai_completion_tokens": max(0, int(ai_completion_tokens)),
                "ai_total_tokens": max(0, int(ai_total_tokens)),
                "aws_daily_cost_usd": Decimal(str(aws_daily_cost_usd)),
                "aws_month_to_date_cost_usd": Decimal(str(aws_month_to_date_cost_usd)),
                "aws_source": aws_source,
                "aws_scope": aws_scope,
                "aws_estimated": bool(aws_estimated),
                "net_after_costs_usd": Decimal(str(net_after_costs_usd)),
                "profitability_status": profitability_status,
                "payload": _json_ready(payload),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def economics_snapshots(
        self,
        *,
        environment: Environment,
        month_key: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.economics_snapshots")
            if row["environment"] == environment.value
        ]
        if month_key is not None:
            rows = [row for row in rows if row["month_key"] == month_key]
        return rows

    def record_polymarket_gamma_market(
        self,
        *,
        environment: Environment,
        market_id: str,
        question: str,
        active: bool,
        closed: bool,
        raw_payload: dict,
        condition_id: str | None = None,
        slug: str | None = None,
        category: str | None = None,
        end_date: datetime | None = None,
        tokens: list | tuple = (),
        tags: list | tuple = (),
        fetched_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_gamma_markets",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "market_id": market_id,
                "condition_id": condition_id,
                "slug": slug,
                "question": question,
                "active": bool(active),
                "closed": bool(closed),
                "category": category,
                "end_date": end_date,
                "tokens": _json_ready(list(tokens)),
                "tags": _json_ready(list(tags)),
                "raw_payload": _json_ready(raw_payload),
                "fetched_at": fetched_at or now,
                "created_at": now,
            },
        )

    def polymarket_gamma_markets(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.polymarket_gamma_markets")
            if row["environment"] == environment.value
        ]

    def record_polymarket_chain_fill_event(
        self,
        *,
        environment: Environment,
        exchange_contract: str,
        block_number: int,
        log_index: int,
        transaction_hash: str,
        raw_event: dict,
        block_hash: str | None = None,
        maker_address: str | None = None,
        taker_address: str | None = None,
        asset_id: str | None = None,
        market_id: str | None = None,
        block_timestamp: datetime | None = None,
        decoded_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_chain_fill_events",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "exchange_contract": exchange_contract,
                "block_number": max(0, int(block_number)),
                "block_hash": block_hash,
                "log_index": max(0, int(log_index)),
                "transaction_hash": transaction_hash,
                "maker_address": maker_address,
                "taker_address": taker_address,
                "asset_id": asset_id,
                "market_id": market_id,
                "raw_event": _json_ready(raw_event),
                "block_timestamp": block_timestamp,
                "decoded_at": decoded_at or now,
                "created_at": now,
            },
        )

    def polymarket_chain_fill_events(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.polymarket_chain_fill_events")
            if row["environment"] == environment.value
        ]

    def record_polymarket_trade(
        self,
        *,
        environment: Environment,
        market_id: str,
        asset_id: str,
        wallet_address: str,
        side: str,
        price: Decimal,
        size: Decimal,
        notional_usd: Decimal,
        transaction_hash: str,
        block_number: int,
        traded_at: datetime,
        condition_id: str | None = None,
        realized_pnl_usd: Decimal | None = None,
        outcome: str | None = None,
        role: str | None = None,
        raw_event_id: str | None = None,
        market_record_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_trades",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "market_id": market_id,
                "condition_id": condition_id,
                "asset_id": asset_id,
                "wallet_address": wallet_address.lower(),
                "side": side.lower(),
                "price": Decimal(str(price)),
                "size": Decimal(str(size)),
                "notional_usd": Decimal(str(notional_usd)),
                "realized_pnl_usd": (
                    None if realized_pnl_usd is None else Decimal(str(realized_pnl_usd))
                ),
                "outcome": outcome,
                "role": role,
                "transaction_hash": transaction_hash,
                "block_number": max(0, int(block_number)),
                "raw_event_id": raw_event_id,
                "market_record_id": market_record_id,
                "traded_at": traded_at,
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def polymarket_trades(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.polymarket_trades")
            if row["environment"] == environment.value
        ]

    def record_polymarket_wallet_position(
        self,
        *,
        environment: Environment,
        wallet_address: str,
        market_id: str,
        asset_id: str,
        state: str,
        size: Decimal,
        realized_pnl_usd: Decimal,
        outcome: str | None = None,
        entry_price: Decimal | None = None,
        exit_price: Decimal | None = None,
        opened_at: datetime | None = None,
        closed_at: datetime | None = None,
        trade_ids: list | tuple = (),
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_wallet_positions",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "wallet_address": wallet_address.lower(),
                "market_id": market_id,
                "asset_id": asset_id,
                "outcome": outcome,
                "state": state,
                "entry_price": None if entry_price is None else Decimal(str(entry_price)),
                "exit_price": None if exit_price is None else Decimal(str(exit_price)),
                "size": Decimal(str(size)),
                "realized_pnl_usd": Decimal(str(realized_pnl_usd)),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "trade_ids": list(trade_ids),
                "created_at": now,
                "updated_at": updated_at or now,
            },
        )

    def record_polymarket_wallet_performance_stat(
        self,
        *,
        environment: Environment,
        wallet_address: str,
        trade_count: int,
        win_rate: Decimal,
        total_realized_pnl_usd: Decimal,
        source: str,
        average_hold_seconds: int | None = None,
        calculated_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_wallet_performance_stats",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "wallet_address": wallet_address.lower(),
                "trade_count": max(0, int(trade_count)),
                "win_rate": Decimal(str(win_rate)),
                "total_realized_pnl_usd": Decimal(str(total_realized_pnl_usd)),
                "average_hold_seconds": (
                    None if average_hold_seconds is None else max(0, int(average_hold_seconds))
                ),
                "source": source,
                "calculated_at": calculated_at or now,
                "created_at": now,
            },
        )

    def polymarket_wallet_performance_stats(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.polymarket_wallet_performance_stats")
            if row["environment"] == environment.value
        ]

    def record_polymarket_target_wallet_snapshot(
        self,
        *,
        environment: Environment,
        min_trade_count: int,
        min_win_rate: Decimal,
        wallets: list,
        source_stat_ids: list,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.polymarket_target_wallet_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "min_trade_count": max(0, int(min_trade_count)),
                "min_win_rate": Decimal(str(min_win_rate)),
                "wallet_count": len(wallets),
                "wallets": _json_ready(wallets),
                "source_stat_ids": list(source_stat_ids),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def polymarket_target_wallet_snapshots(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.polymarket_target_wallet_snapshots")
            if row["environment"] == environment.value
        ]

    def upsert_historical_import_checkpoint(
        self,
        *,
        environment: Environment,
        source: str,
        cursor_type: str,
        cursor_value: str,
        status: str,
        metadata: dict | None = None,
        last_success_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        table = f"{SHARED_SCHEMA}.historical_import_checkpoints"
        rows = self.state.rows(table)
        now = updated_at or datetime.now(UTC)
        for row in rows:
            if row["environment"] == environment.value and row["source"] == source:
                row.update(
                    {
                        "cursor_type": cursor_type,
                        "cursor_value": cursor_value,
                        "status": status,
                        "metadata": _json_ready(metadata or {}),
                        "last_success_at": last_success_at,
                        "updated_at": now,
                    }
                )
                return row
        return self.state.insert(
            table,
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "source": source,
                "cursor_type": cursor_type,
                "cursor_value": cursor_value,
                "status": status,
                "metadata": _json_ready(metadata or {}),
                "last_success_at": last_success_at,
                "updated_at": now,
            },
        )

    def historical_import_checkpoints(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.historical_import_checkpoints")
            if row["environment"] == environment.value
        ]

    def record_alpaca_historical_order(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        order_id: str,
        symbol: str,
        side: str,
        status: str,
        raw_payload: dict,
        client_order_id: str | None = None,
        order_type: str | None = None,
        quantity: Decimal | None = None,
        filled_quantity: Decimal | None = None,
        filled_avg_price: Decimal | None = None,
        notional: Decimal | None = None,
        submitted_at: datetime | None = None,
        filled_at: datetime | None = None,
        canceled_at: datetime | None = None,
        imported_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_historical_orders",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "order_id": order_id,
                "client_order_id": client_order_id,
                "symbol": symbol.upper(),
                "side": side.lower(),
                "order_type": order_type,
                "status": status.lower(),
                "quantity": None if quantity is None else Decimal(str(quantity)),
                "filled_quantity": (
                    None if filled_quantity is None else Decimal(str(filled_quantity))
                ),
                "filled_avg_price": (
                    None if filled_avg_price is None else Decimal(str(filled_avg_price))
                ),
                "notional": None if notional is None else Decimal(str(notional)),
                "submitted_at": submitted_at,
                "filled_at": filled_at,
                "canceled_at": canceled_at,
                "raw_payload": _json_ready(raw_payload),
                "imported_at": imported_at or now,
                "created_at": now,
            },
        )

    def alpaca_historical_orders(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_historical_orders")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if account_id is not None:
            rows = [row for row in rows if row["account_id"] == account_id]
        return rows

    def record_alpaca_historical_fill(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        activity_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        filled_at: datetime,
        raw_payload: dict,
        order_id: str | None = None,
        imported_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        notional = Decimal(str(quantity)) * Decimal(str(price))
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_historical_fills",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "activity_id": activity_id,
                "order_id": order_id,
                "symbol": symbol.upper(),
                "side": side.lower(),
                "quantity": Decimal(str(quantity)),
                "price": Decimal(str(price)),
                "notional": notional,
                "filled_at": filled_at,
                "raw_payload": _json_ready(raw_payload),
                "imported_at": imported_at or now,
                "created_at": now,
            },
        )

    def alpaca_historical_fills(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_historical_fills")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if account_id is not None:
            rows = [row for row in rows if row["account_id"] == account_id]
        return rows

    def record_alpaca_historical_position(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        symbol: str,
        quantity: Decimal,
        raw_payload: dict,
        average_entry_price: Decimal | None = None,
        cost_basis: Decimal | None = None,
        market_value: Decimal | None = None,
        current_price: Decimal | None = None,
        unrealized_pnl_usd: Decimal | None = None,
        observed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_historical_positions",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "symbol": symbol.upper(),
                "quantity": Decimal(str(quantity)),
                "average_entry_price": (
                    None if average_entry_price is None else Decimal(str(average_entry_price))
                ),
                "cost_basis": None if cost_basis is None else Decimal(str(cost_basis)),
                "market_value": None if market_value is None else Decimal(str(market_value)),
                "current_price": None if current_price is None else Decimal(str(current_price)),
                "unrealized_pnl_usd": (
                    None if unrealized_pnl_usd is None else Decimal(str(unrealized_pnl_usd))
                ),
                "raw_payload": _json_ready(raw_payload),
                "observed_at": observed_at or now,
                "created_at": now,
            },
        )

    def alpaca_historical_positions(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_historical_positions")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if account_id is not None:
            rows = [row for row in rows if row["account_id"] == account_id]
        return rows

    def record_alpaca_broker_account_snapshot(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        account_status: str,
        raw_payload: dict,
        buying_power: Decimal | None = None,
        cash: Decimal | None = None,
        portfolio_value: Decimal | None = None,
        equity: Decimal | None = None,
        observed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_broker_account_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "account_status": account_status,
                "buying_power": None if buying_power is None else Decimal(str(buying_power)),
                "cash": None if cash is None else Decimal(str(cash)),
                "portfolio_value": (
                    None if portfolio_value is None else Decimal(str(portfolio_value))
                ),
                "equity": None if equity is None else Decimal(str(equity)),
                "raw_payload": _json_ready(raw_payload),
                "observed_at": observed_at or now,
                "created_at": now,
            },
        )

    def alpaca_broker_account_snapshots(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_broker_account_snapshots")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if account_id is not None:
            rows = [row for row in rows if row["account_id"] == account_id]
        return rows

    def record_stock_bar(
        self,
        *,
        environment: Environment,
        symbol: str,
        timeframe: str,
        bar_start_at: datetime,
        open_price: Decimal,
        high_price: Decimal,
        low_price: Decimal,
        close_price: Decimal,
        volume: Decimal,
        source: str,
        raw_payload: dict,
        trade_count: int | None = None,
        vwap: Decimal | None = None,
        imported_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.stock_bars",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "bar_start_at": bar_start_at,
                "open_price": Decimal(str(open_price)),
                "high_price": Decimal(str(high_price)),
                "low_price": Decimal(str(low_price)),
                "close_price": Decimal(str(close_price)),
                "volume": Decimal(str(volume)),
                "trade_count": None if trade_count is None else max(0, int(trade_count)),
                "vwap": None if vwap is None else Decimal(str(vwap)),
                "source": source,
                "raw_payload": _json_ready(raw_payload),
                "imported_at": imported_at or now,
                "created_at": now,
            },
        )

    def stock_bars(
        self,
        *,
        environment: Environment,
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.stock_bars")
            if row["environment"] == environment.value
        ]
        if symbol is not None:
            rows = [row for row in rows if row["symbol"] == symbol.upper()]
        if timeframe is not None:
            rows = [row for row in rows if row["timeframe"] == timeframe]
        return rows

    def record_alpaca_symbol_pnl_snapshot(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        symbol: str,
        open_quantity: Decimal,
        realized_pnl_usd: Decimal,
        unrealized_pnl_usd: Decimal,
        total_pnl_usd: Decimal,
        cost_basis: Decimal,
        fill_ids: list | tuple,
        average_entry_price: Decimal | None = None,
        market_value: Decimal | None = None,
        position_id: str | None = None,
        calculated_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_symbol_pnl_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "symbol": symbol.upper(),
                "open_quantity": Decimal(str(open_quantity)),
                "average_entry_price": (
                    None if average_entry_price is None else Decimal(str(average_entry_price))
                ),
                "realized_pnl_usd": Decimal(str(realized_pnl_usd)),
                "unrealized_pnl_usd": Decimal(str(unrealized_pnl_usd)),
                "total_pnl_usd": Decimal(str(total_pnl_usd)),
                "cost_basis": Decimal(str(cost_basis)),
                "market_value": None if market_value is None else Decimal(str(market_value)),
                "fill_ids": list(fill_ids),
                "position_id": position_id,
                "calculated_at": calculated_at or now,
                "created_at": now,
            },
        )

    def alpaca_symbol_pnl_snapshots(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        account_id: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_symbol_pnl_snapshots")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if account_id is not None:
            rows = [row for row in rows if row["account_id"] == account_id]
        return rows

    def record_scanner_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        status: str,
        config: dict,
        source_pull_ids: list | tuple,
        accepted_count: int,
        rejected_count: int,
        started_at: datetime,
        completed_at: datetime,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.scanner_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "pipeline_run_id": pipeline_run_id,
                "trigger": trigger,
                "status": status,
                "config": _json_ready(config),
                "source_pull_ids": list(source_pull_ids),
                "accepted_count": max(0, int(accepted_count)),
                "rejected_count": max(0, int(rejected_count)),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def record_scanner_candidate(
        self,
        *,
        environment: Environment,
        scanner_run_id: str,
        venue: str,
        instrument_id: str,
        display_name: str,
        status: str,
        strategy_names: list | tuple,
        metrics: dict,
        source_payload: dict,
        symbol: str | None = None,
        market_id: str | None = None,
        outcome_id: str | None = None,
        refusal_reason: str | None = None,
        price: Decimal | None = None,
        liquidity: Decimal | None = None,
        spread: Decimal | None = None,
        hours_to_resolution: Decimal | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.scanner_candidates",
            {
                "id": str(uuid4()),
                "scanner_run_id": scanner_run_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "display_name": display_name,
                "symbol": symbol.upper() if symbol else None,
                "market_id": market_id,
                "outcome_id": outcome_id,
                "status": status,
                "refusal_reason": refusal_reason,
                "strategy_names": list(strategy_names),
                "price": None if price is None else Decimal(str(price)),
                "liquidity": None if liquidity is None else Decimal(str(liquidity)),
                "spread": None if spread is None else Decimal(str(spread)),
                "hours_to_resolution": (
                    None if hours_to_resolution is None else Decimal(str(hours_to_resolution))
                ),
                "metrics": _json_ready(metrics),
                "source_payload": _json_ready(source_payload),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def scanner_runs(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.scanner_runs")
            if row["environment"] == environment.value
        ]

    def scanner_candidates(
        self,
        *,
        environment: Environment,
        scanner_run_id: str | None = None,
        venue: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.scanner_candidates")
            if row["environment"] == environment.value
        ]
        if scanner_run_id is not None:
            rows = [row for row in rows if row["scanner_run_id"] == scanner_run_id]
        if venue is not None:
            rows = [row for row in rows if row["venue"] == venue]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

    def record_audit_event(
        self,
        *,
        event_type: str,
        actor: str,
        action: str,
        environment: Environment,
        entity_id: str | None = None,
        metadata: dict | None = None,
        success: bool = True,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.audit_events",
            {
                "id": str(uuid4()),
                "event_type": event_type,
                "actor": actor,
                "action": action,
                "environment": environment.value,
                "entity_id": entity_id,
                "success": success,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC),
            },
        )

    def register_alpaca_account(
        self,
        *,
        environment: Environment,
        account_mode: str,
        model_provider: ModelProvider,
        account_id: str,
    ) -> AlpacaAccountRegistrationResult:
        existing = self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_registry")
        for row in existing:
            same_environment = row["environment"] == environment.value
            same_mode = row["account_mode"] == account_mode
            same_account = row["account_id"] == account_id
            different_provider = row["model_provider"] != model_provider.value
            if same_environment and same_mode and same_account and different_provider:
                self.record_audit_event(
                    event_type="alpaca_account_duplicate",
                    actor="system",
                    action="alpaca_account.duplicate",
                    environment=environment,
                    entity_id=account_id,
                    success=False,
                    metadata={
                        "account_mode": account_mode,
                        "existing_model_provider": row["model_provider"],
                        "duplicate_model_provider": model_provider.value,
                        "refusal_reason": "duplicate Alpaca account identifier",
                    },
                )
                return AlpacaAccountRegistrationResult(
                    live_trading_allowed=False,
                    refusal_reason="duplicate Alpaca account identifier",
                )
        self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_account_registry",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "model_provider": model_provider.value,
                "account_id": account_id,
                "created_at": datetime.now(UTC),
            },
        )
        return AlpacaAccountRegistrationResult(live_trading_allowed=True)


class ModelRepositories:
    """Repositories for provider-specific model data.

    REQ: REQ-DB-001, REQ-DB-002, REQ-DB-004, REQ-DB-005, REQ-EXE-016
    """

    def __init__(self, *, state: DatabaseState, provider: ModelProvider, schema_name: str):
        self.state = state
        self.provider = provider
        self.schema_name = schema_name

    def ensure_schema(self, schema_name: str) -> None:
        if schema_name != self.schema_name:
            raise SchemaViolationError(f"{self.provider.value} records must use {self.schema_name}")

    def record_trade_decision(self, decision: TradeDecision) -> dict:
        self.ensure_schema(provider_schema(decision.model_provider))
        row = {
            "id": str(uuid4()),
            "environment": decision.environment.value,
            "model_provider": decision.model_provider.value,
            "venue": decision.venue.value,
            "instrument_identifier": decision.instrument.identifier,
            "instrument_type": decision.instrument.instrument_type.value,
            "signal_inputs": decision.signal_inputs,
            "decision": decision.decision,
            "order_type": decision.order_type.value,
            "size": decision.size,
            "created_at": decision.created_at,
        }
        return self.state.insert(f"{self.schema_name}.trade_decisions", row)

    def record_position_event(
        self,
        transition: PositionTransition,
        *,
        execution_mode: str,
        idempotency_key: str,
    ) -> dict:
        table = f"{self.schema_name}.position_events"
        for row in self.state.rows(table):
            if row["idempotency_key"] == idempotency_key:
                return row
        row = {
            "idempotency_key": idempotency_key,
            "position_id": transition.position_id,
            "execution_mode": execution_mode,
            "prior_state": transition.prior_state.value,
            "new_state": transition.new_state.value,
            "realized_pnl": transition.realized_pnl,
            "unrealized_pnl": transition.unrealized_pnl,
            "reason": transition.reason,
            "created_at": transition.created_at,
        }
        self.state.insert(table, row)
        self.state.insert(
            f"{self.schema_name}.positions",
            {
                "position_id": transition.position_id,
                "state": transition.new_state.value,
                "realized_pnl": transition.realized_pnl,
                "unrealized_pnl": transition.unrealized_pnl,
                "updated_at": transition.created_at,
            },
        )
        return row

    def record_order_event(self, event: OrderEvent) -> dict:
        self.ensure_schema(provider_schema(event.model_provider))
        row = {
            "id": str(uuid4()),
            "order_id": event.order_id,
            "event_type": event.event_type.value,
            "venue": event.venue.value,
            "model_provider": event.model_provider.value,
            "message": event.message,
            "created_at": event.created_at,
        }
        return self.state.insert(f"{self.schema_name}.order_events", row)

    def record_alpaca_account_snapshot(
        self,
        *,
        environment: Environment,
        account_mode: str,
        snapshot: AlpacaReconciliationSnapshot,
    ) -> dict:
        configured_account_id = snapshot.configured_account_id or snapshot.account_id
        broker_account_id = snapshot.broker_account_id or snapshot.account_id
        broker_positions = snapshot.broker_positions or snapshot.positions
        postgres_positions = snapshot.postgres_positions or snapshot.positions
        broker_open_orders = snapshot.broker_open_orders or snapshot.open_orders
        postgres_open_orders = snapshot.postgres_open_orders or snapshot.open_orders
        return self.state.insert(
            f"{self.schema_name}.alpaca_account_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": snapshot.account_id,
                "configured_account_id": configured_account_id,
                "broker_account_id": broker_account_id,
                "account_status": snapshot.account_status,
                "positions": {key: str(value) for key, value in snapshot.positions.items()},
                "open_orders": list(snapshot.open_orders),
                "broker_positions": {key: str(value) for key, value in broker_positions.items()},
                "postgres_positions": {key: str(value) for key, value in postgres_positions.items()},
                "broker_open_orders": list(broker_open_orders),
                "postgres_open_orders": list(postgres_open_orders),
                "buying_power": snapshot.buying_power,
                "observed_at": snapshot.observed_at,
                "freshness_seconds": snapshot.freshness_seconds,
                "mismatches": list(snapshot.mismatches),
                "is_live_safe": snapshot.is_live_safe,
                "created_at": datetime.now(UTC),
            },
        )

    def record_alpaca_reconciliation_mismatch(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        mismatch_reason: str,
        mismatch_details: dict,
    ) -> dict:
        return self.state.insert(
            f"{self.schema_name}.alpaca_reconciliation_mismatches",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "account_mode": account_mode,
                "account_id": account_id,
                "mismatch_reason": mismatch_reason,
                "mismatch_details": _json_ready(mismatch_details),
                "created_at": datetime.now(UTC),
            },
        )

    def reconcile_alpaca_state(
        self,
        broker_snapshot: AlpacaReconciliationSnapshot | None,
        postgres_snapshot: AlpacaReconciliationSnapshot | None,
        *,
        max_freshness_seconds: int = 300,
    ) -> AlpacaReconciliationResult:
        if broker_snapshot is None or postgres_snapshot is None:
            return self._blocked_alpaca_reconciliation(
                "reconciliation incomplete",
                {"completed": False},
                broker_snapshot,
                postgres_snapshot,
            )
        if not broker_snapshot.completed or not postgres_snapshot.completed:
            return self._blocked_alpaca_reconciliation(
                "reconciliation incomplete",
                {
                    "completed": {
                        "broker": broker_snapshot.completed,
                        "postgres": postgres_snapshot.completed,
                    },
                },
                broker_snapshot,
                postgres_snapshot,
            )
        mismatch_details: dict[str, object] = {}
        if broker_snapshot.freshness_seconds > max_freshness_seconds or postgres_snapshot.freshness_seconds > max_freshness_seconds:
            mismatch_details["freshness_seconds"] = {
                "broker": broker_snapshot.freshness_seconds,
                "postgres": postgres_snapshot.freshness_seconds,
                "max": max_freshness_seconds,
            }
        if broker_snapshot.account_status.lower() != "active":
            mismatch_details["account_status"] = broker_snapshot.account_status
        configured_account_id = broker_snapshot.configured_account_id or postgres_snapshot.configured_account_id
        broker_account_id = broker_snapshot.broker_account_id or broker_snapshot.account_id
        if configured_account_id and broker_account_id and configured_account_id != broker_account_id:
            mismatch_details["account_id"] = {
                "configured": configured_account_id,
                "broker": broker_account_id,
            }
        broker_positions = broker_snapshot.broker_positions or broker_snapshot.positions
        postgres_positions = postgres_snapshot.postgres_positions or postgres_snapshot.positions
        if broker_positions != postgres_positions:
            mismatch_details["positions"] = {
                "broker": broker_positions,
                "postgres": postgres_positions,
            }
        broker_open_orders = broker_snapshot.broker_open_orders or broker_snapshot.open_orders
        postgres_open_orders = postgres_snapshot.postgres_open_orders or postgres_snapshot.open_orders
        if set(broker_open_orders) != set(postgres_open_orders):
            mismatch_details["open_orders"] = {
                "broker": broker_open_orders,
                "postgres": postgres_open_orders,
            }
        if broker_snapshot.buying_power != postgres_snapshot.buying_power:
            mismatch_details["buying_power"] = {
                "broker": broker_snapshot.buying_power,
                "postgres": postgres_snapshot.buying_power,
            }
        if broker_snapshot.mismatches or postgres_snapshot.mismatches:
            mismatch_details["reported_mismatches"] = broker_snapshot.mismatches + postgres_snapshot.mismatches
        if not broker_snapshot.is_live_safe or not postgres_snapshot.is_live_safe:
            mismatch_details["is_live_safe"] = {
                "broker": broker_snapshot.is_live_safe,
                "postgres": postgres_snapshot.is_live_safe,
            }
        if mismatch_details:
            return self._blocked_alpaca_reconciliation(
                "broker and Postgres state mismatch",
                mismatch_details,
                broker_snapshot,
                postgres_snapshot,
            )
        return AlpacaReconciliationResult(live_order_allowed=True)

    def _blocked_alpaca_reconciliation(
        self,
        reason: str,
        details: dict,
        broker_snapshot: AlpacaReconciliationSnapshot | None,
        postgres_snapshot: AlpacaReconciliationSnapshot | None,
    ) -> AlpacaReconciliationResult:
        reference_snapshot = broker_snapshot or postgres_snapshot
        environment = (reference_snapshot.environment if reference_snapshot else None) or Environment.LOCAL
        account_mode = (reference_snapshot.account_mode if reference_snapshot else None) or "unknown"
        account_id = (
            (reference_snapshot.configured_account_id if reference_snapshot else None)
            or (reference_snapshot.broker_account_id if reference_snapshot else None)
            or (reference_snapshot.account_id if reference_snapshot else None)
            or "unknown"
        )
        persisted_details = _json_ready(details)
        self.record_alpaca_reconciliation_mismatch(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
            mismatch_reason=reason,
            mismatch_details=persisted_details,
        )
        return AlpacaReconciliationResult(
            live_order_allowed=False,
            mismatch_reason=reason,
            mismatch_details=persisted_details,
        )


class RepositoryRegistry:
    """Repository factory for shared and model-provider schemas."""

    def __init__(self, state: DatabaseState | None = None):
        self.state = state or DatabaseState()

    def shared(self) -> SharedRepositories:
        return SharedRepositories(self.state)

    def for_model(self, provider: ModelProvider) -> ModelRepositories:
        return ModelRepositories(
            state=self.state,
            provider=provider,
            schema_name=MODEL_SCHEMAS[provider],
        )

    def record_order_event_with_audit(
        self,
        event: OrderEvent,
        *,
        environment: Environment,
        actor: str = "system",
    ) -> OrderEventHandlingResult:
        """Persist an order event and a shared audit event.

        REQ: REQ-EXE-016, REQ-OBS-003
        """

        with UnitOfWork(self.state) as unit:
            audit_event = self.shared().record_audit_event(
                event_type="order_event",
                actor=actor,
                action=event.event_type.value,
                environment=environment,
                entity_id=event.order_id,
                success=event.event_type not in {OrderEventType.FAILED, OrderEventType.REFUSED},
                metadata={
                    "venue": event.venue.value,
                    "model_provider": event.model_provider.value,
                    "message": event.message,
                },
            )
            order_event = self.for_model(event.model_provider).record_order_event(event)
            unit.commit()
        return OrderEventHandlingResult(order_event=order_event, audit_event=audit_event)
