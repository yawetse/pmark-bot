"""Broker history totals must not sort or materialize persisted payloads."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import (
    DatabaseState, PersistentDatabaseState, PersistenceUnavailableError,
    RepositoryRegistry, UnitOfWork, run_migrations,
)
from app.domain import Environment
from app.main import AppSettings
from app.services.runtime_status_service import RuntimeStatusService
from tests.spec.test_startup_migration_contention import postgres_engine


COUNT_TABLES = {
    "orders": "shared.alpaca_historical_orders",
    "fills": "shared.alpaca_historical_fills",
    "positions": "shared.alpaca_historical_positions",
    "accountSnapshots": "shared.alpaca_broker_account_snapshots",
    "bars": "shared.stock_bars",
    "pnlSnapshots": "shared.alpaca_symbol_pnl_snapshots",
}


def service_for(state):
    return RuntimeStatusService(settings=AppSettings(), registry=RepositoryRegistry(state))


def test_broker_totals_are_exact_environment_filtered_without_loading_payloads(monkeypatch):
    """REQ-ALP-017/REQ-UI-004: preserve exact counts across large mixed histories."""
    state = DatabaseState()
    for table in COUNT_TABLES.values():
        for environment, count in ((Environment.DEVELOPMENT, 1001), (Environment.PRODUCTION, 3)):
            for i in range(count):
                state.insert(table, {"id": f"{environment.value}-{i}",
                    "environment": environment.value, "raw_payload": {"synthetic": "unused"}})
    service = service_for(state)
    original_rows = state.rows

    def refuse_history_materialization(table, **kwargs):
        assert table not in COUNT_TABLES.values(), "summary must not load history records"
        return original_rows(table, **kwargs)

    monkeypatch.setattr(state, "rows", refuse_history_materialization)
    for environment, expected in ((Environment.DEVELOPMENT, 1001), (Environment.PRODUCTION, 3)):
        summary = service.broker_history_summary(environment)
        assert summary["counts"] == {**dict.fromkeys(COUNT_TABLES, expected), "checkpoints": 0}
        assert summary["status"] == "stored"
        assert summary["checkpoints"] == []
        assert summary["lastUpdatedAt"] is None


@pytest.mark.parametrize("table", COUNT_TABLES.values())
def test_broker_count_failure_preserves_unavailable_response(table):
    """REQ-DB-007: a failed aggregate must not imply a healthy empty history."""
    state = DatabaseState()
    service = service_for(state)
    state.fail_on_read_tables.add(table)
    summary = service.broker_history_summary(Environment.DEVELOPMENT)
    assert summary["status"] == "unavailable"
    assert summary["counts"] == {**dict.fromkeys(COUNT_TABLES, 0), "checkpoints": 0}
    assert summary["checkpoints"] == []
    assert summary["lastUpdatedAt"] is None


def test_broker_checkpoint_status_count_and_latest_are_preserved():
    """REQ-ALP-017: retain all matching checkpoints and the latest-ten display."""
    state = DatabaseState()
    now = datetime(2026, 10, 6, tzinfo=UTC)
    for i in range(13):
        state.insert("shared.historical_import_checkpoints", {
            "id": str(i), "environment": "development", "source": f"alpaca_stock_bars:{i}",
            "cursor_type": "timestamp", "cursor_value": str(i),
            "status": "failed" if i == 0 else "complete", "metadata": {},
            "last_success_at": now + timedelta(minutes=i),
            "updated_at": now + timedelta(minutes=i),
        })
    for environment, source in (("production", "alpaca_stock_bars:other"),
                                 ("development", "polygon_order_filled")):
        state.insert("shared.historical_import_checkpoints", {
            "environment": environment, "source": source, "status": "rate_limited"})
    summary = service_for(state).broker_history_summary(Environment.DEVELOPMENT)
    assert summary["counts"]["checkpoints"] == 13
    assert summary["status"] == "failed"
    assert [row["id"] for row in summary["checkpoints"]] == [str(i) for i in range(12, 2, -1)]
    assert summary["lastUpdatedAt"] == (now + timedelta(minutes=12)).isoformat()


def test_postgres_broker_count_survives_bounded_sort_spill(postgres_engine):
    """Synthetic PG18: existing full read spills; summary counts need no sort."""
    with postgres_engine.begin() as connection:
        run_migrations(connection)
        connection.exec_driver_sql("""
            INSERT INTO shared.alpaca_historical_positions
                (id, environment, account_mode, account_id, symbol, quantity,
                 raw_payload, observed_at, created_at)
            SELECT md5(i::text), CASE WHEN mod(i, 2) = 0 THEN 'development' ELSE 'production' END,
                'paper', 'synthetic-account', 'SYNTH', 1,
                jsonb_build_object('synthetic', repeat(md5(i::text), 16)), now(),
                '2026-01-01'::timestamptz + (20000-i) * interval '1 second'
            FROM generate_series(1, 20000) AS i
        """)
        connection.exec_driver_sql("ANALYZE shared.alpaca_historical_positions")
    state = PersistentDatabaseState(sessionmaker(bind=postgres_engine, expire_on_commit=False))
    with pytest.raises(PersistenceUnavailableError) as failed:
        with UnitOfWork(state):
            session = state._active_session.get()
            session.execute(text("SET LOCAL work_mem = '64kB'"))
            session.execute(text("SET LOCAL temp_file_limit = '1MB'"))
            state.rows("shared.alpaca_historical_positions")
    assert failed.value.__cause__.orig.sqlstate == "53400"
    service = service_for(state)
    with UnitOfWork(state):
        session = state._active_session.get()
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '1MB'"))
        summary = service.broker_history_summary(Environment.DEVELOPMENT)
    assert summary["status"] == "stored"
    assert summary["counts"]["positions"] == 10000
    assert summary["counts"]["checkpoints"] == 0
