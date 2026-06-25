"""Spec tests for Phase 5 execution and Phase 6 exits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, OrderSide, OrderType, PositionState, Venue
from app.services import PipelineLifecycleService


def test_req_exe_016_04_dry_run_execution_records_polymarket_and_alpaca_order_intents() -> None:
    """TST-REQ-EXE-016-04: Validates REQ-EXE-010, REQ-EXE-016, and REQ-ALP-005

    Given: approved Polymarket and Alpaca consensus outputs
    When: execution runs with live trading disabled
    Then: both venues record simulated order intents without submitting live orders
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    strategy_run = _strategy_run_with_outputs(registry, now)
    result = PipelineLifecycleService(registry).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=_market_data_pulls(now),
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["intentCount"] == 2
    assert result.payload["simulatedCount"] == 2
    assert {intent["venue"] for intent in result.payload["intents"]} == {
        Venue.POLYMARKET_US.value,
        Venue.ALPACA.value,
    }
    assert {row["status"] for row in registry.state.rows("shared.order_intents")} == {"simulated"}
    assert len(registry.state.rows("openai.order_events")) == 1
    assert len(registry.state.rows("claude.order_events")) == 1


def test_req_exe_013_04_live_execution_refuses_when_market_data_and_credentials_fail() -> None:
    """TST-REQ-EXE-013-04: Validates REQ-EXE-013, REQ-EXE-014, and REQ-EXE-017

    Given: live mode, stale market data, high spread, and missing credentials
    When: execution runs
    Then: the order intent is persisted as refused before venue submission
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    strategy_run = _strategy_run_with_outputs(registry, now, include_alpaca=False)
    stale_pull = _market_data_pulls(now - timedelta(minutes=20), include_alpaca=False)
    stale_pull[0]["candidates"][0]["spread"] = "0.20"

    result = PipelineLifecycleService(registry).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-live",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=stale_pull,
        config_payload=_config(live_enabled=True),
        credential_status={Venue.POLYMARKET_US.value: False},
        started_at=now,
        completed_at=now,
    )
    intent = result.payload["intents"][0]

    assert result.payload["status"] == "refused"
    assert intent["status"] == "refused"
    assert "STALE_MARKET_DATA" in str(intent["refusalReason"])
    assert "SLIPPAGE_LIMIT" in str(intent["refusalReason"])
    assert "CREDENTIAL_MISSING" in str(intent["refusalReason"])


def test_req_exe_016_05_execution_reconciles_existing_nonterminal_intent_before_retry() -> None:
    """TST-REQ-EXE-016-05: Validates REQ-EXE-016

    Given: a prior order intent with the same idempotency key is nonterminal
    When: execution tries to process the same consensus output again
    Then: the intent is marked for reconciliation before any retry
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    service = PipelineLifecycleService(registry)
    strategy_run = _strategy_run_with_outputs(registry, now, include_alpaca=False)
    first = service.run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-retry",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )
    registry.state.rows("shared.order_intents")[0]["status"] = "submitted"

    second = service.run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-retry",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )

    assert first.payload["intentCount"] == 1
    assert second.payload["reconciliationCount"] == 1
    assert registry.state.rows("shared.order_intents")[0]["status"] == "reconcile_first"


def test_req_ext_001_03_exit_run_records_polymarket_and_stock_exit_intents() -> None:
    """TST-REQ-EXT-001-03: Validates REQ-EXT-001 through REQ-EXT-006

    Given: open Polymarket and Alpaca positions that cross exit thresholds
    When: exit monitoring runs in dry-run mode
    Then: exit intents are persisted and simulated for both venues
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.record_polymarket_wallet_position(
        environment=Environment.DEVELOPMENT,
        wallet_address="0x1111111111111111111111111111111111111111",
        market_id="market-1",
        asset_id="yes-token",
        state=PositionState.OPEN.value,
        size=Decimal("100"),
        realized_pnl_usd=Decimal("0"),
        entry_price=Decimal("0.40"),
        opened_at=now - timedelta(hours=10),
        trade_ids=["trade-1"],
        created_at=now,
        updated_at=now,
    )
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-1",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=24),
        raw_payload={"id": "fill-1"},
        created_at=now,
    )
    shared.record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        current_price=Decimal("112"),
        market_value=Decimal("112"),
        unrealized_pnl_usd=Decimal("12"),
        raw_payload={"high_watermark_price": "115"},
        observed_at=now,
        created_at=now,
    )

    result = PipelineLifecycleService(registry).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-exit",
        trigger="manual",
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["openPositionCount"] == 2
    assert result.payload["triggeredCount"] >= 2
    assert result.payload["simulatedCount"] == result.payload["triggeredCount"]
    assert {intent["venue"] for intent in result.payload["intents"]} == {
        Venue.POLYMARKET_US.value,
        Venue.ALPACA.value,
    }
    assert len(registry.state.rows("shared.exit_intents")) == result.payload["triggeredCount"]


def _strategy_run_with_outputs(
    registry: RepositoryRegistry,
    now: datetime,
    *,
    include_alpaca: bool = True,
) -> dict:
    shared = registry.shared()
    run = shared.record_strategy_consensus_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        reasoning_run_id="reasoning-1",
        trigger="manual",
        status="approved",
        config={},
        vote_count=2,
        approved_count=2 if include_alpaca else 1,
        refused_count=0,
        started_at=now,
        completed_at=now,
    )
    outputs = [
        shared.record_strategy_consensus_output(
            environment=Environment.DEVELOPMENT,
            consensus_run_id=run["id"],
            venue=Venue.POLYMARKET_US.value,
            instrument_id="market-1:yes-token",
            model_provider=ModelProvider.OPENAI,
            status="approved",
            side=OrderSide.BUY.value,
            size_multiplier=Decimal("1"),
            signal_count=2,
            strategy_names=["arbitrage", "convergence"],
            source_payload={"candidate": {"marketSlug": "market-1"}},
            created_at=now,
        )
    ]
    if include_alpaca:
        outputs.append(
            shared.record_strategy_consensus_output(
                environment=Environment.DEVELOPMENT,
                consensus_run_id=run["id"],
                venue=Venue.ALPACA.value,
                instrument_id="alpaca:SPY",
                model_provider=ModelProvider.CLAUDE,
                status="approved",
                side=OrderSide.BUY.value,
                size_multiplier=Decimal("0.5"),
                signal_count=1,
                strategy_names=["momentum"],
                source_payload={"candidate": {"symbol": "SPY"}},
                created_at=now,
            )
        )
    return {
        "id": run["id"],
        "status": run["status"],
        "approvedCount": run["approved_count"],
        "refusedCount": run["refused_count"],
        "voteCount": run["vote_count"],
        "outputs": outputs,
    }


def _market_data_pulls(
    pulled_at: datetime,
    *,
    include_alpaca: bool = True,
) -> list[dict]:
    pulls = [
        {
            "id": "pull-polymarket",
            "venue": Venue.POLYMARKET_US.value,
            "status": "pulled",
            "createdAt": pulled_at.isoformat(),
            "candidates": [
                {
                    "id": "market-1:yes-token",
                    "venue": Venue.POLYMARKET_US.value,
                    "marketId": "market-1",
                    "outcomeId": "yes-token",
                    "marketSlug": "market-1",
                    "price": "0.62",
                    "spread": "0.01",
                    "pulledAt": pulled_at.isoformat(),
                    "metrics": {"volume10m": "300", "baselineVolume10m": "80"},
                }
            ],
        }
    ]
    if include_alpaca:
        pulls.append(
            {
                "id": "pull-alpaca",
                "venue": Venue.ALPACA.value,
                "status": "pulled",
                "createdAt": pulled_at.isoformat(),
                "candidates": [
                    {
                        "id": "alpaca:SPY",
                        "venue": Venue.ALPACA.value,
                        "symbol": "SPY",
                        "price": "500.00",
                        "spread": "0.001",
                        "pulledAt": pulled_at.isoformat(),
                    }
                ],
            }
        )
    return pulls


def _config(*, live_enabled: bool) -> dict:
    return {
        "live_enabled": live_enabled,
        "venues": {
            Venue.POLYMARKET_US.value: {"enabled": True},
            Venue.ALPACA.value: {"enabled": True},
        },
        "risk": {
            "polymarket": {
                "max_position_usd": "25.00",
                "max_daily_loss_usd": "50.00",
                "max_open_positions": 5,
                "market_order_slippage_threshold": "0.02",
            },
            "alpaca": {
                "max_position_usd": "100.00",
                "max_daily_loss_usd": "100.00",
                "max_open_positions": 5,
                "max_portfolio_allocation_per_symbol": "0.10",
                "market_order_slippage_threshold": "0.005",
            },
        },
        "alpaca": {"account_mode": "paper"},
        "execution": {
            "market_data_freshness_seconds": 300,
            "order_type": OrderType.MARKET.value,
            "alpaca": {"model_capital_usd": "1000.00"},
        },
        "exit": {
            "polymarket": {
                "profit_target_usd": "5.00",
                "profit_target_pct": "0.25",
                "volume_spike_multiplier": "3.00",
                "max_thesis_age_hours": "72",
                "min_stale_price_move_pct": "0.10",
            },
            "alpaca": {
                "profit_target_pct": "0.08",
                "stop_loss_pct": "0.04",
                "trailing_stop_pct": "0.05",
                "max_position_age_hours": "168",
                "min_stale_price_move_pct": "0.03",
                "market_hours_only": True,
            },
        },
    }
