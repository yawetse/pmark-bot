"""Spec tests for Phase 3 reasoning and brain persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db import DatabaseState, RepositoryRegistry
from app.domain import Environment, ModelProvider, Venue
from app.services import BrainService, FakeLlmProvider, ScannerService
from app.services.brain_service import AI_USAGE_BUDGET_QUERY_TIMEOUT_MS, _remaining_budget


class _ReasoningRunNotNullState(DatabaseState):
    """Mirror the production reasoning_runs completed_at constraint."""

    def insert(self, table_name: str, row: dict) -> dict:
        if table_name == "shared.reasoning_runs":
            assert row["completed_at"] is not None
        return super().insert(table_name, row)


class _AiUsageRowsMustStayBoundedState(DatabaseState):
    """Fail if a budget check attempts to load every AI usage payload."""

    budget_timeout_ms: int | None = None

    def rows(self, table_name: str, **kwargs):
        if table_name == "shared.ai_usage_events":
            raise AssertionError("budget checks must use a database aggregate")
        return super().rows(table_name, **kwargs)

    def sum_decimal(self, table_name: str, column_name: str, **kwargs) -> Decimal:
        if table_name == "shared.ai_usage_events":
            self.budget_timeout_ms = kwargs.get("timeout_ms")
        return super().sum_decimal(table_name, column_name, **kwargs)


def test_req_llm_001_04_brain_scores_polymarket_and_stock_scanner_survivors() -> None:
    """TST-REQ-LLM-001-04: Validates REQ-LLM-001, REQ-LLM-003, and REQ-OBS-005

    Given: accepted Polymarket and Alpaca scanner candidates
    When: the brain runs with two model providers
    Then: reasoning outputs, normalized signals, prompt checks, and token usage are persisted
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    _record_stock_bars(registry, now)
    scanner_run = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        started_at=now,
        completed_at=now,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        market_data_pulls=[
            {
                "id": "pull-polymarket",
                "venue": Venue.POLYMARKET_US.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "polymarket_us:condition-1:yes-token",
                        "venue": Venue.POLYMARKET_US.value,
                        "market": "Will rates fall? - Yes",
                        "marketId": "condition-1",
                        "tokenId": "yes-token",
                        "state": "priced",
                        "midpoint": "0.45",
                        "price": "0.45",
                        "bestBid": "0.44",
                        "bestAsk": "0.46",
                        "bidDepth": "600",
                        "askDepth": "650",
                        "liquidity": "1250",
                        "spread": "0.02",
                        "volume": "10000",
                        "category": "Politics",
                        "endDate": (now + timedelta(hours=24)).isoformat(),
                        "active": True,
                        "closed": False,
                    }
                ],
            },
            {
                "id": "pull-alpaca",
                "venue": Venue.ALPACA.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "alpaca:SPY",
                        "venue": Venue.ALPACA.value,
                        "symbol": "SPY",
                        "state": "priced",
                        "price": "106",
                        "liquidity": "3",
                        "spread": "0.02",
                    }
                ],
            },
        ],
    )
    providers = (
        FakeLlmProvider(ModelProvider.OPENAI, cost_estimate=Decimal("0.01")),
        FakeLlmProvider(ModelProvider.CLAUDE, cost_estimate=Decimal("0.02")),
    )

    result = BrainService(registry, providers=providers).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        scanner_run=scanner_run.payload,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        started_at=now,
        completed_at=now,
    )
    outputs = registry.shared().reasoning_outputs(environment=Environment.DEVELOPMENT)
    runs = registry.shared().reasoning_runs(environment=Environment.DEVELOPMENT)
    usage = registry.state.rows("shared.ai_usage_events")

    assert scanner_run.payload["acceptedCount"] == 2
    assert result.payload["status"] == "completed"
    assert runs[0]["status"] == "completed"
    assert runs[0]["scored_count"] == 4
    assert result.payload["promptCount"] == 4
    assert result.payload["scoredCount"] == 4
    assert {output["directional_signal"] for output in outputs} == {"buy_yes", "bullish"}
    assert {output["prompt_version"] for output in outputs} == {"pm-brain-v1", "stock-brain-v1"}
    assert all(output["check_results"] for output in outputs)
    assert sum(row["cost_usd"] for row in usage) == Decimal("0.06")
    assert providers[0].call_count == 2
    assert providers[1].call_count == 2


def test_req_llm_001_05_selected_venue_receives_limited_prompt_slots_first() -> None:
    """Alpaca candidates must not be starved by earlier Polymarket rows."""

    registry = RepositoryRegistry()
    now = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    provider = FakeLlmProvider(ModelProvider.OPENAI, cost_estimate=Decimal("0.01"))
    result = BrainService(registry, providers=(provider,)).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-priority",
        trigger="scheduled",
        scanner_run={
            "id": "scanner-priority",
            "candidates": [
                {
                    "id": "pm-first",
                    "status": "accepted",
                    "venue": Venue.POLYMARKET_US.value,
                    "instrumentId": "market-1:yes",
                    "marketId": "market-1",
                    "outcomeId": "yes",
                    "price": "0.50",
                },
                {
                    "id": "stock-second",
                    "status": "accepted",
                    "venue": Venue.ALPACA.value,
                    "instrumentId": "alpaca:SPY",
                    "symbol": "SPY",
                    "price": "500",
                    "strategyNames": ["liquidity"],
                },
                {
                    "id": "stock-stronger",
                    "status": "accepted",
                    "venue": Venue.ALPACA.value,
                    "instrumentId": "alpaca:QQQ",
                    "symbol": "QQQ",
                    "price": "450",
                    "strategyNames": ["momentum", "liquidity", "unusual_volume"],
                },
            ],
        },
        config_payload={
            "default_selected_venue": Venue.ALPACA.value,
            "reasoning": {"max_prompts_per_provider_per_run": 1},
        },
        started_at=now,
        completed_at=now,
    )

    assert result.payload["scoredCount"] == 1
    scored = [output for output in result.payload["outputs"] if output["status"] == "scored"]
    skipped = [output for output in result.payload["outputs"] if output["status"] == "skipped"]
    assert scored[0]["venue"] == Venue.ALPACA.value
    assert scored[0]["instrumentId"] == "alpaca:QQQ"
    assert {output["venue"] for output in skipped} == {
        Venue.ALPACA.value,
        Venue.POLYMARKET_US.value,
    }
    assert {output["refusalReason"] for output in skipped} == {"provider rate limit reached"}


def test_req_llm_001_06_scheduled_reasoning_run_satisfies_production_timestamp_constraint() -> None:
    """TST-REQ-LLM-001-06: Validates REQ-LLM-001 and REQ-DB-001

    Given: a scheduled reasoning run begins without a final completion time
    When: the running row is written to the production-shaped store
    Then: the provisional row satisfies the non-null completed_at constraint
    """
    registry = RepositoryRegistry(_ReasoningRunNotNullState())
    started_at = datetime(2026, 7, 22, 22, 37, tzinfo=UTC)

    result = BrainService(registry, providers=()).run(
        environment=Environment.PRODUCTION,
        pipeline_run_id="pipeline-scheduled",
        trigger="scheduled",
        scanner_run={"id": "scanner-scheduled", "candidates": []},
        config_payload={},
        started_at=started_at,
        completed_at=None,
    )

    assert result.payload["status"] == "no_candidates"
    assert result.payload["completedAt"] is not None


def test_req_llm_004_04_brain_records_budget_and_credential_skips() -> None:
    """TST-REQ-LLM-004-04: Validates REQ-LLM-004

    Given: scanner survivors and providers that cannot score
    When: the brain runs
    Then: skipped reasoning rows explain the budget or provider gate
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    scanner_run = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-2",
        trigger="manual",
        started_at=now,
        completed_at=now,
        config_payload={},
        market_data_pulls=[
            {
                "id": "pull-polymarket",
                "venue": Venue.POLYMARKET_US.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "polymarket_us:condition-1:yes-token",
                        "venue": Venue.POLYMARKET_US.value,
                        "market": "Will rates fall? - Yes",
                        "marketId": "condition-1",
                        "tokenId": "yes-token",
                        "state": "priced",
                        "midpoint": "0.45",
                        "price": "0.45",
                        "bestBid": "0.44",
                        "bestAsk": "0.46",
                        "bidDepth": "600",
                        "askDepth": "650",
                        "liquidity": "1250",
                        "spread": "0.02",
                        "volume": "10000",
                        "category": "Politics",
                        "endDate": (now + timedelta(hours=24)).isoformat(),
                        "active": True,
                        "closed": False,
                    }
                ],
            }
        ],
    )
    providers = (
        FakeLlmProvider(ModelProvider.OPENAI, remaining_budget=Decimal("0")),
        FakeLlmProvider(ModelProvider.CLAUDE, enabled=False),
    )

    result = BrainService(registry, providers=providers).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-2",
        trigger="manual",
        scanner_run=scanner_run.payload,
        config_payload={},
        started_at=now,
        completed_at=now,
    )
    outputs = registry.shared().reasoning_outputs(environment=Environment.DEVELOPMENT)

    assert result.payload["status"] == "skipped"
    assert result.payload["skippedCount"] == 2
    assert {output["status"] for output in outputs} == {"skipped"}
    assert {output["refusal_reason"] for output in outputs} == {
        "provider budget exhausted",
        "provider disabled or credential missing",
    }


def test_req_llm_004_05_provider_budget_uses_rolling_24_hour_window() -> None:
    """Old model spend must not permanently stop the trading pipeline."""

    registry = RepositoryRegistry(_AiUsageRowsMustStayBoundedState())
    now = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    for created_at, cost in (
        (now - timedelta(hours=25), Decimal("19.00")),
        (now - timedelta(hours=2), Decimal("3.00")),
    ):
        registry.shared().record_ai_usage_event(
            environment=Environment.PRODUCTION,
            provider=ModelProvider.OPENAI,
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=cost,
            created_at=created_at,
        )

    remaining = _remaining_budget(
        registry=registry,
        environment=Environment.PRODUCTION,
        provider=ModelProvider.OPENAI,
        budget=Decimal("20.00"),
        window_hours=24,
        now=now,
    )

    assert remaining == Decimal("17.00")
    assert registry.state.budget_timeout_ms == AI_USAGE_BUDGET_QUERY_TIMEOUT_MS


def _record_stock_bars(registry: RepositoryRegistry, now: datetime) -> None:
    for index, close_price in enumerate((Decimal("100"), Decimal("102"), Decimal("106"))):
        registry.shared().record_stock_bar(
            environment=Environment.DEVELOPMENT,
            symbol="SPY",
            timeframe="1Day",
            bar_start_at=now - timedelta(days=2 - index),
            open_price=Decimal("102") if index == 2 else close_price,
            high_price=Decimal("107") if index == 2 else close_price,
            low_price=Decimal("101") if index == 2 else close_price,
            close_price=close_price,
            volume=Decimal("300000") if index == 2 else Decimal("100000"),
            source="alpaca market data api",
            raw_payload={"index": index},
        )
