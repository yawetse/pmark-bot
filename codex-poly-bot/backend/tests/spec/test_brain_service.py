"""Spec tests for Phase 3 reasoning and brain persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, Venue
from app.services import BrainService, FakeLlmProvider, ScannerService


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
