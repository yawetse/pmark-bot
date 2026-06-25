"""Spec tests for Phase 4 strategy consensus persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, Venue
from app.services import StrategyConsensusService


def test_req_str_008_03_polymarket_multi_vote_consensus_approves_full_position() -> None:
    """TST-REQ-STR-008-03: Validates REQ-STR-004, REQ-STR-005, REQ-STR-006, and REQ-STR-008

    Given: Polymarket arbitrage, convergence, and whale-copy votes align
    When: strategy consensus runs
    Then: the output is approved with a full-size multiplier before risk sizing
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    scanner_run, reasoning_run = _polymarket_rows(
        registry,
        now,
        price="0.45",
        related_price="0.62",
        estimated_probability="0.61",
        target_wallets=["wallet-1"],
    )

    result = StrategyConsensusService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        scanner_run=scanner_run,
        reasoning_run=reasoning_run,
        config_payload={},
        started_at=now,
        completed_at=now,
    )
    outputs = result.payload["outputs"]
    accepted_votes = [vote for vote in result.payload["votes"] if vote["status"] == "accepted"]

    assert result.payload["status"] == "approved"
    assert result.payload["approvedCount"] == 1
    assert outputs[0]["status"] == "approved"
    assert outputs[0]["sizeMultiplier"] == "1"
    assert {vote["strategyName"] for vote in accepted_votes} == {
        "arbitrage",
        "convergence",
        "whale_copy",
    }
    assert len(registry.state.rows("openai.strategy_signals")) == 3


def test_req_str_008_04_conflicting_strategy_votes_refuse_trade() -> None:
    """TST-REQ-STR-008-04: Validates REQ-STR-008

    Given: arbitrage and convergence produce opposite Polymarket directions
    When: strategy consensus runs
    Then: the consensus output is refused with a conflict reason
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    scanner_run, reasoning_run = _polymarket_rows(
        registry,
        now,
        price="0.45",
        related_price="0.30",
        estimated_probability="0.61",
        target_wallets=[],
    )

    result = StrategyConsensusService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-2",
        trigger="manual",
        scanner_run=scanner_run,
        reasoning_run=reasoning_run,
        config_payload={},
        started_at=now,
        completed_at=now,
    )
    output = result.payload["outputs"][0]
    accepted_votes = [vote for vote in result.payload["votes"] if vote["status"] == "accepted"]

    assert result.payload["status"] == "refused"
    assert output["status"] == "refused"
    assert output["refusalReason"] == "strategy direction conflict"
    assert {vote["direction"] for vote in accepted_votes} == {"buy", "sell"}


def test_req_str_008_05_stock_single_vote_approves_half_position() -> None:
    """TST-REQ-STR-008-05: Validates REQ-STR-008

    Given: one stock strategy vote passes for a scored Alpaca candidate
    When: stock consensus runs
    Then: the output is approved with a half-size multiplier
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    scanner_run, reasoning_run = _stock_rows(
        registry,
        now,
        symbol="SPY",
        strategy_names=["mean_reversion"],
        metrics={"meanReversionPct": "-0.04"},
        directional_signal="bullish",
    )

    result = StrategyConsensusService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-3",
        trigger="manual",
        scanner_run=scanner_run,
        reasoning_run=reasoning_run,
        config_payload={},
        started_at=now,
        completed_at=now,
    )
    output = result.payload["outputs"][0]
    accepted_votes = [vote for vote in result.payload["votes"] if vote["status"] == "accepted"]

    assert result.payload["status"] == "approved"
    assert output["sizeMultiplier"] == "0.5"
    assert accepted_votes[0]["strategyName"] == "mean_reversion"
    assert accepted_votes[0]["direction"] == "buy"


def test_req_str_008_06_stock_momentum_and_event_votes_approve_full_position() -> None:
    """TST-REQ-STR-008-06: Validates REQ-STR-008

    Given: momentum and event or unusual-volume stock votes align
    When: stock consensus runs
    Then: the output is approved with a full-size multiplier
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    scanner_run, reasoning_run = _stock_rows(
        registry,
        now,
        symbol="NVDA",
        strategy_names=["momentum", "unusual_volume"],
        metrics={"momentumPct": "0.05", "unusualVolumeRatio": "2.20"},
        directional_signal="bullish",
    )

    result = StrategyConsensusService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-4",
        trigger="manual",
        scanner_run=scanner_run,
        reasoning_run=reasoning_run,
        config_payload={},
        started_at=now,
        completed_at=now,
    )
    output = result.payload["outputs"][0]
    accepted_votes = [vote for vote in result.payload["votes"] if vote["status"] == "accepted"]

    assert result.payload["status"] == "approved"
    assert output["sizeMultiplier"] == "1"
    assert {vote["strategyName"] for vote in accepted_votes} == {"momentum", "event"}
    assert {vote["direction"] for vote in accepted_votes} == {"buy"}


def _polymarket_rows(
    registry: RepositoryRegistry,
    now: datetime,
    *,
    price: str,
    related_price: str,
    estimated_probability: str,
    target_wallets: list[str],
) -> tuple[dict, dict]:
    shared = registry.shared()
    scanner_run = shared.record_scanner_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-polymarket",
        trigger="manual",
        status="completed",
        config={},
        source_pull_ids=["pull-1"],
        accepted_count=1,
        rejected_count=0,
        started_at=now,
        completed_at=now,
    )
    candidate = shared.record_scanner_candidate(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=scanner_run["id"],
        venue=Venue.POLYMARKET_US.value,
        instrument_id="market-1:yes-token",
        display_name="Will rates fall? - Yes",
        status="accepted",
        strategy_names=["order_book_depth", "resolution_window"],
        price=Decimal(price),
        liquidity=Decimal("1200"),
        spread=Decimal("0.02"),
        hours_to_resolution=Decimal("24"),
        metrics={
            "targetWalletOverlap": len(target_wallets),
            "targetWallets": target_wallets,
            "targetWalletActionAgeSeconds": 120,
        },
        source_payload={
            "relatedGroup": "rates",
            "relatedPrice": related_price,
        },
        market_id="market-1",
        outcome_id="yes-token",
        created_at=now,
    )
    reasoning_run = shared.record_reasoning_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-polymarket",
        scanner_run_id=scanner_run["id"],
        trigger="manual",
        status="completed",
        config={},
        provider_count=1,
        prompt_count=1,
        scored_count=1,
        skipped_count=0,
        failed_count=0,
        started_at=now,
        completed_at=now,
    )
    shared.record_reasoning_output(
        environment=Environment.DEVELOPMENT,
        reasoning_run_id=reasoning_run["id"],
        scanner_candidate_id=candidate["id"],
        venue=Venue.POLYMARKET_US.value,
        instrument_id="market-1:yes-token",
        model_provider=ModelProvider.OPENAI,
        prompt_version="pm-brain-v1",
        status="scored",
        directional_signal="buy_yes",
        signal_strength=Decimal("0.16"),
        confidence=Decimal("0.81"),
        estimated_probability=Decimal(estimated_probability),
        output_thesis="model estimate is above market price",
        cost_usd=Decimal("0.01"),
        prompt_tokens=100,
        completion_tokens=50,
        prompt_payload={},
        response_payload={},
        check_results=[],
        created_at=now,
    )
    return scanner_run, reasoning_run


def _stock_rows(
    registry: RepositoryRegistry,
    now: datetime,
    *,
    symbol: str,
    strategy_names: list[str],
    metrics: dict[str, str],
    directional_signal: str,
) -> tuple[dict, dict]:
    shared = registry.shared()
    scanner_run = shared.record_scanner_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id=f"pipeline-{symbol.lower()}",
        trigger="manual",
        status="completed",
        config={},
        source_pull_ids=["pull-alpaca"],
        accepted_count=1,
        rejected_count=0,
        started_at=now,
        completed_at=now,
    )
    candidate = shared.record_scanner_candidate(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=scanner_run["id"],
        venue=Venue.ALPACA.value,
        instrument_id=f"alpaca:{symbol}",
        display_name=symbol,
        status="accepted",
        strategy_names=strategy_names,
        price=Decimal("100"),
        liquidity=Decimal("3"),
        spread=Decimal("0.02"),
        metrics=metrics,
        source_payload={"symbol": symbol},
        symbol=symbol,
        created_at=now,
    )
    reasoning_run = shared.record_reasoning_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id=f"pipeline-{symbol.lower()}",
        scanner_run_id=scanner_run["id"],
        trigger="manual",
        status="completed",
        config={},
        provider_count=1,
        prompt_count=1,
        scored_count=1,
        skipped_count=0,
        failed_count=0,
        started_at=now,
        completed_at=now,
    )
    shared.record_reasoning_output(
        environment=Environment.DEVELOPMENT,
        reasoning_run_id=reasoning_run["id"],
        scanner_candidate_id=candidate["id"],
        venue=Venue.ALPACA.value,
        instrument_id=f"alpaca:{symbol}",
        model_provider=ModelProvider.CLAUDE,
        prompt_version="stock-brain-v1",
        status="scored",
        directional_signal=directional_signal,
        signal_strength=Decimal("0.08"),
        confidence=Decimal("0.74"),
        estimated_probability=Decimal("0.62"),
        output_thesis="stock signal supports the trade",
        cost_usd=Decimal("0.02"),
        prompt_tokens=100,
        completion_tokens=40,
        prompt_payload={},
        response_payload={},
        check_results=[],
        created_at=now,
    )
    return scanner_run, reasoning_run
