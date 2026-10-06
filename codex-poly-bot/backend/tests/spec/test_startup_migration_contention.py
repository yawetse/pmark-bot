"""Optional local PostgreSQL integration tests for warm-start migration locks."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db import migration_plan, run_migrations


@pytest.fixture
def postgres_engine():
    """Use only a disposable database on an explicitly selected private test socket."""
    dsn = os.environ.get("NILES_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("NILES_TEST_POSTGRES_DSN selects the temporary offline PostgreSQL instance")
    url = make_url(dsn)
    socket = Path(str(url.query.get("host", "")))
    if (url.host is not None or url.password is not None or socket.parent.parent != Path("/tmp")
            or not socket.parent.name.startswith("niles-pg18.3-") or socket.name != "socket"):
        pytest.fail("integration tests require the private temporary PostgreSQL socket")
    database = f"niles_migration_test_{uuid4().hex}"
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = create_engine(url.set(database=database))
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{database}"')
        admin.dispose()


def test_req_db_002_warm_start_does_not_wait_for_existing_index_writer(postgres_engine):
    """TST-REQ-DB-002-STARTUP-01: repeated migrations avoid redundant writer locks."""
    with postgres_engine.begin() as connection:
        expected = run_migrations(connection)
    with postgres_engine.begin() as writer:
        writer.exec_driver_sql(
            "INSERT INTO shared.job_runs "
            "(id, job_name, status, heartbeat_at, metadata, created_at) "
            "VALUES ('synthetic-writer', 'test-only', 'running', now(), '{}'::jsonb, now())"
        )
        with postgres_engine.begin() as startup:
            startup.exec_driver_sql("SET LOCAL lock_timeout = '250ms'")
            actual = run_migrations(startup)
    assert actual == expected
    assert any("ix_job_runs_job_name_created_at" in statement for statement in actual.sql)


def test_req_db_002_missing_index_still_created_on_repeat_migration(postgres_engine):
    """TST-REQ-DB-002-STARTUP-02: avoid locks without skipping missing schema work."""
    with postgres_engine.begin() as connection:
        expected = run_migrations(connection)
        assert len(expected.table_names) == 64
        connection.exec_driver_sql("DROP INDEX shared.ix_job_runs_job_name_created_at")
        connection.exec_driver_sql(
            "CREATE INDEX ix_job_runs_job_name_created_at ON claude.trade_decisions (id)"
        )
        assert connection.execute(text("SELECT to_regclass('shared.ix_job_runs_job_name_created_at')")).scalar() is None
    with postgres_engine.begin() as connection:
        actual = run_migrations(connection)
        index = connection.execute(text("SELECT to_regclass('shared.ix_job_runs_job_name_created_at')")).scalar()
    assert actual == migration_plan()
    assert index == "shared.ix_job_runs_job_name_created_at"


def test_req_db_002_catalog_failure_is_not_silently_treated_as_migration_success():
    """TST-REQ-DB-002-STARTUP-03: initialization remains fail-closed on metadata failure."""
    error = RuntimeError("metadata read unavailable")

    class UnavailableConnection:
        def execute(self, *args, **kwargs):
            raise error

    with pytest.raises(RuntimeError) as raised:
        run_migrations(UnavailableConnection())
    assert raised.value is error
