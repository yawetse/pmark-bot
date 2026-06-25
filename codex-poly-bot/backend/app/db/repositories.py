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
