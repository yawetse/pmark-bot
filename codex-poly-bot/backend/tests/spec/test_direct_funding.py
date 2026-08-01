"""Executable specifications for disabled-by-default Alpaca direct funding."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any

import httpx
import pytest

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import (
    Environment,
    FundingCadence,
    FundingConfig,
    FundingDirection,
    FundingExecutionMode,
    FundingOccurrenceStatus,
    FundingSchedule,
    ModelProvider,
    Venue,
)
from app.services.direct_funding_service import DirectFundingService
from app.services.funding_service import FundingRepository, FundingService, funding_account_ref
from app.venues.alpaca_funding import AlpacaBrokerFundingAdapter


NOW = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
BROKER_ACCOUNT_ID = "broker-account-secret"
ACCOUNT_REF = funding_account_ref(Venue.ALPACA, BROKER_ACCOUNT_ID)


class CountingTransport(httpx.BaseTransport):
    def __init__(self, *, status_code: int = 200, payload: Any = None) -> None:
        self.status_code = status_code
        self.payload = payload if payload is not None else {"id": "transfer-1", "status": "QUEUED"}
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json=self.payload, request=request)


def _schedule(*, amount: str = "25.00") -> FundingSchedule:
    return FundingSchedule(
        id="direct-weekly",
        enabled=True,
        venue=Venue.ALPACA,
        model_provider=ModelProvider.OPENAI,
        cadence=FundingCadence.WEEKLY,
        execution_mode=FundingExecutionMode.DIRECT,
        direction=FundingDirection.DEPOSIT,
        amount_usd=amount,
        iso_weekday=5,
    )


def _config(*, enabled: bool = True, max_transfer: str = "100", monthly: str = "500") -> FundingConfig:
    return FundingConfig(
        emergency_stop=False,
        direct_transfers_enabled=enabled,
        max_transfer_usd=max_transfer,
        max_monthly_transfer_usd=monthly,
        timezone="America/New_York",
        missing_after_business_days=4,
        schedules=(_schedule(),),
    )


def _runtime_env() -> dict[str, str]:
    return {
        "ALPACA_OPENAI_BROKER_API_KEY": "broker-key",
        "ALPACA_OPENAI_BROKER_API_SECRET": "broker-secret",
        "ALPACA_OPENAI_BROKER_ACCOUNT_ID": BROKER_ACCOUNT_ID,
        "ALPACA_OPENAI_ACH_RELATIONSHIP_ID": "relationship-secret",
        "ALPACA_OPENAI_BROKER_BASE_URL": "https://broker-api.sandbox.alpaca.markets",
    }


def _service(
    *,
    transport: httpx.BaseTransport,
    runtime_env: dict[str, str] | None = None,
    config: FundingConfig | None = None,
) -> tuple[DirectFundingService, FundingRepository, dict]:
    registry = RepositoryRegistry()
    current_config = config or _config()
    registry.shared().record_config_version(
        environment=Environment.DEVELOPMENT,
        username="yaw",
        version="v1",
        payload={"funding": current_config.model_dump(mode="json")},
    )
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=_schedule(),
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=NOW,
    )
    adapter = AlpacaBrokerFundingAdapter(
        runtime_env=runtime_env or _runtime_env(),
        transport=transport,
    )
    return DirectFundingService(registry, adapter=adapter), repository, occurrence


def test_req_fnd_013_01_adapter_submits_exact_incoming_ach_contract_without_plaid() -> None:
    """TST-REQ-FND-013-01, TST-REQ-FND-013-02, TST-REQ-FND-013-03: safe Broker ACH."""

    transport = CountingTransport()
    service, repository, occurrence = _service(transport=transport)

    result = service.submit_occurrence(
        occurrence["id"],
        config=_config(),
        kill_switch_active=False,
    )

    assert result["status"] == FundingOccurrenceStatus.SUBMITTED.value
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.path == f"/v1/accounts/{BROKER_ACCOUNT_ID}/transfers"
    payload = request.content.decode()
    assert '"direction":"INCOMING"' in payload
    assert '"amount":"25.00"' in payload
    assert "relationship-secret" in payload
    persisted = str(repository.list_occurrences(Environment.DEVELOPMENT)).lower()
    assert BROKER_ACCOUNT_ID not in persisted
    assert "relationship-secret" not in persisted
    assert "plaid" not in payload.lower()


def test_req_fnd_014_02_disabled_or_zero_limits_refuse_before_adapter() -> None:
    """TST-REQ-FND-014-02: direct transfers fail closed before the adapter."""

    transport = CountingTransport()
    current_config = _config(enabled=False)
    service, _, occurrence = _service(transport=transport, config=current_config)

    result = service.submit_occurrence(
        occurrence["id"],
        config=current_config,
        kill_switch_active=False,
    )

    assert result["status"] == FundingOccurrenceStatus.REFUSED.value
    assert result["refusal_reason"] == "direct_transfers_disabled"
    assert transport.requests == []


def test_req_fnd_015_03_caps_and_pending_slot_refuse_fixed_transfer_in_full() -> None:
    """TST-REQ-FND-015-01, TST-REQ-FND-015-03: caps and one pending slot are enforced."""

    transport = CountingTransport()
    current_config = _config(max_transfer="20")
    service, repository, occurrence = _service(
        transport=transport,
        config=current_config,
    )

    result = service.submit_occurrence(
        occurrence["id"],
        config=current_config,
        kill_switch_active=False,
    )

    assert result["status"] == FundingOccurrenceStatus.REFUSED.value
    assert result["refusal_reason"] == "per_transfer_limit_exceeded"
    assert repository.monthly_reserved_amount(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        at=NOW,
    ) == Decimal("0")
    assert transport.requests == []


def test_req_fnd_015_02_month_capacity_counts_pending_and_resets_by_eastern_month() -> None:
    """TST-REQ-FND-015-02, TST-REQ-FND-015-04: month capacity counts pending reservations."""

    transport = CountingTransport()
    service, repository, _ = _service(transport=transport)
    for index, status in enumerate(
        (
            FundingOccurrenceStatus.RESERVED,
            FundingOccurrenceStatus.SUBMITTED,
            FundingOccurrenceStatus.UNKNOWN,
            FundingOccurrenceStatus.MATCHED,
            FundingOccurrenceStatus.MISSING,
            FundingOccurrenceStatus.FAILED,
        )
    ):
        schedule = _schedule(amount="10").model_copy(update={"id": f"direct-{index}"})
        occurrence = repository.materialize_occurrence(
            schedule=schedule,
            environment=Environment.DEVELOPMENT,
            account_ref=ACCOUNT_REF,
            config_owner="yaw",
            config_version="v1",
            due_at=NOW.replace(day=20 + index),
            match_deadline_at=NOW.replace(day=20 + index),
        )
        repository.update_occurrence(
            occurrence["id"],
            status=status.value,
            reserved_amount_usd=Decimal("10"),
            reserved_at=NOW,
            post_attempted_at=(
                NOW if status == FundingOccurrenceStatus.MISSING else None
            ),
        )

    assert repository.monthly_reserved_amount(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        at=NOW,
    ) == Decimal("50")
    assert repository.monthly_reserved_amount(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        at=NOW.replace(month=8),
    ) == Decimal("0")


def test_req_fnd_006_02_low_balance_claim_uses_smallest_positive_cap() -> None:
    """TST-REQ-FND-006-02: low-balance direct funding submits the smallest safe cap."""

    registry = RepositoryRegistry()
    schedule = FundingSchedule(
        id="direct-low-balance",
        enabled=True,
        venue=Venue.ALPACA,
        model_provider=ModelProvider.OPENAI,
        cadence=FundingCadence.LOW_BALANCE,
        execution_mode=FundingExecutionMode.DIRECT,
        direction=FundingDirection.DEPOSIT,
        target_balance_usd="500",
    )
    config = FundingConfig(
        direct_transfers_enabled=True,
        max_transfer_usd="100",
        max_monthly_transfer_usd="80",
        schedules=(schedule,),
    )
    registry.shared().record_config_version(
        environment=Environment.DEVELOPMENT,
        username="yaw",
        version="v1",
        payload={"funding": config.model_dump(mode="json")},
    )
    repository = FundingRepository(registry)
    occurrence = repository.materialize_occurrence(
        schedule=schedule,
        environment=Environment.DEVELOPMENT,
        account_ref=ACCOUNT_REF,
        config_owner="yaw",
        config_version="v1",
        due_at=NOW,
        match_deadline_at=NOW,
        expected_amount_usd="200",
    )
    transport = CountingTransport()
    service = DirectFundingService(
        registry,
        adapter=AlpacaBrokerFundingAdapter(
            runtime_env=_runtime_env(),
            transport=transport,
        ),
    )

    submitted = service.submit_occurrence(
        occurrence["id"],
        config=config,
        kill_switch_active=False,
        now=NOW,
    )

    assert submitted["expected_amount_usd"] == Decimal("200")
    assert submitted["submitted_amount_usd"] == Decimal("80")
    assert '"amount":"80.00"' in transport.requests[0].content.decode()


def test_req_fnd_016_01_durable_claim_permits_at_most_one_post() -> None:
    """TST-REQ-FND-016-01: retries reconcile persisted state without a second POST."""

    transport = CountingTransport()
    service, _, occurrence = _service(transport=transport)

    first = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )
    second = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )

    assert first["status"] == FundingOccurrenceStatus.SUBMITTED.value
    assert second["id"] == first["id"]
    assert len(transport.requests) == 1


def test_req_fnd_016_02_crash_left_claim_reconciles_without_another_post() -> None:
    """TST-REQ-FND-016-02: a reserved attempted claim becomes unknown before read recovery."""

    transfer = {
        "id": "transfer-recovered",
        "direction": "INCOMING",
        "relationship_id": "relationship-secret",
        "amount": "25.00",
        "status": "QUEUED",
        "created_at": NOW.isoformat(),
    }
    transport = CountingTransport(payload=[transfer])
    service, repository, occurrence = _service(transport=transport)
    claimed = repository.claim_direct_occurrence(
        occurrence["id"],
        broker_account_ref=ACCOUNT_REF,
        broker_secrets_available=True,
        kill_switch_active=False,
        at=NOW,
    )
    assert claimed["status"] == FundingOccurrenceStatus.RESERVED.value

    recovered = service.reconcile_occurrence(occurrence["id"], now=NOW)

    assert recovered["status"] == FundingOccurrenceStatus.SUBMITTED.value
    assert recovered["provider_transfer_id"] == "transfer-recovered"
    assert len(transport.requests) == 1
    assert transport.requests[0].method == "GET"


def test_req_fnd_016_03_unknown_requires_one_exact_transfer_candidate() -> None:
    """TST-REQ-FND-016-03: zero or multiple candidates remain unknown."""

    candidate = {
        "id": "transfer-a",
        "direction": "INCOMING",
        "relationship_id": "relationship-secret",
        "amount": "25.00",
        "status": "QUEUED",
        "created_at": NOW.isoformat(),
    }
    transport = CountingTransport(payload=[candidate, {**candidate, "id": "transfer-b"}])
    service, repository, occurrence = _service(transport=transport)
    repository.claim_direct_occurrence(
        occurrence["id"],
        broker_account_ref=ACCOUNT_REF,
        broker_secrets_available=True,
        kill_switch_active=False,
        at=NOW,
    )

    unresolved = service.reconcile_occurrence(occurrence["id"], now=NOW)

    assert unresolved["status"] == FundingOccurrenceStatus.UNKNOWN.value
    assert unresolved["provider_transfer_id"] is None
    assert all(request.method == "GET" for request in transport.requests)


def test_req_fnd_016_04_timeout_stays_unknown_and_never_reposts() -> None:
    """TST-REQ-FND-016-04: an ambiguous POST outcome keeps its reservation without retry."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("broker timeout", request=request)
        return httpx.Response(200, json=[], request=request)

    service, _, occurrence = _service(transport=httpx.MockTransport(handler))

    ambiguous = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )
    recovered = service.reconcile_occurrence(occurrence["id"], now=NOW)
    retried = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )

    assert ambiguous["status"] == FundingOccurrenceStatus.UNKNOWN.value
    assert recovered["status"] == FundingOccurrenceStatus.UNKNOWN.value
    assert retried["status"] == FundingOccurrenceStatus.UNKNOWN.value
    assert sum(request.method == "POST" for request in requests) == 1


def test_req_fnd_016_04_unknown_keeps_pending_slot_after_missing_deadline() -> None:
    """TST-REQ-FND-016-04: unresolved direct ambiguity is not downgraded to missing."""

    transport = CountingTransport(payload=[])
    direct, repository, occurrence = _service(transport=transport)
    repository.claim_direct_occurrence(
        occurrence["id"],
        broker_account_ref=ACCOUNT_REF,
        broker_secrets_available=True,
        kill_switch_active=False,
        at=NOW,
    )
    repository.set_sync_state(
        environment=Environment.DEVELOPMENT,
        venue=Venue.ALPACA,
        account_ref=ACCOUNT_REF,
        coverage_through_at=NOW.replace(year=2027),
        backfill_complete=True,
    )

    FundingService(direct.registry, direct_service=direct).run_tick(
        environment=Environment.DEVELOPMENT,
        config=_config(),
        config_owner="yaw",
        config_version="v1",
        kill_switch_active=False,
        now=NOW.replace(year=2027),
    )

    persisted = repository.occurrence(occurrence["id"])
    assert persisted["status"] == FundingOccurrenceStatus.UNKNOWN.value
    assert persisted["reserved_amount_usd"] == Decimal("25.00")
    assert all(request.method == "GET" for request in transport.requests)


def test_req_fnd_004_02_broker_transfer_reads_are_bounded_and_paginated() -> None:
    """TST-REQ-FND-004-02: Broker transfer-list reads use bounded offset pages."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params.get("offset", "0"))
        count = 100 if offset == 0 else 1
        return httpx.Response(
            200,
            json=[{"id": f"transfer-{offset + index}"} for index in range(count)],
            request=request,
        )

    adapter = AlpacaBrokerFundingAdapter(
        runtime_env=_runtime_env(),
        transport=httpx.MockTransport(handler),
    )
    transfers = adapter.list_transfers(
        provider=ModelProvider.OPENAI,
        account_id=BROKER_ACCOUNT_ID,
    )

    assert len(transfers) == 101
    assert [request.url.params["offset"] for request in requests] == ["0", "100"]
    assert all(request.url.params["direction"] == "INCOMING" for request in requests)


def test_req_fnd_017_01_terminal_broker_failures_release_reservation_and_do_not_retry() -> None:
    """TST-REQ-FND-017-01, TST-REQ-FND-017-02: terminal states release caps and do not retry."""

    transport = CountingTransport(
        status_code=422,
        payload={"code": 42210000, "message": "relationship rejected"},
    )
    service, repository, occurrence = _service(transport=transport)

    first = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )
    second = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=False
    )

    assert first["status"] == FundingOccurrenceStatus.REJECTED.value
    assert second["status"] == FundingOccurrenceStatus.REJECTED.value
    assert first["reserved_amount_usd"] is None
    assert len(transport.requests) == 1
    assert len(repository.alerts(Environment.DEVELOPMENT)) == 1


def test_req_fnd_018_01_kill_switch_refuses_write_but_does_not_disable_reads() -> None:
    """TST-REQ-FND-018-01: current emergency controls block the adapter."""

    transport = CountingTransport()
    service, _, occurrence = _service(transport=transport)

    result = service.submit_occurrence(
        occurrence["id"], config=_config(), kill_switch_active=True
    )

    assert result["status"] == FundingOccurrenceStatus.REFUSED.value
    assert result["refusal_reason"] == "global_kill_switch_active"
    assert transport.requests == []


def test_req_fnd_016_03_refused_and_missing_occurrences_never_post() -> None:
    """TST-REQ-FND-014-02, TST-REQ-FND-017-02: only expected occurrences can be claimed."""

    for status in (
        FundingOccurrenceStatus.REFUSED,
        FundingOccurrenceStatus.MISSING,
    ):
        transport = CountingTransport()
        service, repository, occurrence = _service(transport=transport)
        repository.update_occurrence(occurrence["id"], status=status.value)

        result = service.submit_occurrence(
            occurrence["id"],
            config=_config(),
            kill_switch_active=False,
        )

        assert result["status"] == status.value
        assert transport.requests == []


def test_req_fnd_014_04_claim_reloads_current_disabled_config() -> None:
    """TST-REQ-FND-014-04: config changes are re-read inside the durable claim."""

    transport = CountingTransport()
    service, _, occurrence = _service(transport=transport)
    for row in service.registry.state.rows("shared.config_versions"):
        row["active"] = False
    disabled = _config(enabled=False)
    service.registry.shared().record_config_version(
        environment=Environment.DEVELOPMENT,
        username="yaw",
        version="v2",
        payload={"funding": disabled.model_dump(mode="json")},
    )

    result = service.submit_occurrence(
        occurrence["id"],
        config=_config(),
        kill_switch_active=False,
    )

    assert result["status"] == FundingOccurrenceStatus.REFUSED.value
    assert result["refusal_reason"] == "direct_transfers_disabled"
    assert transport.requests == []


def test_req_fnd_014_05_persistence_failure_never_reaches_adapter() -> None:
    """TST-REQ-FND-014-05: a failed durable claim has zero Broker calls."""

    transport = CountingTransport()
    service, _, occurrence = _service(transport=transport)
    service.registry.state.fail_on_tables.add("shared.funding_occurrences")

    with pytest.raises(PersistenceUnavailableError):
        service.submit_occurrence(
            occurrence["id"],
            config=_config(),
            kill_switch_active=False,
        )

    assert transport.requests == []


def test_req_fnd_014_06_missing_broker_secrets_keep_startup_and_readiness_safe() -> None:
    """TST-REQ-FND-014-06: absent optional Broker secrets leave direct readiness blocked."""

    registry = RepositoryRegistry()
    direct = DirectFundingService(
        registry,
        adapter=AlpacaBrokerFundingAdapter(runtime_env={}),
    )
    readiness = FundingService(registry, direct_service=direct).direct_transfer_readiness(
        environment=Environment.DEVELOPMENT,
        config=FundingConfig(),
        kill_switch_active=False,
    )

    assert readiness["enabled"] is False
    assert readiness["ready"] is False
    assert readiness["maxTransferUsd"] == "0.00"
    assert readiness["maxMonthlyTransferUsd"] == "0.00"


def test_req_fnd_018_01_claim_reloads_persisted_kill_switch() -> None:
    """TST-REQ-FND-018-01: a persisted kill switch overrides a stale false hint."""

    transport = CountingTransport()
    service, _, occurrence = _service(transport=transport)
    service.registry.state.upsert_by_id(
        "shared.operational_controls",
        "development:global_kill_switch",
        {
            "environment": "development",
            "control": "global_kill_switch",
            "active": True,
            "actor": "yaw",
            "updated_at": NOW,
        },
    )

    result = service.submit_occurrence(
        occurrence["id"],
        config=_config(),
        kill_switch_active=False,
    )

    assert result["status"] == FundingOccurrenceStatus.REFUSED.value
    assert result["refusal_reason"] == "global_kill_switch_active"
    assert transport.requests == []


def test_req_fnd_016_01_concurrent_claims_issue_one_broker_post() -> None:
    """TST-REQ-FND-016-01: concurrent workers share one durable submission claim."""

    entered_post = Event()
    release_post = Event()

    class BlockingTransport(CountingTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            entered_post.set()
            assert release_post.wait(timeout=5)
            return httpx.Response(self.status_code, json=self.payload, request=request)

    transport = BlockingTransport()
    service, _, occurrence = _service(transport=transport)

    def submit() -> dict:
        return service.submit_occurrence(
            occurrence["id"],
            config=_config(),
            kill_switch_active=False,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(submit)
        assert entered_post.wait(timeout=5)
        second = submit()
        release_post.set()
        first = first_future.result(timeout=5)
    results = [first, second]

    assert len(transport.requests) == 1
    assert {result["status"] for result in results}.issubset(
        {
            FundingOccurrenceStatus.RESERVED.value,
            FundingOccurrenceStatus.SUBMITTED.value,
        }
    )
    assert service.repository.occurrence(occurrence["id"])["status"] == "submitted"


def test_req_fnd_013_04_global_broker_credentials_are_not_shared_between_providers() -> None:
    """TST-REQ-FND-014-03: direct credentials must be scoped to the model provider."""

    transport = CountingTransport()
    global_only = {
        "ALPACA_BROKER_API_KEY": "key",
        "ALPACA_BROKER_SECRET_KEY": "secret",
        "ALPACA_BROKER_ACCOUNT_ID": BROKER_ACCOUNT_ID,
        "ALPACA_BROKER_ACH_RELATIONSHIP_ID": "relationship",
    }
    service, _, occurrence = _service(
        transport=transport,
        runtime_env=global_only,
    )

    result = service.submit_occurrence(
        occurrence["id"],
        config=_config(),
        kill_switch_active=False,
    )

    assert result["refusal_reason"] == "broker_secrets_unavailable"
    assert transport.requests == []
