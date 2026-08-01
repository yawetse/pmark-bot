"""Spec tests for Phase 5 execution and Phase 6 exits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.adapters.aws import InMemorySesEmailAdapter
from app.db import AlpacaReconciliationSnapshot, RepositoryRegistry
from app.domain import Environment, ModelProvider, OrderSide, OrderType, PositionState, Venue
from app.services import NotificationDeliveryLedger, PipelineLifecycleService
from app.services.lifecycle_service import _slippage_ok
from app.venues import PolymarketLiveOrderRequest, VenueCallResult, build_polymarket_order_payload


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
        position_intent: str | None = None,
        estimated_unit_price: Decimal | None = None,
        expected_account_id: str | None = None,
        entry_cutoff_minutes: int | None = None,
        max_quote_age_seconds: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "account_mode": account_mode,
                "symbol": symbol,
                "notional": str(notional) if notional is not None else "",
                "quantity": str(quantity) if quantity is not None else "",
                "side": side,
                "position_intent": position_intent or "",
                "estimated_unit_price": str(estimated_unit_price or ""),
                "expected_account_id": expected_account_id or "",
                "entry_cutoff_minutes": str(entry_cutoff_minutes or ""),
                "max_quote_age_seconds": str(max_quote_age_seconds or ""),
                "client_order_id": client_order_id or "",
            }
        )
        return f"alpaca-{side}-{symbol}-{len(self.calls)}"


class FailingAlpacaSubmitter(RecordingAlpacaSubmitter):
    def submit_order(self, **kwargs: object) -> str:
        self.calls.append({key: str(value) for key, value in kwargs.items()})
        raise RuntimeError("broker rejected exact fractional cover")


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
    assert polymarket.submit_calls[0].quantity is None
    assert polymarket.submit_calls[0].cash_order_qty == Decimal("25.00000000")
    market_payload = build_polymarket_order_payload(polymarket.submit_calls[0])
    assert market_payload.ok
    assert "quantity" not in market_payload.payload["order_payload"]
    assert market_payload.payload["order_payload"]["cashOrderQty"] == {
        "value": "25.00000000",
        "currency": "USD",
    }
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


def test_req_exe_016_10_alpaca_entry_refuses_outside_regular_market_hours() -> None:
    """The day-trading profile must not queue market orders overnight."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 2, 0, tzinfo=UTC)
    alpaca = RecordingAlpacaSubmitter()
    result = PipelineLifecycleService(registry, alpaca_submitter=alpaca).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-after-hours",
        trigger="scheduled",
        strategy_run=_strategy_run_with_outputs(registry, now, include_polymarket=False),
        market_data_pulls=_market_data_pulls(now, include_polymarket=False),
        config_payload=_config(live_enabled=True),
        credential_status={Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["refusedCount"] == 1
    assert "OUTSIDE_MARKET_HOURS" in result.payload["intents"][0]["refusalReason"]
    assert alpaca.calls == []


def test_req_exe_016_11_alpaca_daily_loss_ignores_prior_days() -> None:
    """A prior-day realized loss must not permanently block new stock entries."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="old-buy",
        symbol="QQQ",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("300"),
        filled_at=now - timedelta(days=2),
        raw_payload={"side": "long"},
    )
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="old-sell",
        symbol="QQQ",
        side="sell",
        quantity=Decimal("1"),
        price=Decimal("150"),
        filled_at=now - timedelta(days=1),
        raw_payload={"side": "long"},
    )
    alpaca = RecordingAlpacaSubmitter()
    result = PipelineLifecycleService(registry, alpaca_submitter=alpaca).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-new-day",
        trigger="scheduled",
        strategy_run=_strategy_run_with_outputs(registry, now, include_polymarket=False),
        market_data_pulls=_market_data_pulls(now, include_polymarket=False),
        config_payload=_config(live_enabled=True),
        credential_status={Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert len(alpaca.calls) == 1


def test_req_exe_016_12_alpaca_uses_saved_open_position_limit() -> None:
    """Saved Alpaca risk limits must control the live entry gate."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    registry.shared().record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="QQQ",
        quantity=Decimal("1"),
        average_entry_price=Decimal("300"),
        current_price=Decimal("301"),
        market_value=Decimal("301"),
        unrealized_pnl_usd=Decimal("1"),
        raw_payload={},
        observed_at=now,
    )
    config = _config(live_enabled=True)
    config["risk"]["alpaca"]["max_open_positions"] = 1
    alpaca = RecordingAlpacaSubmitter()
    result = PipelineLifecycleService(registry, alpaca_submitter=alpaca).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-position-limit",
        trigger="scheduled",
        strategy_run=_strategy_run_with_outputs(registry, now, include_polymarket=False),
        market_data_pulls=_market_data_pulls(now, include_polymarket=False),
        config_payload=config,
        credential_status={Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["refusedCount"] == 1
    assert "OPEN_POSITION_LIMIT" in result.payload["intents"][0]["refusalReason"]
    assert alpaca.calls == []


def test_req_exe_016_13_alpaca_risk_uses_selected_account_mode() -> None:
    """A live-account snapshot must not block a paper-account entry."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    registry.shared().record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="live",
        account_id="acct-live",
        symbol="QQQ",
        quantity=Decimal("1"),
        average_entry_price=Decimal("300"),
        current_price=Decimal("301"),
        market_value=Decimal("301"),
        unrealized_pnl_usd=Decimal("1"),
        raw_payload={},
        observed_at=now,
    )
    config = _config(live_enabled=True)
    config["risk"]["alpaca"]["max_open_positions"] = 1
    alpaca = RecordingAlpacaSubmitter()
    result = PipelineLifecycleService(registry, alpaca_submitter=alpaca).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-account-mode",
        trigger="scheduled",
        strategy_run=_strategy_run_with_outputs(registry, now, include_polymarket=False),
        market_data_pulls=_market_data_pulls(now, include_polymarket=False),
        config_payload=config,
        credential_status={Venue.ALPACA.value: True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert len(alpaca.calls) == 1


def test_req_exe_016_14_alpaca_slippage_uses_spread_percentage() -> None:
    """A stock spread is normalized by share price before applying the percentage limit."""

    config = _config(live_enabled=True)
    assert _slippage_ok(
        venue=Venue.ALPACA.value,
        candidate={"price": "500.00", "spread": "1.00"},
        config_payload=config,
    )
    assert not _slippage_ok(
        venue=Venue.ALPACA.value,
        candidate={"price": "500.00", "spread": "3.00"},
        config_payload=config,
    )


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
        raw_payload={"side": "long", "high_watermark_price": "115"},
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
    assert result.payload["triggeredCount"] == 2
    assert result.payload["simulatedCount"] == result.payload["triggeredCount"]
    assert {intent["venue"] for intent in result.payload["intents"]} == {
        Venue.POLYMARKET_US.value,
        Venue.ALPACA.value,
    }
    assert len(registry.state.rows("shared.exit_intents")) == result.payload["triggeredCount"]


def test_req_ext_001_04_stock_position_closes_before_regular_market_close() -> None:
    """The active stock profile should avoid carrying an intraday position overnight."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 19, 50, tzinfo=UTC)
    shared = registry.shared()
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-close-window",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=1),
        raw_payload={"side": "long"},
    )
    shared.record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        current_price=Decimal("100.20"),
        market_value=Decimal("100.20"),
        unrealized_pnl_usd=Decimal("0.20"),
        raw_payload={
            "side": "long",
            "market_clock": {
                "is_open": True,
                "timestamp": now.isoformat(),
                "next_close": (now + timedelta(minutes=10)).isoformat(),
            },
        },
        observed_at=now,
    )

    result = PipelineLifecycleService(registry).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-close-window",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )

    close_intents = [
        intent
        for intent in result.payload["intents"]
        if intent["triggerType"] == "market_hours"
    ]
    assert len(close_intents) == 1
    assert close_intents[0]["status"] == "simulated"


def test_req_ext_001_05_stock_exit_submits_one_order_when_multiple_rules_match() -> None:
    """A full stock position must produce at most one sell order per exit run."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 19, 50, tzinfo=UTC)
    shared = registry.shared()
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-multi-trigger",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=1),
        raw_payload={"side": "long"},
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
        raw_payload={"side": "long"},
        observed_at=now,
    )
    alpaca = RecordingAlpacaSubmitter()

    result = PipelineLifecycleService(
        registry,
        alpaca_exit_submitter=alpaca,
    ).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-one-exit",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=_config(live_enabled=True),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["triggeredCount"] == 1
    assert result.payload["submittedCount"] == 1
    assert result.payload["intents"][0]["triggerType"] == "profit_target"
    assert len(alpaca.calls) == 1


def test_req_ext_001_06_submitted_stock_exit_is_not_resubmitted_for_same_position() -> None:
    """A still-open position reuses its submitted exit instead of placing another sell."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-idempotent-exit",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=1),
        raw_payload={},
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
        raw_payload={"side": "long"},
        observed_at=now,
    )
    alpaca = RecordingAlpacaSubmitter()
    service = PipelineLifecycleService(registry, alpaca_exit_submitter=alpaca)

    first = service.run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-exit-first",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=_config(live_enabled=True),
        started_at=now,
        completed_at=now,
    )
    second = service.run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-exit-second",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=_config(live_enabled=True),
        started_at=now + timedelta(minutes=1),
        completed_at=now + timedelta(minutes=1),
    )

    assert first.payload["submittedCount"] == 1
    assert second.payload["submittedCount"] == 1
    assert len(alpaca.calls) == 1
    assert len(registry.state.rows("shared.exit_intents")) == 1
    assert registry.state.rows("shared.exit_intents")[0]["source_payload"][
        "reusedSubmittedExit"
    ] is True


def test_req_ext_001_07_stock_trailing_stop_uses_recorded_position_high_watermark() -> None:
    """The trailing stop should work without a nonstandard broker payload field."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-trailing-stop",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=1),
        raw_payload={},
    )
    for current_price, observed_at in (
        (Decimal("110"), now - timedelta(minutes=30)),
        (Decimal("104.30"), now),
    ):
        shared.record_alpaca_historical_position(
            environment=Environment.DEVELOPMENT,
            account_mode="paper",
            account_id="acct-1",
            symbol="SPY",
            quantity=Decimal("1"),
            average_entry_price=Decimal("100"),
            current_price=current_price,
            market_value=current_price,
            unrealized_pnl_usd=current_price - Decimal("100"),
            raw_payload={"side": "long"},
            observed_at=observed_at,
        )

    result = PipelineLifecycleService(registry).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-trailing-stop",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=_config(live_enabled=False),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["triggeredCount"] == 1
    assert result.payload["intents"][0]["triggerType"] == "trailing_stop"


def test_req_ext_001_08_stock_open_time_resets_after_a_closed_position() -> None:
    """A new position must not inherit the age of an older round trip."""

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    for activity_id, side, filled_at in (
        ("old-buy", "buy", now - timedelta(days=2)),
        ("old-sell", "sell", now - timedelta(days=1)),
        ("new-buy", "buy", now - timedelta(hours=1)),
    ):
        shared.record_alpaca_historical_fill(
            environment=Environment.DEVELOPMENT,
            account_mode="paper",
            account_id="acct-1",
            activity_id=activity_id,
            symbol="SPY",
            side=side,
            quantity=Decimal("1"),
            price=Decimal("100"),
            filled_at=filled_at,
            raw_payload={},
        )

    opened_at = PipelineLifecycleService(registry)._stock_opened_at(
        Environment.DEVELOPMENT,
        "SPY",
        account_mode="paper",
        account_id="acct-1",
    )

    assert opened_at == now - timedelta(hours=1)


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
        raw_payload={"side": "long", "high_watermark_price": "115"},
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


def test_req_alp_019_022_short_entry_requires_gate_and_uses_whole_share_intent() -> None:
    registry = RepositoryRegistry()
    now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.register_alpaca_account(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        model_provider=ModelProvider.CLAUDE,
        account_id="claude-paper-account",
    )
    registry.for_model(ModelProvider.CLAUDE).record_alpaca_account_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        snapshot=AlpacaReconciliationSnapshot(
            account_id="claude-paper-account",
            positions={},
            open_orders=(),
            buying_power=Decimal("1000"),
            environment=Environment.DEVELOPMENT,
            model_provider=ModelProvider.CLAUDE,
            account_mode="paper",
            configured_account_id="claude-paper-account",
            broker_account_id="claude-paper-account",
            account_status="active",
            observed_at=now,
            is_live_safe=True,
        ),
    )
    run = shared.record_strategy_consensus_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-short-entry",
        reasoning_run_id="reasoning-short-entry",
        trigger="manual",
        status="approved",
        config={},
        vote_count=1,
        approved_count=1,
        refused_count=0,
        started_at=now,
        completed_at=now,
    )
    output = shared.record_strategy_consensus_output(
        environment=Environment.DEVELOPMENT,
        consensus_run_id=run["id"],
        venue=Venue.ALPACA.value,
        instrument_id="alpaca:F",
        model_provider=ModelProvider.CLAUDE,
        status="approved",
        side=OrderSide.SELL.value,
        size_multiplier=Decimal("1"),
        signal_count=1,
        strategy_names=["momentum"],
        source_payload={"candidate": {"symbol": "F"}},
        created_at=now,
    )
    strategy_run = {"id": run["id"], "outputs": [output], "status": "approved"}
    market_data = [{
        "id": "pull-short",
        "venue": Venue.ALPACA.value,
        "status": "pulled",
        "createdAt": now.isoformat(),
        "candidates": [{
            "id": "alpaca:F",
            "venue": Venue.ALPACA.value,
            "symbol": "F",
            "price": "12.50",
            "spread": "0.01",
            "pulledAt": now.isoformat(),
        }],
    }]
    config = _config(live_enabled=True)
    config["alpaca"]["allow_shorting"] = True
    submitter = RecordingAlpacaSubmitter()

    result = PipelineLifecycleService(
        registry,
        alpaca_submitters={ModelProvider.CLAUDE: submitter},
    ).run_execution(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-short-entry",
        trigger="manual",
        strategy_run=strategy_run,
        market_data_pulls=market_data,
        config_payload=config,
        credential_status={f"{Venue.ALPACA.value}:{ModelProvider.CLAUDE.value}": True},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert submitter.calls[0]["side"] == "sell"
    assert submitter.calls[0]["quantity"] == "7"
    assert submitter.calls[0]["notional"] == ""
    assert submitter.calls[0]["position_intent"] == "sell_to_open"


def test_req_alp_022_short_entry_requires_fresh_safe_reconciliation() -> None:
    registry = RepositoryRegistry()
    now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.register_alpaca_account(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        model_provider=ModelProvider.CLAUDE,
        account_id="claude-paper-account",
    )
    service = PipelineLifecycleService(registry)

    missing = service._alpaca_reconciliation_refusal(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        model_provider=ModelProvider.CLAUDE,
        now=now,
        max_freshness_seconds=300,
    )
    registry.for_model(ModelProvider.CLAUDE).record_alpaca_account_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        snapshot=AlpacaReconciliationSnapshot(
            account_id="claude-paper-account",
            positions={},
            open_orders=(),
            buying_power=Decimal("1000"),
            observed_at=now,
            is_live_safe=False,
        ),
    )
    blocked = service._alpaca_reconciliation_refusal(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        model_provider=ModelProvider.CLAUDE,
        now=now,
        max_freshness_seconds=300,
    )

    assert missing == "ALPACA_RECONCILIATION_REQUIRED"
    assert blocked == "ALPACA_RECONCILIATION_BLOCKED"


def test_req_alp_016_duplicate_account_quarantine_blocks_original_provider_route() -> None:
    registry = RepositoryRegistry()
    shared = registry.shared()
    shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.OPENAI,
        account_id="shared-live-account",
    )
    shared.register_alpaca_account(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.CLAUDE,
        account_id="shared-live-account",
    )

    submitter = RecordingAlpacaSubmitter()
    service = PipelineLifecycleService(registry, alpaca_submitter=submitter)
    config = _config(live_enabled=True)
    config["alpaca"]["account_mode"] = "live"
    account_id = service._alpaca_account_id(
        environment=Environment.PRODUCTION,
        account_mode="live",
        model_provider=ModelProvider.OPENAI,
    )
    execution = service._execute_entry_order(
        environment=Environment.PRODUCTION,
        venue=Venue.ALPACA.value,
        model_provider=ModelProvider.OPENAI,
        side="buy",
        order_type="market",
        instrument_id="alpaca:SPY",
        notional=Decimal("100"),
        idempotency_key="quarantined-long-entry",
        output={},
        candidate={"symbol": "SPY", "price": "100"},
        config_payload=config,
        position_intent="buy_to_open",
        expected_account_id=None,
    )

    assert account_id == ""
    assert execution["refusal_reason"] == "ALPACA_ACCOUNT_QUARANTINED"
    assert submitter.calls == []


def test_req_alp_023_025_026_short_exit_is_exact_and_provider_routed() -> None:
    registry = RepositoryRegistry()
    now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    shared = registry.shared()
    shared.register_alpaca_account(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        model_provider=ModelProvider.CLAUDE,
        account_id="claude-paper-account",
    )
    shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="claude-paper-account",
        activity_id="short-fill",
        symbol="F",
        side="sell",
        quantity=Decimal("1.25"),
        price=Decimal("100"),
        filled_at=now - timedelta(hours=1),
        raw_payload={},
    )
    shared.record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="claude-paper-account",
        symbol="F",
        quantity=Decimal("-1.25"),
        average_entry_price=Decimal("100"),
        current_price=Decimal("90"),
        market_value=Decimal("-112.50"),
        unrealized_pnl_usd=Decimal("12.50"),
        raw_payload={"side": "short"},
        observed_at=now,
    )
    openai_submitter = RecordingAlpacaSubmitter()
    claude_submitter = RecordingAlpacaSubmitter()
    config = _config(live_enabled=True)
    config["alpaca"]["allow_shorting"] = False

    result = PipelineLifecycleService(
        registry,
        alpaca_exit_submitter=openai_submitter,
        alpaca_submitters={
            ModelProvider.OPENAI: openai_submitter,
            ModelProvider.CLAUDE: claude_submitter,
        },
    ).run_exit(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-short-exit",
        trigger="scheduled",
        market_data_pulls=[],
        config_payload=config,
        started_at=now,
        completed_at=now,
    )

    assert result.payload["submittedCount"] == 1
    assert openai_submitter.calls == []
    assert claude_submitter.calls[0]["side"] == "buy"
    assert claude_submitter.calls[0]["quantity"] == "1.25"
    assert claude_submitter.calls[0]["position_intent"] == "buy_to_close"
    assert claude_submitter.calls[0]["expected_account_id"] == "claude-paper-account"
    assert registry.state.rows("openai.order_events") == []
    assert registry.state.rows("claude.order_events")[0]["event_type"] == "submitted"
    exit_intent = registry.state.rows("shared.exit_intents")[0]
    assert exit_intent["side"] == "buy"
    assert exit_intent["source_payload"]["modelProvider"] == "claude"


def test_req_alp_025_fractional_cover_failure_requires_operator_action() -> None:
    service = PipelineLifecycleService(
        RepositoryRegistry(),
        alpaca_exit_submitter=FailingAlpacaSubmitter(),
    )

    result = service._execute_exit_order(  # noqa: SLF001 - specification boundary
        position={
            "position_id": "short-fractional",
            "venue": Venue.ALPACA.value,
            "instrument_id": "alpaca:F",
            "symbol": "F",
            "quantity": Decimal("1.25"),
            "position_side": "short",
            "model_provider": ModelProvider.CLAUDE,
            "routing_resolved": True,
            "account_mode": "paper",
            "account_ref": "claude-paper-account",
        },
        venue=Venue.ALPACA.value,
        execution_mode="live",
        risk_approved=True,
        refusal_reason=None,
        config_payload=_config(live_enabled=True),
        idempotency_key="exact-cover",
    )

    assert result.status == "refused"
    assert result.refusal_reason == "ALPACA_EXACT_COVER_UNAVAILABLE"
    assert result.payload["operator_action_required"] is True


def test_req_alp_026_short_exit_refuses_disabled_venue_and_unresolved_routing() -> None:
    for registered, venue_enabled, expected_reason in (
        (True, False, "ALPACA_VENUE_DISABLED"),
        (False, True, "ALPACA_EXIT_ACCOUNT_UNRESOLVED"),
    ):
        registry = RepositoryRegistry()
        now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
        shared = registry.shared()
        if registered:
            shared.register_alpaca_account(
                environment=Environment.DEVELOPMENT,
                account_mode="paper",
                model_provider=ModelProvider.CLAUDE,
                account_id="claude-paper-account",
            )
        shared.record_alpaca_historical_fill(
            environment=Environment.DEVELOPMENT,
            account_mode="paper",
            account_id="claude-paper-account",
            activity_id=f"short-{registered}",
            symbol="F",
            side="sell",
            quantity=Decimal("1"),
            price=Decimal("100"),
            filled_at=now - timedelta(hours=1),
            raw_payload={"side": "sell"},
        )
        shared.record_alpaca_historical_position(
            environment=Environment.DEVELOPMENT,
            account_mode="paper",
            account_id="claude-paper-account",
            symbol="F",
            quantity=Decimal("-1"),
            average_entry_price=Decimal("100"),
            current_price=Decimal("90"),
            market_value=Decimal("-90"),
            unrealized_pnl_usd=Decimal("10"),
            raw_payload={"side": "short"},
            observed_at=now,
        )
        openai_submitter = RecordingAlpacaSubmitter()
        claude_submitter = RecordingAlpacaSubmitter()
        config = _config(live_enabled=True)
        config["venues"][Venue.ALPACA.value]["enabled"] = venue_enabled

        result = PipelineLifecycleService(
            registry,
            alpaca_submitters={
                ModelProvider.OPENAI: openai_submitter,
                ModelProvider.CLAUDE: claude_submitter,
            },
        ).run_exit(
            environment=Environment.DEVELOPMENT,
            pipeline_run_id=f"pipeline-short-refusal-{registered}",
            trigger="scheduled",
            market_data_pulls=[],
            config_payload=config,
            started_at=now,
            completed_at=now,
        )

        assert result.payload["refusedCount"] == 1
        assert result.payload["intents"][0]["refusalReason"] == expected_reason
        assert openai_submitter.calls == []
        assert claude_submitter.calls == []


def _strategy_run_with_outputs(
    registry: RepositoryRegistry,
    now: datetime,
    *,
    include_alpaca: bool = True,
    include_polymarket: bool = True,
) -> dict:
    shared = registry.shared()
    run = shared.record_strategy_consensus_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        reasoning_run_id="reasoning-1",
        trigger="manual",
        status="approved",
        config={},
        vote_count=int(include_polymarket) + int(include_alpaca),
        approved_count=int(include_polymarket) + int(include_alpaca),
        refused_count=0,
        started_at=now,
        completed_at=now,
    )
    outputs = []
    if include_polymarket:
        outputs.append(shared.record_strategy_consensus_output(
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
        ))
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
    include_polymarket: bool = True,
) -> list[dict]:
    pulls = []
    if include_polymarket:
        pulls.append({
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
        })
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
