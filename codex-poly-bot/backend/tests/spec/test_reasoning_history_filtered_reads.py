"""Filter reasoning history before sorting without changing consensus inputs."""

from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from sqlalchemy.dialects import postgresql

from app.db import (
    DatabaseState, PersistentDatabaseState, PersistenceUnavailableError, RepositoryRegistry,
)
from app.domain import Environment, ModelProvider


TABLE = "shared.reasoning_outputs"
SCOPES = list(product(Environment, (None, "run-a", ""), (None, "alpaca", ""),
                      (None, ModelProvider.OPENAI, ModelProvider.CLAUDE),
                      (None, "scored", "")))


@pytest.fixture(scope="module")
def history():
    state = DatabaseState()
    now = datetime(2026, 10, 10, tzinfo=UTC)
    for environment, run, venue, provider, status in product(
        Environment, ("run-a", ""), ("alpaca", ""), ModelProvider, ("scored", ""),
    ):
        for i in range(125):
            state.insert(TABLE, {
                "id": f"{environment.value}/{run}/{venue}/{provider.value}/{status}/{i:04}",
                "environment": environment.value, "reasoning_run_id": run,
                "venue": venue, "model_provider": provider.value, "status": status,
                "created_at": now - timedelta(seconds=i // 2),
                "prompt_payload": {"synthetic": i}, "response_payload": {"synthetic": i},
            })
    return state


def expected_filters(environment, run, venue, provider, status):
    filters = {"environment": environment.value}
    for key, value in (("reasoning_run_id", run), ("venue", venue),
                       ("model_provider", provider.value if provider is not None else None),
                       ("status", status)):
        if value is not None:
            filters[key] = value
    return filters


@pytest.mark.parametrize("environment,run,venue,provider,status", SCOPES)
def test_scoped_history_preserves_every_row_payload_and_order(
    monkeypatch, history, environment, run, venue, provider, status,
):
    original = history.rows
    filters = expected_filters(environment, run, venue, provider, status)
    expected = [row for row in original(TABLE)
                if all(row[key] == value for key, value in filters.items())]
    calls = []

    def capture(table, **kwargs):
        calls.append((table, kwargs))
        return original(table, **kwargs)

    monkeypatch.setattr(history, "rows", capture)
    actual = RepositoryRegistry(history).shared().reasoning_outputs(
        environment=environment, reasoning_run_id=run, venue=venue,
        model_provider=provider, status=status,
    )
    assert actual == expected
    assert len(actual) >= 125  # preserve full matching history, including empty-string scopes
    assert calls == [(TABLE, {"filters": filters})]


@pytest.mark.parametrize("environment,run,venue,provider,status", SCOPES)
def test_postgres_statement_filters_before_unchanged_sort_without_limit(
    environment, run, venue, provider, status,
):
    statements = []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return self

        def mappings(self):
            return self

        def all(self):
            return []

        def close(self):
            pass

    state = PersistentDatabaseState(Session)
    RepositoryRegistry(state).shared().reasoning_outputs(
        environment=environment, reasoning_run_id=run, venue=venue,
        model_provider=provider, status=status,
    )
    statement = statements[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    filters = expected_filters(environment, run, venue, provider, status)
    assert "WHERE shared.reasoning_outputs.environment =" in sql
    for key in ("reasoning_run_id", "venue", "model_provider", "status"):
        assert (f"AND shared.reasoning_outputs.{key} =" in sql) == (key in filters)
    assert sorted(statement.params.values()) == sorted(filters.values())
    assert "ORDER BY shared.reasoning_outputs.created_at ASC, shared.reasoning_outputs.id ASC" in sql
    assert "LIMIT" not in sql


def test_scoped_read_failure_is_not_reported_as_an_empty_history():
    state = DatabaseState(available=False)
    with pytest.raises(PersistenceUnavailableError):
        RepositoryRegistry(state).shared().reasoning_outputs(
            environment=Environment.DEVELOPMENT, reasoning_run_id="run-a", status="scored",
        )
