"""Repository contracts and local in-memory repository implementation.

REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
REQ-DB-007, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018, REQ-EXE-016,
REQ-OBS-003, REQ-OBS-004, REQ-DB-008, REQ-UI-014
"""

from __future__ import annotations

from copy import deepcopy
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.domain import (
    Environment,
    ModelProvider,
    OrderEvent,
    OrderEventType,
    PositionTransition,
    StrategySignal,
    TradeDecision,
)
from app.db.schema import MODEL_SCHEMAS, SHARED_SCHEMA, metadata, provider_schema


class PersistenceUnavailableError(RuntimeError):
    """Raised when persistence is unavailable for a live-sensitive path."""


class SchemaViolationError(ValueError):
    """Raised when a repository is used with the wrong schema."""


SHARED_CONFIG_USERNAME = "__shared__"


def normalize_config_username(username: str | None) -> str:
    """Return the config owner key used by shared config version rows."""

    value = (username or "").strip()
    return value or SHARED_CONFIG_USERNAME


@dataclass
class DatabaseState:
    """Local repository state used by tests and dry-run development."""

    available: bool = True
    fail_on_tables: set[str] = field(default_factory=set)
    fail_on_read_tables: set[str] = field(default_factory=set)
    tables: dict[str, list[dict]] = field(default_factory=dict)
    _transaction_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _session_locks: dict[str, Lock] = field(default_factory=dict, init=False, repr=False)
    _session_locks_guard: Lock = field(default_factory=Lock, init=False, repr=False)

    def begin_transaction(self) -> dict[str, list[dict]]:
        """Capture in-memory state so tests receive transaction semantics."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        self._transaction_lock.acquire()
        return deepcopy(self.tables)

    def commit_transaction(self, transaction: dict[str, list[dict]]) -> None:
        del transaction
        self._transaction_lock.release()

    def rollback_transaction(self, transaction: dict[str, list[dict]]) -> None:
        self.tables = transaction
        self._transaction_lock.release()

    def insert(self, table_name: str, row: dict) -> dict:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        self.tables.setdefault(table_name, []).append(row)
        return row

    def update_by_id(self, table_name: str, row_id: str, values: dict[str, Any]) -> dict:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        for row in self.tables.setdefault(table_name, []):
            if row.get("id") == row_id:
                row.update(values)
                return row
        raise PersistenceUnavailableError(f"row not found for {table_name}")

    def upsert_by_id(self, table_name: str, row_id: str, values: dict[str, Any]) -> dict:
        """Insert a row or update it by primary key."""

        for row in self.tables.setdefault(table_name, []):
            if row.get("id") == row_id:
                row.update(values)
                return row
        return self.insert(table_name, {"id": row_id, **values})

    def lock_transaction_key(self, key: str) -> None:
        """Use the enclosing in-memory transaction as the serialization lock."""

        del key

    def try_session_lock(self, key: str) -> object | None:
        """Acquire one nonblocking process lock for a long-running job."""

        with self._session_locks_guard:
            lock = self._session_locks.setdefault(key, Lock())
        return lock if lock.acquire(blocking=False) else None

    def release_session_lock(self, token: object) -> None:
        """Release a process job lock returned by try_session_lock."""

        if not hasattr(token, "release"):
            raise PersistenceUnavailableError("invalid in-memory session lock token")
        token.release()  # type: ignore[union-attr]

    def rows(
        self,
        table_name: str,
        *,
        limit: int | None = None,
        before: tuple[datetime, str] | None = None,
        newest_first: bool = False,
        filters: dict[str, Any] | None = None,
        ids: set[str] | None = None,
    ) -> list[dict]:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        rows = self.tables.setdefault(table_name, [])
        if (
            filters is None
            and ids is None
            and limit is None
            and not newest_first
            and before is None
        ):
            return rows
        selected_rows = [
            row
            for row in rows
            if (ids is None or row.get("id") in ids)
            and all(row.get(key) == value for key, value in (filters or {}).items())
        ]
        if before is not None:
            before_key = (before[0].isoformat(), before[1])
            selected_rows = [
                row
                for row in selected_rows
                if (_row_order_value(row), str(row.get("id", ""))) < before_key
            ]
        if newest_first:
            selected_rows.sort(
                key=lambda row: (_row_order_value(row), str(row.get("id", ""))),
                reverse=True,
            )
        if limit is not None:
            selected_rows = selected_rows[: max(1, int(limit))]
        return selected_rows

    def count(self, table_name: str, *, filters: dict[str, Any] | None = None) -> int:
        """Count matching in-memory rows without copying row payloads."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            )
        return sum(
            1
            for row in self.tables.setdefault(table_name, [])
            if all(row.get(key) == value for key, value in (filters or {}).items())
        )

    def sum_decimal(
        self,
        table_name: str,
        column_name: str,
        *,
        filters: dict[str, Any] | None = None,
        created_at_gte: datetime | None = None,
        timeout_ms: int | None = None,
    ) -> Decimal:
        """Sum matching in-memory values; timeout_ms applies to Postgres only."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            )
        total = Decimal("0")
        for row in self.tables.setdefault(table_name, []):
            if not all(row.get(key) == value for key, value in (filters or {}).items()):
                continue
            created_at = row.get("created_at")
            if created_at_gte is not None and (
                not isinstance(created_at, datetime) or created_at < created_at_gte
            ):
                continue
            total += Decimal(str(row.get(column_name) or "0"))
        return total


@dataclass(frozen=True)
class _SqlAlchemyTransaction:
    session: Any
    token: Any | None
    nested: Any | None = None


@dataclass(frozen=True)
class _PostgresSessionLock:
    session: Any
    key: str


class PersistentDatabaseState(DatabaseState):
    """Repository state backed by the configured Postgres database."""

    def __init__(self, session_factory: sessionmaker):
        super().__init__(available=True)
        self.session_factory = session_factory
        self._active_session: ContextVar[Any | None] = ContextVar(
            "codex_poly_bot_db_session",
            default=None,
        )

    def begin_transaction(self) -> _SqlAlchemyTransaction:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        active = self._active_session.get()
        if active is not None:
            try:
                return _SqlAlchemyTransaction(
                    session=active,
                    token=None,
                    nested=active.begin_nested(),
                )
            except SQLAlchemyError as exc:
                raise PersistenceUnavailableError("nested Postgres transaction failed") from exc
        session = self.session_factory()
        token = self._active_session.set(session)
        return _SqlAlchemyTransaction(session=session, token=token)

    def commit_transaction(self, transaction: _SqlAlchemyTransaction) -> None:
        if transaction.nested is not None:
            try:
                transaction.nested.commit()
            except SQLAlchemyError as exc:
                transaction.nested.rollback()
                raise PersistenceUnavailableError("Postgres savepoint commit failed") from exc
            return
        try:
            transaction.session.commit()
        except SQLAlchemyError as exc:
            transaction.session.rollback()
            raise PersistenceUnavailableError("Postgres persistence commit failed") from exc
        finally:
            assert transaction.token is not None
            self._active_session.reset(transaction.token)
            transaction.session.close()

    def rollback_transaction(self, transaction: _SqlAlchemyTransaction) -> None:
        if transaction.nested is not None:
            transaction.nested.rollback()
            return
        try:
            transaction.session.rollback()
        finally:
            assert transaction.token is not None
            self._active_session.reset(transaction.token)
            transaction.session.close()

    def insert(self, table_name: str, row: dict) -> dict:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        table = _table_for_name(table_name)
        values = {
            key: value
            for key, value in row.items()
            if key in table.c
        }
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            result = session.execute(table.insert().values(**values).returning(*table.c))
            persisted = dict(result.mappings().one())
            if owns_session:
                session.commit()
            return persisted
        except SQLAlchemyError as exc:
            if owns_session:
                session.rollback()
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}") from exc
        finally:
            if owns_session:
                session.close()

    def update_by_id(self, table_name: str, row_id: str, values: dict[str, Any]) -> dict:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        table = _table_for_name(table_name)
        clean_values = {key: value for key, value in values.items() if key in table.c}
        if not clean_values:
            raise SchemaViolationError(f"no known repository columns to update for {table_name}")
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            result = session.execute(
                table.update()
                .where(table.c.id == row_id)
                .values(**clean_values)
                .returning(*table.c)
            )
            persisted = result.mappings().one_or_none()
            if persisted is None:
                if owns_session:
                    session.rollback()
                raise PersistenceUnavailableError(f"row not found for {table_name}")
            if owns_session:
                session.commit()
            return dict(persisted)
        except SQLAlchemyError as exc:
            if owns_session:
                session.rollback()
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}") from exc
        finally:
            if owns_session:
                session.close()

    def upsert_by_id(self, table_name: str, row_id: str, values: dict[str, Any]) -> dict:
        """Atomically insert or update a Postgres row by primary key."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        table = _table_for_name(table_name)
        insert_values = {
            key: value
            for key, value in {"id": row_id, **values}.items()
            if key in table.c
        }
        update_values = {
            key: value
            for key, value in values.items()
            if key in table.c and key not in {"id", "created_at"}
        }
        statement = postgresql_insert(table).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.id],
            set_=update_values,
        ).returning(*table.c)
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            persisted = dict(session.execute(statement).mappings().one())
            if owns_session:
                session.commit()
            return persisted
        except SQLAlchemyError as exc:
            if owns_session:
                session.rollback()
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            ) from exc
        finally:
            if owns_session:
                session.close()

    def lock_transaction_key(self, key: str) -> None:
        """Serialize a logical key for the current Postgres transaction."""

        session = self._active_session.get()
        if session is None:
            raise PersistenceUnavailableError("transaction lock requires an active transaction")
        try:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )
        except SQLAlchemyError as exc:
            raise PersistenceUnavailableError("Postgres transaction lock failed") from exc

    def try_session_lock(self, key: str) -> object | None:
        """Acquire a nonblocking Postgres advisory lock on a dedicated session."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        session = self.session_factory()
        try:
            acquired = bool(
                session.execute(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                    {"key": key},
                ).scalar_one()
            )
        except SQLAlchemyError as exc:
            session.close()
            raise PersistenceUnavailableError("Postgres session lock failed") from exc
        if not acquired:
            session.close()
            return None
        return _PostgresSessionLock(session=session, key=key)

    def release_session_lock(self, token: object) -> None:
        """Release and close a dedicated Postgres advisory-lock session."""

        if not isinstance(token, _PostgresSessionLock):
            raise PersistenceUnavailableError("invalid Postgres session lock token")
        try:
            token.session.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": token.key},
            )
        except SQLAlchemyError as exc:
            raise PersistenceUnavailableError("Postgres session unlock failed") from exc
        finally:
            token.session.close()

    def rows(
        self,
        table_name: str,
        *,
        limit: int | None = None,
        before: tuple[datetime, str] | None = None,
        newest_first: bool = False,
        filters: dict[str, Any] | None = None,
        ids: set[str] | None = None,
    ) -> list[dict]:
        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}")
        table = _table_for_name(table_name)
        statement = table.select()
        if ids is not None:
            if "id" not in table.c:
                raise SchemaViolationError(f"ID lookup is unavailable for {table_name}")
            if not ids:
                return []
            statement = statement.where(table.c.id.in_(sorted(ids)))
        for key, value in (filters or {}).items():
            if key not in table.c:
                raise SchemaViolationError(f"unknown repository column: {table_name}.{key}")
            statement = statement.where(table.c[key] == value)
        if before is not None:
            if "created_at" not in table.c or "id" not in table.c:
                raise SchemaViolationError(f"cursor pagination is unavailable for {table_name}")
            statement = statement.where(
                or_(
                    table.c.created_at < before[0],
                    and_(table.c.created_at == before[0], table.c.id < before[1]),
                )
            )
        if "created_at" in table.c:
            column = table.c.created_at
            order_columns = [column.desc() if newest_first else column.asc()]
            if "id" in table.c:
                order_columns.append(table.c.id.desc() if newest_first else table.c.id.asc())
            statement = statement.order_by(*order_columns)
        elif "updated_at" in table.c:
            column = table.c.updated_at
            statement = statement.order_by(column.desc() if newest_first else column.asc())
        if limit is not None:
            statement = statement.limit(max(1, int(limit)))
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            return [dict(row) for row in session.execute(statement).mappings().all()]
        except SQLAlchemyError as exc:
            raise PersistenceUnavailableError(f"Postgres persistence is unavailable for {table_name}") from exc
        finally:
            if owns_session:
                session.close()

    def count(self, table_name: str, *, filters: dict[str, Any] | None = None) -> int:
        """Count matching Postgres rows without loading their JSON payloads."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            )
        table = _table_for_name(table_name)
        statement = select(func.count()).select_from(table)
        for key, value in (filters or {}).items():
            if key not in table.c:
                raise SchemaViolationError(f"unknown repository column: {table_name}.{key}")
            statement = statement.where(table.c[key] == value)
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            return int(session.execute(statement).scalar_one())
        except SQLAlchemyError as exc:
            if owns_session:
                session.rollback()
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            ) from exc
        finally:
            if owns_session:
                session.close()

    def sum_decimal(
        self,
        table_name: str,
        column_name: str,
        *,
        filters: dict[str, Any] | None = None,
        created_at_gte: datetime | None = None,
        timeout_ms: int | None = None,
    ) -> Decimal:
        """Sum matching Postgres decimal values without loading row payloads."""

        if not self.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if table_name in self.fail_on_read_tables:
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            )
        table = _table_for_name(table_name)
        if column_name not in table.c:
            raise SchemaViolationError(
                f"unknown repository column: {table_name}.{column_name}"
            )
        statement = select(func.coalesce(func.sum(table.c[column_name]), 0))
        for key, value in (filters or {}).items():
            if key not in table.c:
                raise SchemaViolationError(f"unknown repository column: {table_name}.{key}")
            statement = statement.where(table.c[key] == value)
        if created_at_gte is not None:
            if "created_at" not in table.c:
                raise SchemaViolationError(
                    f"created_at filtering is unavailable for {table_name}"
                )
            statement = statement.where(table.c.created_at >= created_at_gte)
        session = self._active_session.get()
        owns_session = session is None
        if owns_session:
            session = self.session_factory()
        try:
            if timeout_ms is not None:
                bounded_timeout_ms = max(1, int(timeout_ms))
                session.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{bounded_timeout_ms}ms"},
                )
            return Decimal(str(session.execute(statement).scalar_one()))
        except SQLAlchemyError as exc:
            if owns_session:
                session.rollback()
            raise PersistenceUnavailableError(
                f"Postgres persistence is unavailable for {table_name}"
            ) from exc
        finally:
            if owns_session:
                session.close()

def _table_for_name(table_name: str):
    table = metadata.tables.get(table_name)
    if table is None:
        raise SchemaViolationError(f"unknown repository table: {table_name}")
    return table


def _row_order_value(row: dict[str, Any]) -> str:
    value = row.get("created_at") if "created_at" in row else row.get("updated_at")
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else str(value)


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
        self._transaction: _SqlAlchemyTransaction | None = None

    def __enter__(self) -> UnitOfWork:
        if not self.state.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        begin_transaction = getattr(self.state, "begin_transaction", None)
        if begin_transaction is not None:
            self._transaction = begin_transaction()
            return self
        self._snapshot = deepcopy(self.state.tables)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.rollback()
        elif self._transaction is not None and not self.committed:
            self.rollback()

    def commit(self) -> None:
        if not self.state.available:
            raise PersistenceUnavailableError("Postgres persistence is unavailable")
        if self._transaction is not None:
            commit_transaction = getattr(self.state, "commit_transaction")
            commit_transaction(self._transaction)
            self._transaction = None
        self.committed = True

    def rollback(self) -> None:
        if self._transaction is not None:
            rollback_transaction = getattr(self.state, "rollback_transaction")
            rollback_transaction(self._transaction)
            self._transaction = None
            self.rolled_back = True
            return
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

    def record_config_version(
        self,
        *,
        environment: Environment,
        version: str,
        payload: dict,
        active: bool = True,
        username: str | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.config_versions",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "username": normalize_config_username(username),
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
        model: str | None = None,
        pipeline_run_id: str | None = None,
        pipeline_step: str | None = None,
        candidate_id: str | None = None,
        usage_source: str = "provider_response",
        cost_source: str = "recorded",
        response_id: str | None = None,
        raw_payload: dict | None = None,
        imported_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            f"{SHARED_SCHEMA}.ai_usage_events",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "provider": provider.value,
                "model": model,
                "pipeline_run_id": pipeline_run_id,
                "pipeline_step": pipeline_step,
                "candidate_id": candidate_id,
                "prompt_tokens": max(0, int(prompt_tokens)),
                "completion_tokens": max(0, int(completion_tokens)),
                "cost_usd": Decimal(str(cost_usd)),
                "usage_source": usage_source,
                "cost_source": cost_source,
                "response_id": response_id,
                "raw_payload": _json_ready(raw_payload or {}),
                "imported_at": imported_at,
                "created_at": now,
            },
        )

    def ai_usage_events(
        self,
        *,
        environment: Environment,
        provider: ModelProvider | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.ai_usage_events")
            if row["environment"] == environment.value
        ]
        if provider is not None:
            rows = [row for row in rows if row["provider"] == provider.value]
        return rows

    def record_ai_usage_import_run(
        self,
        *,
        environment: Environment,
        provider: ModelProvider,
        status: str,
        source: str,
        imported_count: int,
        message: str,
        started_at: datetime,
        completed_at: datetime,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        error_code: str | None = None,
        metadata: dict | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.ai_usage_import_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "provider": provider.value,
                "status": status,
                "source": source,
                "period_start": period_start,
                "period_end": period_end,
                "imported_count": max(0, int(imported_count)),
                "error_code": error_code,
                "message": message,
                "metadata": _json_ready(metadata or {}),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def ai_usage_import_runs(
        self,
        *,
        environment: Environment,
        provider: ModelProvider | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.ai_usage_import_runs")
            if row["environment"] == environment.value
        ]
        if provider is not None:
            rows = [row for row in rows if row["provider"] == provider.value]
        return rows

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

    def record_alpaca_symbol_preset_snapshot(
        self,
        *,
        environment: Environment,
        preset_name: str,
        status: str,
        source: str,
        source_url: str | None,
        symbols: list | tuple,
        effective_at: datetime,
        refreshed_at: datetime,
        message: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        normalized_symbols = [
            str(symbol).strip().upper().replace(".", "-")
            for symbol in symbols
            if str(symbol).strip()
        ]
        return self.state.insert(
            f"{SHARED_SCHEMA}.alpaca_symbol_preset_snapshots",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "preset_name": preset_name.strip().lower().replace(" ", "_"),
                "status": status,
                "source": source,
                "source_url": source_url,
                "symbols": list(dict.fromkeys(normalized_symbols)),
                "symbol_count": len(dict.fromkeys(normalized_symbols)),
                "effective_at": effective_at,
                "refreshed_at": refreshed_at,
                "message": message,
                "created_at": created_at or refreshed_at,
            },
        )

    def alpaca_symbol_preset_snapshots(
        self,
        *,
        environment: Environment,
        preset_name: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_symbol_preset_snapshots")
            if row["environment"] == environment.value
        ]
        if preset_name is not None:
            normalized = preset_name.strip().lower().replace(" ", "_")
            rows = [row for row in rows if row["preset_name"] == normalized]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

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
        return self.state.rows(
            f"{SHARED_SCHEMA}.scanner_runs",
            filters={"environment": environment.value},
        )

    def latest_scanner_run(self, *, environment: Environment) -> dict | None:
        self.ensure_schema(SHARED_SCHEMA)
        rows = self.state.rows(
            f"{SHARED_SCHEMA}.scanner_runs",
            filters={"environment": environment.value},
            newest_first=True,
            limit=1,
        )
        return rows[0] if rows else None

    def scanner_rejection_breakdown(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        limit: int = 12,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = self.state.rows(
            f"{SHARED_SCHEMA}.pipeline_steps",
            filters={
                "environment": environment.value,
                "run_id": pipeline_run_id,
                "step_key": "scanner",
            },
            newest_first=True,
            limit=1,
        )
        metrics = rows[0].get("metrics") if rows else None
        persisted = metrics.get("rejectionBreakdown") if isinstance(metrics, dict) else None
        breakdown = [
            {
                "venue": str(row.get("venue") or "unknown"),
                "reason": str(row.get("reason") or "not recorded"),
                "count": int(row.get("count") or 0),
            }
            for row in persisted or []
            if isinstance(row, dict) and int(row.get("count") or 0) > 0
        ]
        breakdown.sort(
            key=lambda row: (-row["count"], row["venue"], row["reason"])
        )
        return breakdown[: max(1, int(limit))]

    def scanner_candidates(
        self,
        *,
        environment: Environment,
        scanner_run_id: str | None = None,
        venue: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        filters: dict[str, Any] = {"environment": environment.value}
        if scanner_run_id is not None:
            filters["scanner_run_id"] = scanner_run_id
        if venue is not None:
            filters["venue"] = venue
        if status is not None:
            filters["status"] = status
        return self.state.rows(
            f"{SHARED_SCHEMA}.scanner_candidates",
            filters=filters,
        )

    def record_reasoning_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        scanner_run_id: str | None,
        trigger: str,
        status: str,
        config: dict,
        provider_count: int,
        prompt_count: int,
        scored_count: int,
        skipped_count: int,
        failed_count: int,
        started_at: datetime,
        completed_at: datetime,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.reasoning_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "pipeline_run_id": pipeline_run_id,
                "scanner_run_id": scanner_run_id,
                "trigger": trigger,
                "status": status,
                "config": _json_ready(config),
                "provider_count": max(0, int(provider_count)),
                "prompt_count": max(0, int(prompt_count)),
                "scored_count": max(0, int(scored_count)),
                "skipped_count": max(0, int(skipped_count)),
                "failed_count": max(0, int(failed_count)),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def update_reasoning_run_result(
        self,
        *,
        reasoning_run_id: str,
        status: str,
        scored_count: int,
        skipped_count: int,
        failed_count: int,
        completed_at: datetime,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.update_by_id(
            f"{SHARED_SCHEMA}.reasoning_runs",
            reasoning_run_id,
            {
                "status": status,
                "scored_count": max(0, int(scored_count)),
                "skipped_count": max(0, int(skipped_count)),
                "failed_count": max(0, int(failed_count)),
                "completed_at": completed_at,
            },
        )

    def record_reasoning_output(
        self,
        *,
        environment: Environment,
        reasoning_run_id: str,
        scanner_candidate_id: str | None,
        venue: str,
        instrument_id: str,
        model_provider: ModelProvider,
        prompt_version: str,
        status: str,
        directional_signal: str,
        signal_strength: Decimal,
        prompt_payload: dict,
        response_payload: dict,
        check_results: list | tuple,
        cost_usd: Decimal,
        prompt_tokens: int,
        completion_tokens: int,
        confidence: Decimal | None = None,
        estimated_probability: Decimal | None = None,
        output_thesis: str | None = None,
        refusal_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        prompt_token_count = max(0, int(prompt_tokens))
        completion_token_count = max(0, int(completion_tokens))
        return self.state.insert(
            f"{SHARED_SCHEMA}.reasoning_outputs",
            {
                "id": str(uuid4()),
                "reasoning_run_id": reasoning_run_id,
                "scanner_candidate_id": scanner_candidate_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "model_provider": model_provider.value,
                "prompt_version": prompt_version,
                "status": status,
                "refusal_reason": refusal_reason,
                "directional_signal": directional_signal,
                "signal_strength": Decimal(str(signal_strength)),
                "confidence": None if confidence is None else Decimal(str(confidence)),
                "estimated_probability": (
                    None if estimated_probability is None else Decimal(str(estimated_probability))
                ),
                "cost_usd": Decimal(str(cost_usd)),
                "prompt_tokens": prompt_token_count,
                "completion_tokens": completion_token_count,
                "total_tokens": prompt_token_count + completion_token_count,
                "prompt_payload": _json_ready(prompt_payload),
                "response_payload": _json_ready(response_payload),
                "check_results": _json_ready(list(check_results)),
                "output_thesis": output_thesis,
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def reasoning_runs(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.reasoning_runs")
            if row["environment"] == environment.value
        ]

    def reasoning_outputs(
        self,
        *,
        environment: Environment,
        reasoning_run_id: str | None = None,
        venue: str | None = None,
        model_provider: ModelProvider | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.reasoning_outputs")
            if row["environment"] == environment.value
        ]
        if reasoning_run_id is not None:
            rows = [row for row in rows if row["reasoning_run_id"] == reasoning_run_id]
        if venue is not None:
            rows = [row for row in rows if row["venue"] == venue]
        if model_provider is not None:
            rows = [row for row in rows if row["model_provider"] == model_provider.value]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

    def record_strategy_consensus_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        reasoning_run_id: str | None,
        trigger: str,
        status: str,
        config: dict,
        vote_count: int,
        approved_count: int,
        refused_count: int,
        started_at: datetime,
        completed_at: datetime,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.strategy_consensus_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "pipeline_run_id": pipeline_run_id,
                "reasoning_run_id": reasoning_run_id,
                "trigger": trigger,
                "status": status,
                "config": _json_ready(config),
                "vote_count": max(0, int(vote_count)),
                "approved_count": max(0, int(approved_count)),
                "refused_count": max(0, int(refused_count)),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def update_strategy_consensus_run_result(
        self,
        *,
        consensus_run_id: str,
        status: str,
        vote_count: int,
        approved_count: int,
        refused_count: int,
        completed_at: datetime,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.update_by_id(
            f"{SHARED_SCHEMA}.strategy_consensus_runs",
            consensus_run_id,
            {
                "status": status,
                "vote_count": max(0, int(vote_count)),
                "approved_count": max(0, int(approved_count)),
                "refused_count": max(0, int(refused_count)),
                "completed_at": completed_at,
            },
        )

    def record_strategy_vote(
        self,
        *,
        environment: Environment,
        consensus_run_id: str,
        reasoning_output_id: str | None,
        scanner_candidate_id: str | None,
        venue: str,
        instrument_id: str,
        model_provider: ModelProvider,
        strategy_name: str,
        status: str,
        source_payload: dict,
        direction: str | None = None,
        confidence: Decimal | None = None,
        refusal_reason: str | None = None,
        inputs_hash: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.strategy_votes",
            {
                "id": str(uuid4()),
                "consensus_run_id": consensus_run_id,
                "reasoning_output_id": reasoning_output_id,
                "scanner_candidate_id": scanner_candidate_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "model_provider": model_provider.value,
                "strategy_name": strategy_name,
                "direction": direction,
                "confidence": None if confidence is None else Decimal(str(confidence)),
                "status": status,
                "refusal_reason": refusal_reason,
                "inputs_hash": inputs_hash,
                "source_payload": _json_ready(source_payload),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def record_strategy_consensus_output(
        self,
        *,
        environment: Environment,
        consensus_run_id: str,
        venue: str,
        instrument_id: str,
        model_provider: ModelProvider,
        status: str,
        size_multiplier: Decimal,
        signal_count: int,
        strategy_names: list | tuple,
        source_payload: dict,
        side: str | None = None,
        refusal_reason: str | None = None,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.strategy_consensus_outputs",
            {
                "id": str(uuid4()),
                "consensus_run_id": consensus_run_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "model_provider": model_provider.value,
                "status": status,
                "side": side,
                "size_multiplier": Decimal(str(size_multiplier)),
                "signal_count": max(0, int(signal_count)),
                "strategy_names": _json_ready(list(strategy_names)),
                "refusal_reason": refusal_reason,
                "source_payload": _json_ready(source_payload),
                "created_at": created_at or datetime.now(UTC),
            },
        )

    def strategy_consensus_runs(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.strategy_consensus_runs")
            if row["environment"] == environment.value
        ]

    def strategy_votes(
        self,
        *,
        environment: Environment,
        consensus_run_id: str | None = None,
        model_provider: ModelProvider | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.strategy_votes")
            if row["environment"] == environment.value
        ]
        if consensus_run_id is not None:
            rows = [row for row in rows if row["consensus_run_id"] == consensus_run_id]
        if model_provider is not None:
            rows = [row for row in rows if row["model_provider"] == model_provider.value]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

    def strategy_consensus_outputs(
        self,
        *,
        environment: Environment,
        consensus_run_id: str | None = None,
        model_provider: ModelProvider | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.strategy_consensus_outputs")
            if row["environment"] == environment.value
        ]
        if consensus_run_id is not None:
            rows = [row for row in rows if row["consensus_run_id"] == consensus_run_id]
        if model_provider is not None:
            rows = [row for row in rows if row["model_provider"] == model_provider.value]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

    def record_execution_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        strategy_consensus_run_id: str | None,
        trigger: str,
        status: str,
        config: dict,
        intent_count: int,
        submitted_count: int,
        simulated_count: int,
        refused_count: int,
        reconciliation_count: int,
        started_at: datetime,
        completed_at: datetime,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.execution_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "pipeline_run_id": pipeline_run_id,
                "strategy_consensus_run_id": strategy_consensus_run_id,
                "trigger": trigger,
                "status": status,
                "config": _json_ready(config),
                "intent_count": max(0, int(intent_count)),
                "submitted_count": max(0, int(submitted_count)),
                "simulated_count": max(0, int(simulated_count)),
                "refused_count": max(0, int(refused_count)),
                "reconciliation_count": max(0, int(reconciliation_count)),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def update_execution_run_result(
        self,
        *,
        execution_run_id: str,
        status: str,
        intent_count: int,
        submitted_count: int,
        simulated_count: int,
        refused_count: int,
        reconciliation_count: int,
        completed_at: datetime,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.update_by_id(
            f"{SHARED_SCHEMA}.execution_runs",
            execution_run_id,
            {
                "status": status,
                "intent_count": max(0, int(intent_count)),
                "submitted_count": max(0, int(submitted_count)),
                "simulated_count": max(0, int(simulated_count)),
                "refused_count": max(0, int(refused_count)),
                "reconciliation_count": max(0, int(reconciliation_count)),
                "completed_at": completed_at,
            },
        )

    def record_order_intent(
        self,
        *,
        environment: Environment,
        execution_run_id: str,
        pipeline_run_id: str,
        strategy_consensus_output_id: str | None,
        venue: str,
        instrument_id: str,
        model_provider: ModelProvider,
        side: str,
        order_type: str,
        status: str,
        notional_usd: Decimal,
        size_multiplier: Decimal,
        idempotency_key: str,
        risk_payload: dict,
        source_payload: dict,
        refusal_reason: str | None = None,
        venue_order_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        table = f"{SHARED_SCHEMA}.order_intents"
        for row in self.state.rows(table):
            if row["idempotency_key"] == idempotency_key:
                row.update(
                    {
                        "status": status,
                        "refusal_reason": refusal_reason,
                        "venue_order_id": venue_order_id,
                        "risk_payload": _json_ready(risk_payload),
                        "source_payload": _json_ready(source_payload),
                        "updated_at": updated_at or datetime.now(UTC),
                    }
                )
                return row
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            table,
            {
                "id": str(uuid4()),
                "execution_run_id": execution_run_id,
                "pipeline_run_id": pipeline_run_id,
                "strategy_consensus_output_id": strategy_consensus_output_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "model_provider": model_provider.value,
                "side": side,
                "order_type": order_type,
                "status": status,
                "notional_usd": Decimal(str(notional_usd)),
                "size_multiplier": Decimal(str(size_multiplier)),
                "idempotency_key": idempotency_key,
                "refusal_reason": refusal_reason,
                "venue_order_id": venue_order_id,
                "risk_payload": _json_ready(risk_payload),
                "source_payload": _json_ready(source_payload),
                "created_at": now,
                "updated_at": updated_at or now,
            },
        )

    def execution_runs(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.execution_runs")
            if row["environment"] == environment.value
        ]

    def order_intents(
        self,
        *,
        environment: Environment,
        execution_run_id: str | None = None,
        pipeline_run_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.order_intents")
            if row["environment"] == environment.value
        ]
        if execution_run_id is not None:
            rows = [row for row in rows if row["execution_run_id"] == execution_run_id]
        if pipeline_run_id is not None:
            rows = [row for row in rows if row["pipeline_run_id"] == pipeline_run_id]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows

    def record_exit_run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        status: str,
        config: dict,
        open_position_count: int,
        triggered_count: int,
        simulated_count: int,
        submitted_count: int,
        refused_count: int,
        started_at: datetime,
        completed_at: datetime,
        created_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.insert(
            f"{SHARED_SCHEMA}.exit_runs",
            {
                "id": str(uuid4()),
                "environment": environment.value,
                "pipeline_run_id": pipeline_run_id,
                "trigger": trigger,
                "status": status,
                "config": _json_ready(config),
                "open_position_count": max(0, int(open_position_count)),
                "triggered_count": max(0, int(triggered_count)),
                "simulated_count": max(0, int(simulated_count)),
                "submitted_count": max(0, int(submitted_count)),
                "refused_count": max(0, int(refused_count)),
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at or completed_at,
            },
        )

    def update_exit_run_result(
        self,
        *,
        exit_run_id: str,
        status: str,
        open_position_count: int,
        triggered_count: int,
        simulated_count: int,
        submitted_count: int,
        refused_count: int,
        completed_at: datetime,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        return self.state.update_by_id(
            f"{SHARED_SCHEMA}.exit_runs",
            exit_run_id,
            {
                "status": status,
                "open_position_count": max(0, int(open_position_count)),
                "triggered_count": max(0, int(triggered_count)),
                "simulated_count": max(0, int(simulated_count)),
                "submitted_count": max(0, int(submitted_count)),
                "refused_count": max(0, int(refused_count)),
                "completed_at": completed_at,
            },
        )

    def record_exit_intent(
        self,
        *,
        environment: Environment,
        exit_run_id: str,
        pipeline_run_id: str,
        venue: str,
        instrument_id: str,
        position_id: str,
        trigger_type: str,
        status: str,
        side: str,
        notional_usd: Decimal,
        idempotency_key: str,
        source_payload: dict,
        model_provider: ModelProvider | None = None,
        quantity: Decimal | None = None,
        threshold: Decimal | None = None,
        observed_value: Decimal | None = None,
        refusal_reason: str | None = None,
        venue_order_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> dict:
        self.ensure_schema(SHARED_SCHEMA)
        table = f"{SHARED_SCHEMA}.exit_intents"
        for row in self.state.rows(table):
            if row["idempotency_key"] == idempotency_key:
                row.update(
                    {
                        "exit_run_id": exit_run_id,
                        "pipeline_run_id": pipeline_run_id,
                        "position_id": position_id,
                        "trigger_type": trigger_type,
                        "status": status,
                        "quantity": None if quantity is None else Decimal(str(quantity)),
                        "notional_usd": Decimal(str(notional_usd)),
                        "threshold": None if threshold is None else Decimal(str(threshold)),
                        "observed_value": (
                            None if observed_value is None else Decimal(str(observed_value))
                        ),
                        "refusal_reason": refusal_reason,
                        "venue_order_id": venue_order_id,
                        "source_payload": _json_ready(source_payload),
                        "updated_at": updated_at or datetime.now(UTC),
                    }
                )
                return row
        now = created_at or datetime.now(UTC)
        return self.state.insert(
            table,
            {
                "id": str(uuid4()),
                "exit_run_id": exit_run_id,
                "pipeline_run_id": pipeline_run_id,
                "environment": environment.value,
                "venue": venue,
                "instrument_id": instrument_id,
                "position_id": position_id,
                "model_provider": model_provider.value if model_provider else None,
                "trigger_type": trigger_type,
                "status": status,
                "side": side,
                "quantity": None if quantity is None else Decimal(str(quantity)),
                "notional_usd": Decimal(str(notional_usd)),
                "threshold": None if threshold is None else Decimal(str(threshold)),
                "observed_value": None if observed_value is None else Decimal(str(observed_value)),
                "idempotency_key": idempotency_key,
                "refusal_reason": refusal_reason,
                "venue_order_id": venue_order_id,
                "source_payload": _json_ready(source_payload),
                "created_at": now,
                "updated_at": updated_at or now,
            },
        )

    def exit_runs(self, *, environment: Environment) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        return [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.exit_runs")
            if row["environment"] == environment.value
        ]

    def exit_intents(
        self,
        *,
        environment: Environment,
        exit_run_id: str | None = None,
        pipeline_run_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.exit_intents")
            if row["environment"] == environment.value
        ]
        if exit_run_id is not None:
            rows = [row for row in rows if row["exit_run_id"] == exit_run_id]
        if pipeline_run_id is not None:
            rows = [row for row in rows if row["pipeline_run_id"] == pipeline_run_id]
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
        quarantine_reason = self.alpaca_account_quarantine_reason(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
        )
        if quarantine_reason:
            return AlpacaAccountRegistrationResult(
                live_trading_allowed=False,
                refusal_reason=quarantine_reason,
            )
        existing = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_registry")
            if row["environment"] == environment.value and row["account_mode"] == account_mode
        ]
        latest_by_provider: dict[str, dict[str, Any]] = {}
        for row in existing:
            provider = str(row["model_provider"])
            current = latest_by_provider.get(provider)
            row_created_at = row.get("created_at")
            current_created_at = current.get("created_at") if current else None
            if current is None or (
                isinstance(row_created_at, datetime)
                and (
                    not isinstance(current_created_at, datetime)
                    or row_created_at > current_created_at
                )
            ):
                latest_by_provider[provider] = row
        for row in latest_by_provider.values():
            same_account = row["account_id"] == account_id
            same_provider = row["model_provider"] == model_provider.value
            if same_account and same_provider:
                return AlpacaAccountRegistrationResult(live_trading_allowed=True)
            different_provider = row["model_provider"] != model_provider.value
            if same_account and different_provider:
                reason = "duplicate Alpaca account identifier"
                quarantine_id = sha256(
                    f"{environment.value}:{account_mode}:{account_id}".encode("utf-8")
                ).hexdigest()
                self.state.upsert_by_id(
                    f"{SHARED_SCHEMA}.alpaca_account_quarantines",
                    quarantine_id,
                    {
                        "environment": environment.value,
                        "account_mode": account_mode,
                        "account_id": account_id,
                        "model_providers": sorted(
                            {row["model_provider"], model_provider.value}
                        ),
                        "reason": reason,
                        "active": True,
                        "created_at": datetime.now(UTC),
                        "updated_at": datetime.now(UTC),
                        "resolved_at": None,
                    },
                )
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
                        "refusal_reason": reason,
                    },
                )
                return AlpacaAccountRegistrationResult(
                    live_trading_allowed=False,
                    refusal_reason=reason,
                )
        current_provider_route = latest_by_provider.get(model_provider.value)
        if current_provider_route is not None:
            self.state.update_by_id(
                f"{SHARED_SCHEMA}.alpaca_account_registry",
                str(current_provider_route["id"]),
                {
                    "account_id": account_id,
                    "created_at": datetime.now(UTC),
                },
            )
            return AlpacaAccountRegistrationResult(live_trading_allowed=True)
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

    def alpaca_account_quarantine_reason(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
    ) -> str | None:
        rows = self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_quarantines")
        match = next(
            (
                row
                for row in rows
                if row["environment"] == environment.value
                and row["account_mode"] == account_mode
                and row["account_id"] == account_id
                and row.get("active") is True
            ),
            None,
        )
        return str(match.get("reason") or "") if match else None

    def reconcile_alpaca_account_quarantines(
        self,
        *,
        environment: Environment,
        routes: dict[ModelProvider, tuple[str, str]],
    ) -> None:
        """Resolve a quarantine only after all implicated providers report distinct routes."""

        for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_quarantines"):
            if row.get("environment") != environment.value or row.get("active") is not True:
                continue
            providers = {
                ModelProvider(str(value))
                for value in row.get("model_providers") or []
            }
            if not providers or any(provider not in routes for provider in providers):
                continue
            provider_routes = [routes[provider] for provider in providers]
            if len(set(provider_routes)) != len(provider_routes):
                continue
            now = datetime.now(UTC)
            self.state.update_by_id(
                f"{SHARED_SCHEMA}.alpaca_account_quarantines",
                str(row["id"]),
                {"active": False, "resolved_at": now, "updated_at": now},
            )
            self.record_audit_event(
                event_type="alpaca_account_quarantine_resolved",
                actor="system",
                action="alpaca_account.quarantine_resolved",
                environment=environment,
                entity_id=str(row.get("account_id") or ""),
                metadata={
                    "account_mode": str(row.get("account_mode") or ""),
                    "model_providers": sorted(provider.value for provider in providers),
                },
            )

    def alpaca_provider_has_quarantined_account(
        self,
        *,
        environment: Environment,
        account_mode: str,
        model_provider: ModelProvider,
    ) -> bool:
        return any(
            row.get("environment") == environment.value
            and row.get("account_mode") == account_mode
            and row.get("active") is True
            and model_provider.value in (row.get("model_providers") or [])
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_quarantines")
        )

    def alpaca_account_registrations(
        self,
        *,
        environment: Environment,
        account_mode: str | None = None,
        model_provider: ModelProvider | None = None,
    ) -> list[dict]:
        """Return internal Alpaca account routing records."""

        self.ensure_schema(SHARED_SCHEMA)
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_registry")
            if row["environment"] == environment.value
        ]
        if account_mode is not None:
            rows = [row for row in rows if row["account_mode"] == account_mode]
        if model_provider is not None:
            rows = [row for row in rows if row["model_provider"] == model_provider.value]
        latest_by_provider: dict[str, dict[str, Any]] = {}
        for row in rows:
            provider = str(row["model_provider"])
            current = latest_by_provider.get(provider)
            row_created_at = row.get("created_at")
            current_created_at = current.get("created_at") if current else None
            if current is None or (
                isinstance(row_created_at, datetime)
                and (
                    not isinstance(current_created_at, datetime)
                    or row_created_at > current_created_at
                )
            ):
                latest_by_provider[provider] = row
        rows = list(latest_by_provider.values())
        quarantined_accounts = {
            (row["account_mode"], row["account_id"])
            for row in self.state.rows(f"{SHARED_SCHEMA}.alpaca_account_quarantines")
            if row["environment"] == environment.value and row.get("active") is True
        }
        return [
            {
                **row,
                "live_trading_allowed": (
                    (row["account_mode"], row["account_id"]) not in quarantined_accounts
                ),
            }
            for row in rows
        ]


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

    def record_strategy_signal(self, signal: StrategySignal) -> dict:
        self.ensure_schema(provider_schema(signal.model_provider))
        return self.state.insert(
            f"{self.schema_name}.strategy_signals",
            {
                "id": str(uuid4()),
                "strategy_name": signal.strategy_name,
                "direction": signal.direction.value,
                "inputs_hash": signal.inputs_hash,
                "created_at": signal.created_at,
            },
        )

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
