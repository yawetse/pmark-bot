"""Spec tests for Phase 5 execution and Phase 6 exits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.adapters.aws import InMemorySesEmailAdapter
from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, OrderSide, OrderType, PositionState, Venue
from app.services import NotificationDeliveryLedger, PipelineLifecycleService
from app.venues import PolymarketLiveOrderRequest, VenueCallResult


class RecordingAlpacaSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def submit_order(
        self,
        *,
        account_mode: str,
        symbol: str,
        notional: Decimal | None = None,
        quantity: Decimal | None = None,
        side: str = "buy",
        client_order_id: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "account_mode": account_mode,
                "symbol": symbol,
                "notional": str(notional) if notional is not None else "",
                "quantity": str(quantity) if quantity is not None else "",
                "side": side,
                "client_order_id": client_order_id or "",
            }
        )
        return f"alpaca-{side}-{symbol}-{len(self.calls)}"


class RecordingPolymarketSubmitter:
    def __init__(self) -> None:
        self.submit_calls: list[PolymarketLiveOrderRequest] = []
        self.close_calls: list[dict[str, str]] = []

    def submit_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        self.submit_calls.append(request)
        return VenueCallResult(ok=True, payload={"venue_order_id": f"pm-entry-{len(self.submit_calls)}"})

    def close_position(
        self,
        *,
        market_slug: str,
        current_price: Decimal | str | None = None,
        slippage_tolerance_bips: int | None = None,
        slippage_tolerance_ticks: int | None = None,
    ) -> VenueCallResult:
        self.close_calls.append(
            {
                "market_slug": market_slug,
                "current_price": str(current_price or ""),
                "bips": str(slippage_tolerance_bips or ""),
                "ticks": str(slippage_tolerance_ticks or ""),
            }
        )
        return VenueCallResult(ok=True, payload={"venue_order_id": f"pm-exit-{len(self.close_calls)}"})


class FailingPolymarketSubmitter:
    def submit_order(self, request: PolymarketLiveOrderRequest) -> VenueCallResult:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("Polymarket SDK call failed",),
            payload={
                "error_type": "BadRequestError",
                "operation": "submit_order",
                "market_slug": request.market_slug,
                "status_code": 400,
            },
        )


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


def test_req_exe_016_06_live_execution_submits_when_submitters_are_configured() -> None:
    """TST-REQ-EXE-016-06: Validates REQ-EXE-010, REQ-ALP-006, and REQ-EXE-016

    Given: live mode, fresh market data, credentials, and live submitters
    When: execution runs
    Then: approved entry intents are submitted through venue adapters
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    alpaca = RecordingAlpacaSubmitter()
    polymarket = RecordingPolymarketSubmitter()
    result = PipelineLifecycleService(
        registry,
        alpaca_submitter=alpaca,
        polymarket_submitter=polymarket,
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-live-submit",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now),
        market_data_pulls=_market_data_pulls(now),
        config_payload=_config(live_enabled=True),
        credential_status={Venue.POLYMARKET_US.value: True, Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["submittedCount"] == 2
    assert {intent["status"] for intent in result.payload["intents"]} == {"submitted"}
    assert polymarket.submit_calls[0].market_slug == "market-1"
    assert alpaca.calls[0]["symbol"] == "SPY"
    assert alpaca.calls[0]["side"] == "buy"
    assert len(alpaca.calls[0]["client_order_id"]) == 64
    execution_row = registry.state.rows("shared.execution_runs")[0]
    assert execution_row["status"] == "completed"
    assert execution_row["intent_count"] == 2
    assert execution_row["submitted_count"] == 2


def test_req_exe_016_07_polymarket_order_uses_nested_candidate_market_slug() -> None:
    """TST-REQ-EXE-016-07: Validates REQ-EXE-010 and REQ-VEN-004

    Given: a production-shaped Polymarket market candidate with the slug in its source payload
    When: live execution builds an SDK order request
    Then: the adapter receives the real market slug, not the venue name fallback
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    pulls = _market_data_pulls(now, include_alpaca=False)
    candidate = pulls[0]["candidates"][0]
    candidate.pop("marketSlug")
    candidate["source_payload"] = {"marketSlug": "will-fed-cut"}
    strategy_run = _strategy_run_with_outputs(registry, now, include_alpaca=False)
    strategy_run["outputs"][0]["source_payload"]["candidate"].pop("marketSlug")
    polymarket = RecordingPolymarketSubmitter()

    result = PipelineLifecycleService(registry, polymarket_submitter=polymarket).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-nested-slug",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=pulls,
        config_payload=_config(live_enabled=True),
        credential_status={Venue.POLYMARKET_US.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert polymarket.submit_calls[0].market_slug == "will-fed-cut"


def test_req_exe_016_09_polymarket_buy_no_uses_buy_short_intent() -> None:
    """TST-REQ-EXE-016-09: Validates REQ-EXE-010 and REQ-VEN-004

    Given: a persisted Polymarket consensus output from a model buy_no signal
    When: live execution builds the SDK order request
    Then: the entry order buys short rather than trying to sell an existing long
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    strategy_run = _strategy_run_with_outputs(registry, now, include_alpaca=False)
    output_row = registry.state.rows("shared.strategy_consensus_outputs")[0]
    output_row["side"] = OrderSide.SELL.value
    output_row["source_payload"]["output"] = {"directional_signal": "buy_no"}
    polymarket = RecordingPolymarketSubmitter()

    result = PipelineLifecycleService(registry, polymarket_submitter=polymarket).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-buy-no-entry",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=True),
        credential_status={Venue.POLYMARKET_US.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert polymarket.submit_calls[0].intent == "ORDER_INTENT_BUY_SHORT"


def test_req_exe_016_08_polymarket_sdk_failure_payload_is_persisted() -> None:
    """TST-REQ-EXE-016-08: Validates REQ-EXE-016 and REQ-OBS-006

    Given: a live Polymarket SDK submit failure with safe diagnostic metadata
    When: execution records the refused order intent
    Then: the dashboard can read the failure payload without exposing credentials
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)

    result = PipelineLifecycleService(registry, polymarket_submitter=FailingPolymarketSubmitter()).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-sdk-failure",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now, include_alpaca=False),
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=True),
        credential_status={Venue.POLYMARKET_US.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "refused"
    intent_row = registry.state.rows("shared.order_intents")[0]
    execution_result = intent_row["source_payload"]["executionResult"]
    assert execution_result["error_type"] == "BadRequestError"
    assert execution_result["market_slug"] == "market-1"
    assert "secret" not in str(execution_result).lower()


def test_req_exe_016_07_live_execution_routes_submitters_by_model_provider() -> None:
    """TST-REQ-EXE-016-07: Validates REQ-EXE-016 and REQ-WAL-001

    Given: live execution has provider-specific venue submitters
    When: OpenAI and Claude outputs are approved
    Then: each output is submitted through the account for its venue and model provider
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    openai_alpaca = RecordingAlpacaSubmitter()
    claude_alpaca = RecordingAlpacaSubmitter()
    openai_polymarket = RecordingPolymarketSubmitter()
    claude_polymarket = RecordingPolymarketSubmitter()

    result = PipelineLifecycleService(
        registry,
        alpaca_submitters={
            ModelProvider.OPENAI: openai_alpaca,
            ModelProvider.CLAUDE: claude_alpaca,
        },
        polymarket_submitters={
            ModelProvider.OPENAI: openai_polymarket,
            ModelProvider.CLAUDE: claude_polymarket,
        },
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-model-routed-submit",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now),
        market_data_pulls=_market_data_pulls(now),
        config_payload=_config(live_enabled=True),
        credential_status={
            f"{Venue.POLYMARKET_US.value}:{ModelProvider.OPENAI.value}": True,
            f"{Venue.ALPACA.value}:{ModelProvider.CLAUDE.value}": True,
        },
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "completed"
    assert len(openai_polymarket.submit_calls) == 1
    assert len(claude_polymarket.submit_calls) == 0
    assert len(openai_alpaca.calls) == 0
    assert len(claude_alpaca.calls) == 1


def test_req_exe_016_08_live_execution_does_not_fallback_to_other_model_account() -> None:
    """TST-REQ-EXE-016-08: Validates REQ-EXE-016 and REQ-WAL-001

    Given: one model provider lacks a venue submitter
    When: that provider has an approved live output
    Then: the order is refused instead of using another provider's account
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    openai_alpaca = RecordingAlpacaSubmitter()
    openai_polymarket = RecordingPolymarketSubmitter()

    result = PipelineLifecycleService(
        registry,
        alpaca_submitters={ModelProvider.OPENAI: openai_alpaca},
        polymarket_submitters={ModelProvider.OPENAI: openai_polymarket},
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-no-cross-provider-fallback",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now),
        market_data_pulls=_market_data_pulls(now),
        config_payload=_config(live_enabled=True),
        credential_status={
            f"{Venue.POLYMARKET_US.value}:{ModelProvider.OPENAI.value}": True,
            f"{Venue.ALPACA.value}:{ModelProvider.CLAUDE.value}": True,
        },
        started_at=now,
        completed_at=now,
    )

    intents_by_venue = {intent["venue"]: intent for intent in result.payload["intents"]}

    assert intents_by_venue[Venue.POLYMARKET_US.value]["status"] == "submitted"
    assert intents_by_venue[Venue.ALPACA.value]["status"] == "refused"
    assert intents_by_venue[Venue.ALPACA.value]["refusalReason"] == "LIVE_SUBMITTER_NOT_CONFIGURED"
    assert len(openai_alpaca.calls) == 0


def test_req_not_006_04_live_execution_trade_submission_sends_email_notification() -> None:
    """TST-REQ-NOT-006-04: Validates REQ-NOT-006 and REQ-EXE-016

    Given: live execution submits approved orders and trade emails are enabled
    When: execution records submitted intents
    Then: trade-placed notifications are sent for actual submitted orders only
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    alpaca = RecordingAlpacaSubmitter()
    polymarket = RecordingPolymarketSubmitter()
    adapter = InMemorySesEmailAdapter()
    ledger = NotificationDeliveryLedger()

    result = PipelineLifecycleService(
        registry,
        alpaca_submitter=alpaca,
        polymarket_submitter=polymarket,
        notification_adapter=adapter,
        notification_ledger=ledger,
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-live-email",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now),
        market_data_pulls=_market_data_pulls(now),
        config_payload={
            **_config(live_enabled=True),
            "notifications": {
                "recipients": {"yaw": "yaw@example.com"},
                "email_on_trade_placed": True,
            },
        },
        credential_status={Venue.POLYMARKET_US.value: True, Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 2
    assert adapter.sent_count == 2
    assert {record.notification_type for record in ledger.records} == {"trade_placed"}
    assert "polymarket_us" in adapter.attempts[0].subject
    assert "alpaca" in adapter.attempts[1].subject


def test_req_not_006_05_dry_run_execution_does_not_send_trade_email() -> None:
    """TST-REQ-NOT-006-05: Validates REQ-NOT-006 and REQ-EXE-016

    Given: dry-run execution records simulated intents
    When: a notification adapter is configured
    Then: no trade-placed email is sent because no actual order was submitted
    """
    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    adapter = InMemorySesEmailAdapter()

    result = PipelineLifecycleService(
        registry,
        notification_adapter=adapter,
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-dry-email",
        trigger="manual",
        strategy_run=_strategy_run_with_outputs(registry, now),
        market_data_pulls=_market_data_pulls(now),
        config_payload={
            **_config(live_enabled=False),
            "notifications": {
                "recipients": {"yaw": "yaw@example.com"},
                "email_on_trade_placed": True,
            },
        },
        started_at=now,
        completed_at=now,
    )

    assert result.payload["simulatedCount"] == 2
    assert adapter.sent_count == 0


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


def test_req_ext_006_01_live_exit_submits_through_configured_venue_submitters() -> None:
    """TST-REQ-EXT-006-01: Validates REQ-EXT-006

    Given: live mode and open Polymarket and Alpaca positions
    When: exit monitoring triggers exits
    Then: Polymarket closes the position and Alpaca submits a sell quantity
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
    alpaca = RecordingAlpacaSubmitter()
    polymarket = RecordingPolymarketSubmitter()

    result = PipelineLifecycleService(
        registry,
        alpaca_exit_submitter=alpaca,
        polymarket_position_closer=polymarket,
    ).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-live-exit",
        trigger="manual",
        market_data_pulls=_market_data_pulls(now, include_alpaca=False),
        config_payload=_config(live_enabled=True),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["submittedCount"] == result.payload["triggeredCount"]
    assert polymarket.close_calls[0]["market_slug"] == "market-1"
    assert polymarket.close_calls[0]["bips"] == "200"
    assert alpaca.calls[0]["symbol"] == "SPY"
    assert alpaca.calls[0]["side"] == "sell"
    assert alpaca.calls[0]["quantity"] == "1"


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
