"""Preserve full financial histories while filtering before database sorting."""

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.db import (
    DatabaseState, PersistentDatabaseState, PersistenceUnavailableError,
    RepositoryRegistry, UnitOfWork, run_migrations,
)
from app.domain import Environment
from tests.spec.test_startup_migration_contention import postgres_engine


TABLE = "shared.alpaca_historical_positions"
SCOPES = list(product(list(Environment), (None, "paper", ""), (None, "account-a", "")))


def baseline(rows, environment, account_mode, account_id):
    return [row for row in rows if row["environment"] == environment.value
            and (account_mode is None or row["account_mode"] == account_mode)
            and (account_id is None or row["account_id"] == account_id)]


def selected_ids(rows, last_tie=False):
    """Mirror caller comparisons; unchanged row sequence must preserve both ties."""
    selected = {}
    for row in rows:
        key = (row["account_id"], row["symbol"])
        prior = selected.get(key)
        observed = row.get("observed_at") or datetime.min.replace(tzinfo=UTC)
        previous = (prior.get("observed_at") or datetime.min.replace(tzinfo=UTC)) if prior else observed
        if prior is None or observed > previous or (last_tie and observed == previous):
            selected[key] = row
    return {key: row["id"] for key, row in selected.items()}


@pytest.mark.parametrize("environment,account_mode,account_id", SCOPES)
def test_memory_position_scope_preserves_complete_history_and_ties(
    monkeypatch, environment, account_mode, account_id,
):
    state = DatabaseState()
    now = datetime(2026, 10, 6, tzinfo=UTC)
    for i in range(1208):
        for env, mode, account in product(Environment, ("paper", ""), ("account-a", "")):
            state.insert(TABLE, {"id": f"{env.value}/{mode}/{account}/{i}",
                "environment": env.value, "account_mode": mode, "account_id": account,
                "symbol": "SYNTH", "quantity": i,
                "observed_at": None if i < 2 else now,
                "created_at": now - timedelta(seconds=i), "raw_payload": {"synthetic": i}})
    original = state.rows
    expected = baseline(original(TABLE), environment, account_mode, account_id)
    seen = []

    def capture(table, **kwargs):
        seen.append(kwargs)
        return original(table, **kwargs)

    monkeypatch.setattr(state, "rows", capture)
    actual = RepositoryRegistry(state).shared().alpaca_historical_positions(
        environment=environment, account_mode=account_mode, account_id=account_id,
    )
    assert actual == expected
    assert len(actual) >= 1208  # no arbitrary latest-row or pagination truncation
    for last_tie in (False, True):
        assert selected_ids(actual, last_tie) == selected_ids(expected, last_tie)
    filters = {"environment": environment.value}
    if account_mode is not None:
        filters["account_mode"] = account_mode
    if account_id is not None:
        filters["account_id"] = account_id
    assert seen == [{"filters": filters}]


def test_postgres_position_scope_filters_before_sort_without_truncating(postgres_engine):
    with postgres_engine.begin() as connection:
        run_migrations(connection)
        connection.exec_driver_sql("""
            INSERT INTO shared.alpaca_historical_positions
                (id, environment, account_mode, account_id, symbol, quantity,
                 raw_payload, observed_at, created_at)
            SELECT md5(i::text), CASE WHEN mod(i, 8) < 4 THEN 'development' ELSE 'production' END,
                CASE WHEN mod(i, 4) < 2 THEN 'paper' ELSE '' END,
                CASE WHEN mod(i, 2) = 0 THEN 'account-a' ELSE '' END, 'SYNTH', i,
                jsonb_build_object('synthetic', repeat(md5(i::text), 16)), '2026-10-06'::timestamptz,
                '2026-01-01'::timestamptz + (10000-i) * interval '1 second'
            FROM generate_series(1, 10000) AS i
        """)
    state = PersistentDatabaseState(sessionmaker(bind=postgres_engine, expire_on_commit=False))
    all_rows = state.rows(TABLE)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "FROM shared.alpaca_historical_positions" in statement:
            statements.append(statement)

    event.listen(postgres_engine, "before_cursor_execute", capture)
    try:
        for environment, mode, account in SCOPES:
            expected = baseline(all_rows, environment, mode, account)
            actual = RepositoryRegistry(state).shared().alpaca_historical_positions(
                environment=environment, account_mode=mode, account_id=account,
            )
            assert actual == expected
            assert len(actual) >= 1250 if expected else actual == []
            for last_tie in (False, True):
                assert selected_ids(actual, last_tie) == selected_ids(expected, last_tie)
            sql = statements[-1]
            assert "WHERE shared.alpaca_historical_positions.environment =" in sql
            assert (" AND shared.alpaca_historical_positions.account_mode =" in sql) == (mode is not None)
            assert (" AND shared.alpaca_historical_positions.account_id =" in sql) == (account is not None)
            assert "ORDER BY shared.alpaca_historical_positions.created_at ASC, shared.alpaca_historical_positions.id ASC" in sql
            assert "LIMIT" not in sql
    finally:
        event.remove(postgres_engine, "before_cursor_execute", capture)

    # Same temp budget: narrow account history fits; environment-only history
    # still spills. Predicate pushdown reduces exposure without promising a cap.
    with UnitOfWork(state):
        session = state._active_session.get()
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '1MB'"))
        actual = RepositoryRegistry(state).shared().alpaca_historical_positions(
            environment=Environment.DEVELOPMENT, account_mode="paper", account_id="account-a",
        )
        assert actual == baseline(all_rows, Environment.DEVELOPMENT, "paper", "account-a")
    with pytest.raises(PersistenceUnavailableError) as failed:
        with UnitOfWork(state):
            session = state._active_session.get()
            session.execute(text("SET LOCAL work_mem = '64kB'"))
            session.execute(text("SET LOCAL temp_file_limit = '1MB'"))
            RepositoryRegistry(state).shared().alpaca_historical_positions(
                environment=Environment.DEVELOPMENT,
            )
    assert failed.value.__cause__.orig.sqlstate == "53400"
