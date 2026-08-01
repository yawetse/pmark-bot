"""Executable specifications for recurring funding and cash-flow reconciliation."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.aws.ses import InMemorySesEmailAdapter
from app.db import (
    PersistenceUnavailableError,
    PersistentDatabaseState,
    RepositoryRegistry,
    migration_plan,
)
from app.domain import (
    CashFlowStatus,
    Environment,
    FundingCadence,
    FundingConfig,
    FundingDirection,
    FundingExecutionMode,
    FundingOccurrenceKeyInput,
    FundingOccurrenceStatus,
    FundingSchedule,
    ModelProvider,
    Venue,
    VenueCashFlow,
    build_funding_occurrence_key,
)
from app.main import AppSettings, _portfolio_refresh_loop, create_app
from app.services.config_service import default_config_payload
from app.services.funding_service import (
    FundingRepository,
    FundingService,
    add_business_days,
    adjusted_trading_performance,
    adjust_to_business_day,
    calculate_low_balance_gap,
    funding_account_ref,
    normalize_alpaca_funding_activity,
    normalize_polymarket_funding_activity,
    schedule_due_at,
)
from app.services.venue_portfolio_service import (
    ProviderBackedVenuePortfolioSource,
    StaticVenuePortfolioSource,
    VenuePortfolioService,
    _account_ref,
)


NOW = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
ACCOUNT_REF = "alpaca:account-safe"


def _schedule(
    *,
    schedule_id: str = "weekly-openai",
    cadence: FundingCadence = FundingCadence.WEEKLY,
    mode: FundingExecutionMode = FundingExecutionMode.OBSERVE,
    amount: str = "100.00",
    venue: Venue = Venue.ALPACA,
    provider: ModelProvider = ModelProvider.OPENAI,
) -> FundingSchedule:
    return FundingSchedule(
        id=schedule_id,
        enabled=True,
        venue=venue,
        model_provider=provider,
        cadence=cadence,
        execution_mode=mode,
        direction=FundingDirection.DEPOSIT,
        amount_usd=amount,
        iso_weekday=5 if cadence == FundingCadence.WEEKLY else None,
        day_of_month=31 if cadence == FundingCadence.MONTHLY else None,
        target_balance_usd="500.00" if cadence == FundingCadence.LOW_BALANCE else None,
    )


def _cash_flow(
    *,
    transaction_id: str = "cash-1",
    amount: str = "100.00",
    effective_at: datetime = NOW,
    provider: ModelProvider = ModelProvider.OPENAI,
) -> VenueCashFlow:
    return VenueCashFlow(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        model_providers=(provider,),
        account_ref=ACCOUNT_REF,
        venue_transaction_id=transaction_id,
        activity_type="CSD",
        direction=FundingDirection.DEPOSIT,
        amount_usd=amount,
        status=CashFlowStatus.COMPLETED,
        effective_at=effective_at,
        effective_time_precision="timestamp",
        observed_at=effective_at,
        updated_at=effective_at,
    )


def test_req_fnd_001_03_venue_activity_is_normalized_without_ambiguous_transfers() -> None:
    """TST-REQ-FND-001-03, TST-REQ-FND-001-04: documented cash activity is normalized."""

    alpaca = normalize_alpaca_funding_activity(
        {
            "id": "alpaca-csd-1",
            "activity_type": "CSD",
            "net_amount": "125.00",
            "date": "2026-07-31",
            "status": "completed",
        },
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    )
    polymarket = normalize_polymarket_funding_activity(
        {
            "id": "pm-deposit-1",
            "type": "ACCOUNT_ADVANCED_DEPOSIT",
            "amount": {"value": "50.00"},
            "updateTime": "2026-07-31T14:00:00Z",
        },
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.CLAUDE,
        account_ref="polymarket:safe",
        observed_at=NOW,
    )

    assert alpaca is not None
    assert alpaca.direction == FundingDirection.DEPOSIT
    assert alpaca.effective_time_precision == "date"
    assert alpaca.effective_at.hour == 13  # 09:00 EDT in UTC.
    assert polymarket is not None
    assert polymarket.direction == FundingDirection.DEPOSIT
    signed_transfer = normalize_alpaca_funding_activity(
        {"id": "signed", "activity_type": "TRANS", "net_amount": "-5.00"},
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    )
    assert signed_transfer is not None
    assert signed_transfer.direction == FundingDirection.WITHDRAWAL
    assert normalize_alpaca_funding_activity(
        {"id": "ambiguous", "activity_type": "TRANS", "amount": "5.00"},
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    ) is None


def test_req_fnd_001_05_alpaca_activity_read_is_bounded_and_independent() -> None:
    """TST-REQ-FND-001-05 and TST-REQ-FND-004-02: account activity reads are bounded."""

    def handler(request):
        activity_type = request.url.path.rsplit("/", 1)[-1]
        payload = {
            "CSD": [
                {
                    "id": "deposit-1",
                    "activity_type": "CSD",
                    "net_amount": "25.00",
                    "date": "2026-07-31",
                }
            ],
            "CSW": [
                {
                    "id": "withdrawal-1",
                    "activity_type": "CSW",
                    "net_amount": "-5.00",
                    "date": "2026-07-30",
                }
                ],
                "TRANS": [
                {"id": "ambiguous", "activity_type": "TRANS", "amount": "10.00"}
                ],
        }[activity_type]
        return httpx.Response(200, json=payload, request=request)

    source = ProviderBackedVenuePortfolioSource(
        {},
        alpaca_transport=httpx.MockTransport(handler),
    )
    flows, status = source._alpaca_funding_activity(
        base_url="https://paper-api.alpaca.markets",
        headers={"APCA-API-KEY-ID": "key", "APCA-API-SECRET-KEY": "secret"},
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    )

    assert status == "ready"
    assert [(flow.direction.value, flow.amount_usd) for flow in flows] == [
        ("deposit", Decimal("25.00")),
        ("withdrawal", Decimal("5.00")),
    ]


def test_req_fnd_004_02_alpaca_backfill_cursor_resumes_after_page_budget() -> None:
    """TST-REQ-FND-004-02, TST-REQ-FND-004-03: a partial Alpaca read resumes its cursor."""

    registry = RepositoryRegistry()
    requests: list[httpx.Request] = []

    def full_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        activity_type = request.url.path.rsplit("/", 1)[-1]
        if activity_type != "CSD":
            return httpx.Response(200, json=[], request=request)
        token = request.url.params.get("page_token", "head")
        return httpx.Response(
            200,
            json=[
                {
                    "id": f"{token}-{index}",
                    "activity_type": "CSD",
                    "net_amount": "1.00",
                    "date": "2026-07-31",
                }
                for index in range(100)
            ],
            request=request,
        )

    source = ProviderBackedVenuePortfolioSource(
        {},
        alpaca_transport=httpx.MockTransport(full_handler),
        registry=registry,
    )
    _, status = source._alpaca_funding_activity(
        base_url="https://paper-api.alpaca.markets",
        headers={},
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    )
    metadata = source._funding_sync_metadata[
        ("development", "alpaca", ACCOUNT_REF)
    ]

    assert status == "partial"
    assert sum(request.url.path.endswith("/CSD") for request in requests) == 20
    assert metadata["backfillCursor"]
    FundingRepository(registry).set_sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        coverage_through_at=None,
        backfill_cursor=metadata["backfillCursor"],
        backfill_complete=False,
    )

    resumed_requests: list[httpx.Request] = []

    def short_handler(request: httpx.Request) -> httpx.Response:
        resumed_requests.append(request)
        return httpx.Response(200, json=[], request=request)

    resumed = ProviderBackedVenuePortfolioSource(
        {},
        alpaca_transport=httpx.MockTransport(short_handler),
        registry=registry,
    )
    _, resumed_status = resumed._alpaca_funding_activity(
        base_url="https://paper-api.alpaca.markets",
        headers={},
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref=ACCOUNT_REF,
        observed_at=NOW,
    )

    assert resumed_status == "ready"
    assert any("page_token" in request.url.params for request in resumed_requests)


def test_req_fnd_004_03_polymarket_head_sync_precedes_backfill_and_coverage() -> None:
    """TST-REQ-FND-004-03: Polymarket reaches the prior head before resuming backfill."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    repository.set_sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.POLYMARKET_US,
        account_ref="polymarket-safe",
        coverage_through_at=NOW - timedelta(days=10),
        head_transaction_id="prior-head",
        backfill_cursor="backfill-1",
        backfill_complete=False,
    )
    calls: list[str | None] = []

    def activity(activity_id: str, at: datetime) -> dict:
        return {
            "id": activity_id,
            "type": "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
            "amount": {"value": "10.00"},
            "updateTime": at.isoformat(),
            "status": "completed",
        }

    class Portfolio:
        def activities(self, params):
            cursor = params.get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {
                    "activities": [
                        activity("new-head", NOW),
                        activity("prior-head", NOW - timedelta(days=1)),
                    ],
                    "nextCursor": "head-next",
                    "eof": False,
                }
            assert cursor == "backfill-1"
            return {
                "activities": [activity("old-history", NOW - timedelta(days=20))],
                "eof": True,
            }

    source = ProviderBackedVenuePortfolioSource({}, registry=registry)
    flows, status = source._polymarket_funding_activity(
        SimpleNamespace(portfolio=Portfolio()),
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref="polymarket-safe",
        observed_at=NOW,
    )
    metadata = source._funding_sync_metadata[
        ("development", "polymarket_us", "polymarket-safe")
    ]

    assert calls == [None, "backfill-1"]
    assert status == "ready"
    assert metadata["headTransactionId"] == "new-head"
    assert metadata["backfillComplete"] is True
    service = VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource(
            [
                {
                    "status": "ready",
                    "fundingStatus": status,
                    "fundingSync": metadata,
                    "venue": "polymarket_us",
                    "provider": "openai",
                    "accountRef": "polymarket-safe",
                    "accountMode": "live",
                    "cashUsd": "100",
                    "buyingPowerUsd": "100",
                    "accountValueUsd": "100",
                    "positions": [],
                    "fills": [],
                    "cashFlows": [flow.model_dump(mode="json") for flow in flows],
                    "observedAt": NOW,
                }
            ]
        ),
    )
    service.refresh(Environment.DEVELOPMENT)
    persisted = repository.sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.POLYMARKET_US,
        account_ref="polymarket-safe",
    )
    assert persisted["head_transaction_id"] == "new-head"
    assert persisted["coverage_through_at"] == NOW


def test_req_fnd_002_03_direct_and_portfolio_account_refs_are_identical() -> None:
    """TST-REQ-FND-002-03: direct funding binds to the confirmed portfolio identity."""

    assert funding_account_ref(Venue.ALPACA, "account-123") == _account_ref(
        Venue.ALPACA,
        "account-123",
    )


def test_req_fnd_003_03_portfolio_refresh_persists_cash_flows_and_coverage_atomically() -> None:
    """TST-REQ-FND-003-03 and TST-REQ-FND-004-03: refresh stores activity and coverage."""

    registry = RepositoryRegistry()
    account = {
        "status": "ready",
        "fundingStatus": "ready",
        "venue": "alpaca",
        "provider": "openai",
        "accountRef": ACCOUNT_REF,
        "accountMode": "paper",
        "cashUsd": "100",
        "buyingPowerUsd": "100",
        "accountValueUsd": "100",
        "positions": [],
        "fills": [],
        "cashFlows": [_cash_flow().model_dump(mode="json")],
        "observedAt": NOW,
    }
    service = VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource([account]),
    )

    service.refresh(Environment.DEVELOPMENT)

    cash_flows = registry.state.rows("shared.venue_cash_flows")
    sync_state = registry.state.rows("shared.funding_sync_state")
    assert len(cash_flows) == 1
    assert sync_state[0]["coverage_through_at"] == NOW


def test_req_fnd_001_01_account_funding_failures_are_isolated_and_history_is_retained() -> None:
    """TST-REQ-FND-001-01, TST-REQ-FND-001-02: one failed account keeps prior history."""

    registry = RepositoryRegistry()
    source = StaticVenuePortfolioSource(
        [
            {
                "status": "ready",
                "fundingStatus": "ready",
                "venue": "alpaca",
                "provider": "openai",
                "accountRef": ACCOUNT_REF,
                "accountMode": "paper",
                "cashUsd": "100",
                "buyingPowerUsd": "100",
                "accountValueUsd": "100",
                "positions": [],
                "fills": [],
                "cashFlows": [_cash_flow().model_dump(mode="json")],
                "observedAt": NOW,
            },
            {
                "status": "error",
                "venue": "polymarket_us",
                "provider": "claude",
                "accountRef": "polymarket_us-safe",
                "message": "funding read failed",
                "observedAt": NOW,
            },
        ]
    )
    service = VenuePortfolioService(registry, source=source)

    service.refresh(Environment.DEVELOPMENT)
    source.accounts[0] = {**source.accounts[0], "fundingStatus": "error", "cashFlows": []}
    service.refresh(Environment.DEVELOPMENT)

    assert len(registry.state.rows("shared.venue_cash_flows")) == 1
    snapshots = registry.state.rows("shared.venue_portfolio_snapshots")
    assert any(row["status"] == "ready" for row in snapshots)
    assert any(row["status"] == "error" for row in snapshots)


def test_req_fnd_002_02_cash_flow_contract_rejects_raw_bank_fields() -> None:
    """TST-REQ-FND-002-01, TST-REQ-FND-002-02: cash-flow fields are normalized and allowlisted."""

    with pytest.raises(ValidationError):
        VenueCashFlow(
            **_cash_flow().model_dump(),
            routing_number="021000021",
        )

    row = FundingRepository(RepositoryRegistry()).upsert_cash_flow(_cash_flow())
    assert row["direction"] == "deposit"
    assert row["venue_status"] == "completed"
    serialized = str(row).lower()
    assert "routing" not in serialized
    assert "relationship" not in serialized
    assert "raw_payload" not in serialized


def test_req_fnd_003_01_shared_account_cash_flow_merges_provider_attribution_once() -> None:
    """TST-REQ-FND-003-01: shared-account observations upsert one transaction."""

    repository = FundingRepository(RepositoryRegistry())
    first = repository.upsert_cash_flow(_cash_flow())
    second = repository.upsert_cash_flow(
        _cash_flow(provider=ModelProvider.CLAUDE)
    )

    assert first["id"] == second["id"]
    assert second["model_providers"] == ["claude", "openai"]
    assert len(repository.list_cash_flows(Environment.DEVELOPMENT)) == 1


def test_req_fnd_003_02_stale_poll_cannot_regress_terminal_cash_status() -> None:
    """TST-REQ-FND-003-02: an older or stale poll cannot reopen completed cash flow."""

    repository = FundingRepository(RepositoryRegistry())
    completed = repository.upsert_cash_flow(_cash_flow())
    stale_pending = VenueCashFlow(
        **{
            **_cash_flow().model_dump(),
            "status": CashFlowStatus.PENDING,
            "observed_at": NOW + timedelta(minutes=5),
            "updated_at": NOW + timedelta(minutes=5),
        }
    )

    persisted = repository.upsert_cash_flow(stale_pending)

    assert persisted["id"] == completed["id"]
    assert persisted["venue_status"] == CashFlowStatus.COMPLETED.value


def test_req_fnd_001_04_polymarket_balance_change_contract_is_normalized() -> None:
    """TST-REQ-FND-001-04: documented account balance changes preserve venue state."""

    flow = normalize_polymarket_funding_activity(
        {
            "type": "ACCOUNT_BALANCE_CHANGE",
            "accountBalanceChange": {
                "transactionId": "pm-change-1",
                "direction": "credit",
                "amount": "75.00",
                "status": "settled",
                "time": "2026-07-30T18:00:00Z",
            },
        },
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        account_ref="polymarket-safe",
        observed_at=NOW,
    )

    assert flow is not None
    assert flow.direction == FundingDirection.DEPOSIT
    assert flow.status == CashFlowStatus.COMPLETED
    assert flow.updated_at == datetime(2026, 7, 30, 18, 0, tzinfo=UTC)


def test_req_fnd_004_01_funding_migration_retains_indefinite_history() -> None:
    """TST-REQ-FND-004-01, TST-REQ-FND-007-05: funding tables are durable."""

    plan = migration_plan()

    assert {
        "shared.venue_cash_flows",
        "shared.funding_occurrences",
        "shared.funding_sync_state",
        "shared.funding_alert_outbox",
    }.issubset(set(plan.table_names))
    ddl = "\n".join(plan.sql).lower()
    assert "delete from shared.venue_cash_flows" not in ddl
    assert "delete from shared.funding_occurrences" not in ddl
    assert "uq_funding_pending_account" in ddl


def test_req_fnd_007_02_persistent_state_uses_postgres_advisory_lock_contract() -> None:
    """TST-REQ-FND-007-02, TST-REQ-FND-008-04, TST-REQ-FND-016-01: Postgres locks execute."""

    sessions = []

    class Result:
        def scalar_one(self):
            return True

    class Session:
        def __init__(self):
            self.queries: list[tuple[str, dict | None]] = []
            self.closed = False

        def execute(self, statement, params=None):
            self.queries.append((str(statement), params))
            return Result()

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            self.closed = True

    def session_factory():
        session = Session()
        sessions.append(session)
        return session

    state = PersistentDatabaseState(session_factory)
    token = state.try_session_lock("funding-tick:development")
    assert token is not None
    assert "pg_try_advisory_lock" in sessions[0].queries[0][0]
    assert sessions[0].closed is False
    state.release_session_lock(token)
    assert "pg_advisory_unlock" in sessions[0].queries[1][0]
    assert sessions[0].closed is True

    transaction = state.begin_transaction()
    state.lock_transaction_key("funding:development:alpaca:account")
    state.commit_transaction(transaction)
    assert "pg_advisory_xact_lock" in sessions[1].queries[0][0]
    assert sessions[1].closed is True


def test_req_fnd_005_02_schedule_uses_eastern_time_month_end_and_next_business_day() -> None:
    """TST-REQ-FND-005-02: schedule calculation handles DST, month end, and holidays."""

    monthly = _schedule(cadence=FundingCadence.MONTHLY)
    due = schedule_due_at(monthly, date(2026, 2, 1))
    july_fourth = adjust_to_business_day(date(2026, 7, 4))

    assert due.date() == date(2026, 3, 2)  # Feb 28 is Saturday in 2026.
    assert due.hour == 14  # 09:00 EST in UTC.
    assert july_fourth == date(2026, 7, 6)
    assert add_business_days(date(2026, 7, 2), 4) == date(2026, 7, 9)


def test_req_fnd_005_02_deadline_preserves_eastern_wall_time_across_dst() -> None:
    """TST-REQ-FND-005-02: a 09:00 Eastern due stays 09:00 after DST changes."""

    due = datetime(2026, 3, 6, 14, 0, tzinfo=UTC)  # 09:00 EST.
    deadline = add_business_days(due, 1)

    assert isinstance(deadline, datetime)
    assert deadline == datetime(2026, 3, 9, 13, 0, tzinfo=UTC)  # 09:00 EDT.


def test_req_fnd_006_01_low_balance_gap_requires_fresh_confirmed_balance() -> None:
    """TST-REQ-FND-006-01, TST-REQ-FND-006-04: low-balance uses confirmed buying power."""

    assert calculate_low_balance_gap("500", "175") == Decimal("325")
    assert calculate_low_balance_gap("500", "550") == Decimal("0")
    with pytest.raises(ValueError, match="fresh confirmed"):
        calculate_low_balance_gap("500", "175", snapshot_fresh=False)


def test_req_fnd_006_03_low_balance_episode_rearms_only_after_recovery() -> None:
    """TST-REQ-FND-006-03: a fresh at-target snapshot rearms one low-balance episode."""

    registry = RepositoryRegistry()
    service = FundingService(registry)
    schedule = _schedule(schedule_id="low", cadence=FundingCadence.LOW_BALANCE)
    config = FundingConfig(schedules=(schedule,))

    def snapshot(snapshot_id: str, at: datetime, buying_power: str) -> None:
        registry.state.insert(
            "shared.venue_portfolio_snapshots",
            {
                "id": snapshot_id,
                "environment": "development",
                "venue": "alpaca",
                "model_provider": "openai",
                "account_ref": ACCOUNT_REF,
                "status": "ready",
                "buying_power_usd": Decimal(buying_power),
                "account_value_usd": Decimal(buying_power),
                "observed_at": at,
                "created_at": at,
            },
        )

    snapshot("below-1", NOW, "100")
    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
    )
    snapshot("below-2", NOW + timedelta(minutes=1), "90")
    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW + timedelta(minutes=1),
    )
    assert len(service.repository.list_occurrences(Environment.DEVELOPMENT)) == 1

    snapshot("rearmed", NOW + timedelta(minutes=2), "500")
    snapshot("below-3", NOW + timedelta(minutes=3), "80")
    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW + timedelta(minutes=3),
    )
    assert len(service.repository.list_occurrences(Environment.DEVELOPMENT)) == 2


def test_req_fnd_007_01_occurrence_keys_and_materialization_are_idempotent() -> None:
    """TST-REQ-FND-007-01: deterministic due occurrences persist once."""

    key_input = FundingOccurrenceKeyInput(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        model_provider=ModelProvider.OPENAI,
        schedule_id="weekly-openai",
        due_at=NOW,
        direction=FundingDirection.DEPOSIT,
        execution_mode=FundingExecutionMode.OBSERVE,
    )
    repository = FundingRepository(RepositoryRegistry())
    first = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=add_business_days(NOW, 4),
    )
    second = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=add_business_days(NOW, 4),
    )

    assert build_funding_occurrence_key(key_input) == build_funding_occurrence_key(key_input)
    assert first["id"] == second["id"]
    assert len(repository.list_occurrences(Environment.DEVELOPMENT)) == 1


def test_req_fnd_007_02_concurrent_materialization_persists_one_occurrence() -> None:
    """TST-REQ-FND-007-02: concurrent materialization returns one deterministic row."""

    from concurrent.futures import ThreadPoolExecutor

    repository = FundingRepository(RepositoryRegistry())

    def materialize(_index: int) -> str:
        return repository.materialize_occurrence(
            schedule=_schedule(),
            environment=Environment.DEVELOPMENT,
            account_ref=ACCOUNT_REF,
            config_owner="yaw",
            config_version="v1",
            due_at=NOW,
            match_deadline_at=NOW + timedelta(days=4),
        )["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(materialize, range(8)))

    assert len(set(ids)) == 1
    assert len(repository.list_occurrences(Environment.DEVELOPMENT)) == 1


def test_req_fnd_007_04_runtime_tick_materializes_fixed_schedule_when_snapshot_is_stale() -> None:
    """TST-REQ-FND-005-04, TST-REQ-FND-007-04: a new fixed schedule uses only its newest due."""

    registry = RepositoryRegistry()
    registry.state.insert(
        "shared.venue_portfolio_snapshots",
        {
            "id": "snapshot-1",
            "environment": "development",
            "venue": "alpaca",
            "model_provider": "openai",
            "account_ref": ACCOUNT_REF,
            "account_mode": "paper",
            "status": "ready",
            "cash_usd": Decimal("100"),
            "buying_power_usd": Decimal("100"),
            "account_value_usd": Decimal("100"),
            "observed_at": NOW - timedelta(hours=2),
            "created_at": NOW - timedelta(hours=2),
        },
    )
    config = FundingConfig(
        schedules=(
            _schedule(),
            _schedule(
                schedule_id="low-balance",
                cadence=FundingCadence.LOW_BALANCE,
            ),
        )
    )
    service = FundingService(registry)

    result = service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
        portfolio_freshness_seconds=120,
    )

    occurrences = service.repository.list_occurrences(Environment.DEVELOPMENT)
    assert result["status"] == "completed"
    assert [row["schedule_id"] for row in occurrences] == ["weekly-openai"]


def test_req_fnd_005_01_weekly_and_monthly_schedules_materialize_at_due_time() -> None:
    """TST-REQ-FND-005-01: enabled weekly and monthly schedules materialize once."""

    registry = RepositoryRegistry()
    registry.state.insert(
        "shared.venue_portfolio_snapshots",
        {
            "id": "snapshot-fixed",
            "environment": "development",
            "venue": "alpaca",
            "model_provider": "openai",
            "account_ref": ACCOUNT_REF,
            "status": "ready",
            "buying_power_usd": Decimal("100"),
            "account_value_usd": Decimal("100"),
            "observed_at": NOW,
            "created_at": NOW,
        },
    )
    service = FundingService(registry)
    config = FundingConfig(
        schedules=(
            _schedule(schedule_id="weekly"),
            _schedule(schedule_id="monthly", cadence=FundingCadence.MONTHLY),
        )
    )

    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
    )

    assert {row["schedule_id"] for row in service.repository.list_occurrences(Environment.DEVELOPMENT)} == {
        "weekly",
        "monthly",
    }


def test_req_fnd_005_03_runtime_tick_catches_up_each_missed_fixed_due() -> None:
    """TST-REQ-FND-005-03: downtime catch-up materializes every missed weekly due."""

    registry = RepositoryRegistry()
    registry.state.insert(
        "shared.venue_portfolio_snapshots",
        {
            "id": "snapshot-catch-up",
            "environment": "development",
            "venue": "alpaca",
            "model_provider": "openai",
            "account_ref": ACCOUNT_REF,
            "account_mode": "paper",
            "status": "ready",
            "cash_usd": Decimal("100"),
            "buying_power_usd": Decimal("100"),
            "account_value_usd": Decimal("100"),
            "observed_at": NOW,
            "created_at": NOW,
        },
    )
    service = FundingService(registry)
    config = FundingConfig(schedules=(_schedule(),))
    prior_due = datetime(2026, 7, 10, 13, 0, tzinfo=UTC)
    service.repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=prior_due,
        match_deadline_at=add_business_days(prior_due, 4),
    )

    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=config,
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
    )

    due_dates = sorted(
        row["due_at"].date()
        for row in service.repository.list_occurrences(Environment.DEVELOPMENT)
    )
    assert due_dates == [
        date(2026, 7, 10),
        date(2026, 7, 17),
        date(2026, 7, 24),
        date(2026, 7, 31),
    ]


def test_req_fnd_018_02_emergency_stop_allows_read_only_matching() -> None:
    """TST-REQ-FND-018-02: emergency controls leave reconciliation active."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=NOW + timedelta(days=5),
    )
    repository.upsert_cash_flow(_cash_flow(effective_at=NOW + timedelta(hours=1)))
    repository.set_sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        coverage_through_at=NOW + timedelta(days=6),
    )
    service = FundingService(registry)

    service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=FundingConfig(emergency_stop=True, schedules=(_schedule(),)),
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=True,
        now=NOW + timedelta(days=6),
    )

    assert repository.occurrence(occurrence["id"])["status"] == "matched"


def test_req_fnd_008_01_reconciliation_matches_one_cash_flow_and_delays_missing() -> None:
    """TST-REQ-FND-008-01, TST-REQ-FND-008-03: matching is one-to-one and coverage-gated."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=NOW + timedelta(days=6),
    )
    flow = repository.upsert_cash_flow(_cash_flow(effective_at=NOW + timedelta(hours=1)))
    matched = repository.reconcile_occurrence(
        occurrence["id"],
        coverage_through_at=NOW + timedelta(days=7),
        now=NOW + timedelta(days=7),
    )

    assert matched["status"] == FundingOccurrenceStatus.MATCHED.value
    assert matched["matched_cash_flow_id"] == flow["id"]


def test_req_fnd_008_02_multiple_matching_candidates_remain_unmatched() -> None:
    """TST-REQ-FND-008-02: multiple eligible cash flows do not produce an ambiguous match."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=NOW + timedelta(days=5),
    )
    for transaction_id in ("cash-a", "cash-b"):
        repository.upsert_cash_flow(
            _cash_flow(
                transaction_id=transaction_id,
                effective_at=NOW + timedelta(hours=1),
            )
        )

    unresolved = repository.reconcile_occurrence(
        occurrence["id"],
        coverage_through_at=NOW + timedelta(days=6),
        now=NOW + timedelta(days=1),
    )

    assert unresolved["status"] == FundingOccurrenceStatus.EXPECTED.value
    assert unresolved["matched_cash_flow_id"] is None


def test_req_fnd_008_04_concurrent_reconciliation_reuses_no_cash_flow() -> None:
    """TST-REQ-FND-008-04: one cash flow can match only one racing occurrence."""

    from concurrent.futures import ThreadPoolExecutor

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrences = [
        repository.materialize_occurrence(
            schedule=_schedule(schedule_id=f"weekly-{index}"),
            environment=Environment.DEVELOPMENT,
            account_ref=ACCOUNT_REF,
            config_owner="yaw",
            config_version="v1",
            due_at=NOW,
            match_deadline_at=NOW + timedelta(days=5),
        )
        for index in range(2)
    ]
    flow = repository.upsert_cash_flow(
        _cash_flow(transaction_id="single", effective_at=NOW + timedelta(hours=1))
    )

    def reconcile(occurrence: dict) -> dict:
        return repository.reconcile_occurrence(
            occurrence["id"],
            coverage_through_at=NOW + timedelta(days=6),
            now=NOW + timedelta(days=1),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile, occurrences))

    assert sum(row["status"] == FundingOccurrenceStatus.MATCHED.value for row in results) == 1
    assert sum(row.get("matched_cash_flow_id") == flow["id"] for row in results) == 1


def test_req_fnd_009_01_failure_and_recovery_alerts_are_logically_unique() -> None:
    """TST-REQ-FND-009-01, TST-REQ-FND-009-02, TST-REQ-FND-009-03: alerts deduplicate."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW - timedelta(days=10),
        match_deadline_at=NOW - timedelta(days=4),
    )
    missing = repository.reconcile_occurrence(
        occurrence["id"], coverage_through_at=NOW, now=NOW
    )
    repository.reconcile_occurrence(occurrence["id"], coverage_through_at=NOW, now=NOW)
    repository.upsert_cash_flow(
        _cash_flow(effective_at=NOW - timedelta(days=8))
    )
    recovered = repository.reconcile_occurrence(
        occurrence["id"], coverage_through_at=NOW, now=NOW
    )
    outbox = registry.state.rows("shared.funding_alert_outbox")

    assert missing["status"] == FundingOccurrenceStatus.MISSING.value
    assert recovered["status"] == FundingOccurrenceStatus.MATCHED.value
    assert [row["transition_type"] for row in outbox] == ["failure", "recovery"]


def test_req_fnd_009_04_transition_rolls_back_when_outbox_persistence_fails() -> None:
    """TST-REQ-FND-009-04: state and alert outbox commit as one transaction."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW - timedelta(days=10),
        match_deadline_at=NOW - timedelta(days=4),
    )
    registry.state.fail_on_tables.add("shared.funding_alert_outbox")

    with pytest.raises(PersistenceUnavailableError):
        repository.reconcile_occurrence(
            occurrence["id"],
            coverage_through_at=NOW,
            now=NOW,
        )

    assert repository.occurrence(occurrence["id"])["status"] == "expected"
    assert repository.alerts(Environment.DEVELOPMENT) == []


def test_req_fnd_009_04_alert_delivery_retries_then_marks_sent() -> None:
    """TST-REQ-FND-009-04: SES delivery uses bounded outbox retry state."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW - timedelta(days=10),
        match_deadline_at=NOW - timedelta(days=4),
    )
    repository.reconcile_occurrence(
        occurrence["id"],
        coverage_through_at=NOW,
        now=NOW,
    )
    adapter = InMemorySesEmailAdapter(fail_delivery=True)
    service = FundingService(
        registry,
        notification_adapter=adapter,
        notification_recipients=("operator@example.com",),
    )

    assert service.deliver_alerts(environment=Environment.DEVELOPMENT, now=NOW) == 0
    first = repository.alerts(Environment.DEVELOPMENT)[0]
    assert first["delivery_status"] == "failed"
    assert first["attempt_count"] == 1
    assert first["next_attempt_at"] == NOW + timedelta(minutes=1)
    assert first["provider_message_id"] is None
    assert first["last_error"] == "SES delivery failed"
    adapter.fail_delivery = False
    assert service.deliver_alerts(
        environment=Environment.DEVELOPMENT,
        now=first["next_attempt_at"],
    ) == 1
    sent = repository.alerts(Environment.DEVELOPMENT)[0]
    assert sent["delivery_status"] == "sent"
    assert sent["attempt_count"] == 2
    assert sent["provider_message_id"] == "ses-message-1"
    heartbeat = service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=FundingConfig(),
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW + timedelta(hours=1),
    )
    assert heartbeat["fundingAlertCounts"]["sent"] == 1


def test_req_fnd_009_04_alert_delivery_caps_attempts_and_backoff() -> None:
    """TST-REQ-FND-009-04: alert attempts stop at five with bounded exponential backoff."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW - timedelta(days=10),
        match_deadline_at=NOW - timedelta(days=4),
    )
    repository.reconcile_occurrence(
        occurrence["id"], coverage_through_at=NOW, now=NOW
    )
    adapter = InMemorySesEmailAdapter(fail_delivery=True)
    service = FundingService(
        registry,
        notification_adapter=adapter,
        notification_recipients=("operator@example.com",),
    )
    attempt_at = NOW
    for expected_attempt in range(1, 6):
        service.deliver_alerts(
            environment=Environment.DEVELOPMENT,
            now=attempt_at,
        )
        alert = repository.alerts(Environment.DEVELOPMENT)[0]
        assert alert["attempt_count"] == expected_attempt
        assert alert["next_attempt_at"] <= attempt_at + timedelta(minutes=60)
        attempt_at = alert["next_attempt_at"]
    service.deliver_alerts(
        environment=Environment.DEVELOPMENT,
        now=attempt_at + timedelta(hours=2),
    )

    assert len(adapter.attempts) == 5
    assert repository.alerts(Environment.DEVELOPMENT)[0]["attempt_count"] == 5


def test_req_fnd_009_02_claimed_alert_is_not_resent_after_result_persistence_failure() -> None:
    """TST-REQ-FND-009-02: a send-success persistence failure cannot resend the alert."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW - timedelta(days=10),
        match_deadline_at=NOW - timedelta(days=4),
    )
    repository.reconcile_occurrence(
        occurrence["id"],
        coverage_through_at=NOW,
        now=NOW,
    )

    class PersistFailingAdapter(InMemorySesEmailAdapter):
        def send_alert(self, alert):
            result = super().send_alert(alert)
            registry.state.fail_on_tables.add("shared.funding_alert_outbox")
            return result

    adapter = PersistFailingAdapter()
    service = FundingService(
        registry,
        notification_adapter=adapter,
        notification_recipients=("operator@example.com",),
    )

    with pytest.raises(PersistenceUnavailableError):
        service.deliver_alerts(environment=Environment.DEVELOPMENT, now=NOW)
    registry.state.fail_on_tables.clear()
    assert repository.alerts(Environment.DEVELOPMENT)[0]["delivery_status"] == "sending"
    assert service.deliver_alerts(
        environment=Environment.DEVELOPMENT,
        now=NOW + timedelta(hours=1),
    ) == 0
    assert adapter.sent_count == 1


def test_req_fnd_008_03_partial_refresh_does_not_advance_missing_coverage() -> None:
    """TST-REQ-FND-008-03: incomplete pagination cannot create a false missing alert."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    repository.set_sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        coverage_through_at=NOW - timedelta(days=20),
    )
    service = VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource(
            [
                {
                    "status": "ready",
                    "fundingStatus": "partial",
                    "venue": "alpaca",
                    "provider": "openai",
                    "accountRef": ACCOUNT_REF,
                    "accountMode": "paper",
                    "cashUsd": "100",
                    "buyingPowerUsd": "100",
                    "accountValueUsd": "100",
                    "positions": [],
                    "fills": [],
                    "cashFlows": [],
                    "observedAt": NOW,
                }
            ]
        ),
    )

    service.refresh(Environment.DEVELOPMENT)

    assert repository.sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
    )["coverage_through_at"] == NOW - timedelta(days=20)


def test_req_fnd_010_01_authenticated_history_api_is_sanitized() -> None:
    """TST-REQ-FND-010-01, TST-REQ-FND-010-02, TST-REQ-FND-010-04: API auth is reused."""

    app = create_app(
        AppSettings(
            environment=Environment.DEVELOPMENT,
            allowed_usernames=("yaw",),
            signing_secret="test-secret",
        )
    )
    app.state.services.funding.repository.upsert_cash_flow(_cash_flow())
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)

    assert client.get("/api/funding/history").status_code == 401
    response = client.get(
        "/api/funding/history?limit=25",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )

    assert response.status_code == 200
    assert client.get(
        "/api/funding",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    ).status_code == 200
    body = response.json()
    assert body["cashFlows"][0]["accountLabel"]
    serialized = str(body).lower()
    assert "account_ref" not in serialized
    assert "relationship_id" not in serialized
    assert "request_fingerprint" not in serialized


def test_req_fnd_010_03_history_uses_independent_stable_cursors() -> None:
    """TST-REQ-FND-010-03: cash-flow pages are descending and non-overlapping."""

    registry = RepositoryRegistry()
    repository = FundingRepository(registry)
    for index in range(3):
        repository.upsert_cash_flow(
            _cash_flow(
                transaction_id=f"cash-{index}",
                effective_at=NOW + timedelta(minutes=index),
            )
        )
    service = FundingService(registry)
    first = service.history_payload(
        Environment.DEVELOPMENT,
        start_at=NOW - timedelta(minutes=1),
        end_at=NOW + timedelta(minutes=4),
        limit=2,
    )
    second = service.history_payload(
        Environment.DEVELOPMENT,
        start_at=NOW - timedelta(minutes=1),
        end_at=NOW + timedelta(minutes=4),
        limit=2,
        cash_cursor=first["nextCashCursor"],
    )

    assert len(first["cashFlows"]) == 2
    assert len(second["cashFlows"]) == 1
    assert {row["id"] for row in first["cashFlows"]}.isdisjoint(
        {row["id"] for row in second["cashFlows"]}
    )
    assert second["nextCashCursor"] is None


def test_req_fnd_004_04_retained_history_is_queryable_in_an_older_interval() -> None:
    """TST-REQ-FND-004-04: retained cash-flow history remains queryable for one year."""

    registry = RepositoryRegistry()
    old_at = NOW - timedelta(days=300)
    FundingRepository(registry).upsert_cash_flow(
        _cash_flow(transaction_id="old-cash", effective_at=old_at)
    )

    payload = FundingService(registry).history_payload(
        Environment.DEVELOPMENT,
        start_at=old_at - timedelta(days=1),
        end_at=old_at + timedelta(days=1),
    )

    assert [row["activityType"] for row in payload["cashFlows"]] == ["CSD"]


def test_req_fnd_010_05_history_interval_returns_cash_adjusted_performance() -> None:
    """TST-REQ-FND-010-05: history returns interval totals and adjusted trading P&L."""

    registry = RepositoryRegistry()
    for snapshot_id, observed_at, value in (
        ("start", NOW, "1000"),
        ("end", NOW + timedelta(days=4), "1300"),
    ):
        registry.state.insert(
            "shared.venue_portfolio_snapshots",
            {
                "id": snapshot_id,
                "environment": "development",
                "venue": "alpaca",
                "model_provider": "openai",
                "account_ref": ACCOUNT_REF,
                "status": "ready",
                "account_value_usd": Decimal(value),
                "observed_at": observed_at,
                "created_at": observed_at,
            },
        )
    repository = FundingRepository(registry)
    repository.upsert_cash_flow(
        _cash_flow(amount="200", effective_at=NOW + timedelta(days=1))
    )

    payload = FundingService(registry).history_payload(
        Environment.DEVELOPMENT,
        start_at=NOW,
        end_at=NOW + timedelta(days=4),
    )

    assert payload["performance"]["tradingPnlExcludingCashFlowsUsd"] == "100.00000000"
    assert payload["performance"]["completedDepositsUsd"] == "200.00000000"


def test_req_fnd_011_02_stale_boundaries_exclude_cash_flows_from_performance() -> None:
    """TST-REQ-FND-012-03: stale boundaries return unavailable."""

    registry = RepositoryRegistry()
    registry.state.insert(
        "shared.venue_portfolio_snapshots",
        {
            "id": "stale-start",
            "environment": "development",
            "venue": "alpaca",
            "model_provider": "openai",
            "account_ref": ACCOUNT_REF,
            "status": "ready",
            "account_value_usd": Decimal("1000"),
            "observed_at": NOW - timedelta(minutes=10),
            "created_at": NOW - timedelta(minutes=10),
        },
    )
    FundingRepository(registry).upsert_cash_flow(
        _cash_flow(effective_at=NOW + timedelta(hours=1))
    )

    payload = FundingService(registry).history_payload(
        Environment.DEVELOPMENT,
        start_at=NOW,
        end_at=NOW + timedelta(days=1),
    )

    assert payload["performance"]["tradingPnlExcludingCashFlowsUsd"] is None
    assert payload["performance"]["completedDepositsUsd"] == "0E-8"
    assert payload["performance"]["accounts"][0]["status"] == "unavailable"


def test_req_fnd_011_02_noncompleted_cash_statuses_do_not_change_performance() -> None:
    """TST-REQ-FND-011-02: noncompleted venue cash states are excluded from P&L."""

    registry = RepositoryRegistry()
    for snapshot_id, observed_at, value in (
        ("start-status", NOW, "1000"),
        ("end-status", NOW + timedelta(days=1), "1100"),
    ):
        registry.state.insert(
            "shared.venue_portfolio_snapshots",
            {
                "id": snapshot_id,
                "environment": "development",
                "venue": "alpaca",
                "model_provider": "openai",
                "account_ref": ACCOUNT_REF,
                "status": "ready",
                "account_value_usd": Decimal(value),
                "observed_at": observed_at,
                "created_at": observed_at,
            },
        )
    repository = FundingRepository(registry)
    for index, status in enumerate(
        (
            CashFlowStatus.PENDING,
            CashFlowStatus.UNKNOWN,
            CashFlowStatus.REJECTED,
            CashFlowStatus.RETURNED,
            CashFlowStatus.FAILED,
            CashFlowStatus.CANCELED,
        )
    ):
        repository.upsert_cash_flow(
            VenueCashFlow(
                **{
                    **_cash_flow(
                        transaction_id=f"status-{index}",
                        effective_at=NOW + timedelta(hours=12),
                    ).model_dump(),
                    "status": status,
                }
            )
        )

    payload = FundingService(registry).history_payload(
        Environment.DEVELOPMENT,
        start_at=NOW,
        end_at=NOW + timedelta(days=1),
    )

    assert payload["performance"]["completedDepositsUsd"] == "0E-8"
    assert payload["performance"]["tradingPnlExcludingCashFlowsUsd"] == "100.00000000"


def test_req_fnd_011_01_adjusted_pnl_excludes_completed_external_cash_flows() -> None:
    """TST-REQ-FND-011-01: external cash flows are excluded from trading P&L."""

    result = adjusted_trading_performance(
        beginning_value="1000",
        ending_value="1200",
        cash_flows=[
            (NOW + timedelta(days=1), FundingDirection.DEPOSIT, Decimal("300")),
            (NOW + timedelta(days=2), FundingDirection.WITHDRAWAL, Decimal("50")),
        ],
        period_start=NOW,
        period_end=NOW + timedelta(days=4),
    )

    assert result.adjusted_pnl_usd == Decimal("-50.00000000")


def test_req_fnd_012_01_modified_dietz_uses_documented_numeric_oracle() -> None:
    """TST-REQ-FND-012-01: Modified Dietz result is deterministic."""

    result = adjusted_trading_performance(
        beginning_value="1000",
        ending_value="1300",
        cash_flows=[
            (NOW + timedelta(days=1), FundingDirection.DEPOSIT, Decimal("200")),
            (NOW + timedelta(days=3), FundingDirection.WITHDRAWAL, Decimal("40")),
        ],
        period_start=NOW,
        period_end=NOW + timedelta(days=4),
    )

    assert result.adjusted_pnl_usd == Decimal("140.00000000")
    assert result.weighted_denominator_usd == Decimal("1140.00000000")
    assert result.modified_dietz_return == Decimal("0.12280702")


def test_req_fnd_012_02_non_positive_modified_dietz_denominator_is_unavailable() -> None:
    """TST-REQ-FND-012-02: a non-positive denominator suppresses percentage return."""

    result = adjusted_trading_performance(
        beginning_value="0",
        ending_value="10",
        cash_flows=[],
        period_start=NOW,
        period_end=NOW + timedelta(days=1),
    )

    assert result.modified_dietz_return is None
    assert result.unavailable_reason == "non_positive_modified_dietz_denominator"


def test_req_fnd_019_02_funding_config_is_complete_versioned_and_safe() -> None:
    """TST-REQ-FND-014-01, TST-REQ-FND-019-02: every bootstrap funding object is safe."""

    defaults = default_config_payload()["funding"]
    for _environment in (
        Environment.LOCAL,
        Environment.DEVELOPMENT,
        Environment.PRODUCTION,
    ):
        parsed = FundingConfig.model_validate(defaults)
        assert not parsed.direct_transfers_enabled
        assert parsed.max_transfer_usd == Decimal("0.00")
        assert parsed.max_monthly_transfer_usd == Decimal("0.00")
    with pytest.raises(ValidationError):
        FundingConfig.model_validate({**defaults, "timezone": "UTC"})


def test_req_fnd_019_01_complete_funding_patch_is_versioned_and_audited() -> None:
    """TST-REQ-FND-019-01, TST-REQ-FND-019-02: one complete funding patch is atomic."""

    app = create_app(
        AppSettings(
            environment=Environment.DEVELOPMENT,
            allowed_usernames=("yaw",),
            signing_secret="test-secret",
        )
    )
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://localhost:3100",
        "X-CSRF-Token": "local-dev-csrf-token",
    }
    current = client.get("/api/config/current", headers=headers).json()
    funding = dict(current["settings"]["funding"])
    funding["emergency_stop"] = True

    response = client.post(
        "/api/config",
        headers=headers,
        json={
            "environment": "development",
            "expected_version": None if current["version"] == "bootstrap" else current["version"],
            "patches": [{"op": "replace", "path": "funding", "value": funding}],
        },
    )

    assert response.status_code == 200
    audit = app.state.services.registry.state.rows("shared.audit_events")[-1]
    assert audit["actor"] == "yaw"
    assert audit["environment"] == "development"
    assert audit["metadata"]["path"] == "funding"


def test_req_fnd_020_02_polymarket_direct_mode_is_rejected_and_observe_is_allowed() -> None:
    """TST-REQ-FND-020-01, TST-REQ-FND-020-02: Polymarket remains observe-only."""

    observe = _schedule(venue=Venue.POLYMARKET_US)
    assert observe.execution_mode == FundingExecutionMode.OBSERVE
    with pytest.raises(ValidationError, match="observe-only"):
        _schedule(
            venue=Venue.POLYMARKET_US,
            mode=FundingExecutionMode.DIRECT,
        )


def test_req_fnd_007_03_portfolio_refresh_is_the_single_funding_hook(monkeypatch) -> None:
    """TST-REQ-FND-007-03: funding runs after refresh and outside the trading hook."""

    funding_calls: list[dict] = []
    events: list[str] = []

    class Runtime:
        def refresh_venue_portfolio(self, environment):
            del environment
            events.append("refresh")
            return {"status": "ready"}

        def record_worker_heartbeat(self, **kwargs):
            return kwargs

    class Config:
        def config_for_next_loop(self, environment, username=None):
            del environment, username
            return SimpleNamespace(
                snapshot=SimpleNamespace(
                    payload=default_config_payload(),
                    version="v1",
                )
            )

    class Funding:
        def run_tick(self, **kwargs):
            events.append("funding")
            funding_calls.append(kwargs)
            return {"status": "completed"}

    async def stop_after_first_tick(_delay):
        raise StopAsyncIteration

    services = SimpleNamespace(
        runtime_status=Runtime(),
        config=Config(),
        funding=Funding(),
        kill_switch=SimpleNamespace(
            state=lambda environment: SimpleNamespace(active=False)
        ),
    )
    monkeypatch.setattr("app.main.asyncio.sleep", stop_after_first_tick)

    with pytest.raises(StopAsyncIteration):
        asyncio.run(
            _portfolio_refresh_loop(
                services=services,
                settings=AppSettings(allowed_usernames=("yaw",)),
                environment=Environment.DEVELOPMENT,
                interval_seconds=60,
            )
        )

    assert events == ["refresh", "funding"]
    assert len(funding_calls) == 1
    assert funding_calls[0]["config_owner"] == "yaw"
    assert funding_calls[0]["portfolio_freshness_seconds"] == 120


def test_req_fnd_007_03_tick_lock_skips_and_releases_after_success_or_failure(monkeypatch) -> None:
    """TST-REQ-FND-007-03: the session lock skips overlap and always releases."""

    registry = RepositoryRegistry()
    service = FundingService(registry)
    lock_key = "funding-tick:development"
    held = registry.state.try_session_lock(lock_key)
    assert held is not None
    assert service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=FundingConfig(),
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
    ) == {"status": "skipped", "reason": "funding_tick_already_running"}
    registry.state.release_session_lock(held)

    assert service.run_tick(
        environment=Environment.DEVELOPMENT,
        config=FundingConfig(),
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW,
    )["status"] == "completed"
    after_success = registry.state.try_session_lock(lock_key)
    assert after_success is not None
    registry.state.release_session_lock(after_success)

    monkeypatch.setattr(
        service.repository,
        "list_occurrences",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tick failed")),
    )
    with pytest.raises(RuntimeError, match="tick failed"):
        service.run_tick(
            environment=Environment.DEVELOPMENT,
            config=FundingConfig(),
            config_owner="yaw",
            config_version="v1",
            kill_switch_active=False,
            now=NOW,
        )
    after_failure = registry.state.try_session_lock(lock_key)
    assert after_failure is not None
    registry.state.release_session_lock(after_failure)
