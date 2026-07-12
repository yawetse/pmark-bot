"""Red-phase tests for Postgres Persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
import httpx
from pydantic import ValidationError

import app.db.session as db_session_module
from app.db import (
    DatabaseState,
    PersistenceConfigurationError,
    PersistenceUnavailableError,
    RepositoryRegistry,
    SHARED_CONFIG_USERNAME,
    SchemaViolationError,
    UnitOfWork,
    create_session_factory,
    live_order_persistence_gate,
    migration_plan,
    retention_policy,
)
from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderSide,
    OrderType,
    PositionState,
    PositionTransition,
    StrategySignal,
    TradeDecision,
    Venue,
)
from app.services.ai_usage_import_service import (
    AiUsageImportService,
    ProviderBackedAiUsageImportSource,
    ProviderUsageRow,
    StaticAiUsageImportSource,
)
from tests.spec.helpers import pending


def prediction_instrument() -> Instrument:
    return Instrument(
        venue=Venue.POLYMARKET_US,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id="market-1",
        outcome_id="yes",
        display_name="Will the event happen?",
    )


def test_req_db_001_01_live_dry_run_position_events_persistence_runs_both() -> None:
    """TST-REQ-DB-001-01: Validates REQ-DB-001

    Given: live and dry-run position events
    When: persistence runs
    Then: both position types are stored in Postgres
    """
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.OPENAI)
    live_transition = PositionTransition(
        position_id="live-pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="2.25",
        unrealized_pnl="0",
        reason="live exit",
    )
    dry_run_transition = PositionTransition(
        position_id="dry-pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.EXITING,
        realized_pnl="0",
        unrealized_pnl="1.50",
        reason="dry-run exit check",
    )

    repository.record_position_event(
        live_transition,
        execution_mode="live",
        idempotency_key="live-event-1",
    )
    repository.record_position_event(
        dry_run_transition,
        execution_mode="dry_run",
        idempotency_key="dry-event-1",
    )

    rows = registry.state.rows("openai.position_events")
    assert {row["execution_mode"] for row in rows} == {"live", "dry_run"}
    assert {row["position_id"] for row in rows} == {"live-pos-1", "dry-pos-1"}

def test_req_db_001_02_duplicate_position_events_same_idempotency_key_persistence_runs() -> None:
    """TST-REQ-DB-001-02: Validates REQ-DB-001

    Given: duplicate position events with the same idempotency key
    When: persistence runs
    Then: the system avoids duplicate position rows
    """
    registry = RepositoryRegistry()
    repository = registry.for_model(ModelProvider.OPENAI)
    transition = PositionTransition(
        position_id="pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="1.00",
        unrealized_pnl="0",
        reason="closed once",
    )

    first = repository.record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="idem-1",
    )
    second = repository.record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="idem-1",
    )

    assert second == first
    assert len(registry.state.rows("openai.position_events")) == 1

def test_req_db_002_01_claude_openai_records_migrations_repositories_run_each_model() -> None:
    """TST-REQ-DB-002-01: Validates REQ-DB-002

    Given: Claude and OpenAI records
    When: migrations and repositories run
    Then: each model provider uses its separate schema
    """
    plan = migration_plan()
    registry = RepositoryRegistry()

    assert plan.schema_names == ("shared", "claude", "openai")
    assert "claude.trade_decisions" in plan.table_names
    assert "openai.trade_decisions" in plan.table_names
    assert "openai.alpaca_reconciliation_mismatches" in plan.table_names
    assert "shared.job_runs" in plan.table_names
    assert "shared.comparison_metric_snapshots" in plan.table_names
    assert "shared.economics_snapshots" in plan.table_names
    assert "shared.ai_usage_import_runs" in plan.table_names
    assert "shared.pipeline_runs" in plan.table_names
    assert "shared.pipeline_steps" in plan.table_names
    assert "shared.tick_summaries" in plan.table_names
    assert "shared.scanner_runs" in plan.table_names
    assert "shared.scanner_candidates" in plan.table_names
    assert "shared.reasoning_runs" in plan.table_names
    assert "shared.reasoning_outputs" in plan.table_names
    assert "shared.strategy_consensus_runs" in plan.table_names
    assert "shared.strategy_votes" in plan.table_names
    assert "shared.strategy_consensus_outputs" in plan.table_names
    assert "shared.execution_runs" in plan.table_names
    assert "shared.order_intents" in plan.table_names
    assert "shared.exit_runs" in plan.table_names
    assert "shared.exit_intents" in plan.table_names
    assert "shared.polymarket_gamma_markets" in plan.table_names
    assert "shared.polymarket_chain_fill_events" in plan.table_names
    assert "shared.polymarket_trades" in plan.table_names
    assert "shared.polymarket_wallet_positions" in plan.table_names
    assert "shared.polymarket_wallet_performance_stats" in plan.table_names
    assert "shared.polymarket_target_wallet_snapshots" in plan.table_names
    assert "shared.historical_import_checkpoints" in plan.table_names
    assert "shared.alpaca_symbol_preset_snapshots" in plan.table_names
    assert "shared.alpaca_historical_orders" in plan.table_names
    assert "shared.alpaca_historical_fills" in plan.table_names
    assert "shared.alpaca_historical_positions" in plan.table_names
    assert "shared.alpaca_broker_account_snapshots" in plan.table_names
    assert "shared.stock_bars" in plan.table_names
    assert "shared.alpaca_symbol_pnl_snapshots" in plan.table_names
    assert "openai.order_intents" in plan.table_names
    assert "openai.strategy_signals" in plan.table_names
    assert all("..." not in statement for statement in plan.sql)
    assert any("CREATE TABLE IF NOT EXISTS openai.trade_decisions" in statement for statement in plan.sql)
    assert registry.for_model(ModelProvider.CLAUDE).schema_name == "claude"
    assert registry.for_model(ModelProvider.OPENAI).schema_name == "openai"

def test_req_db_002_02_repository_attempts_write_model_record_wrong_schema_validation() -> None:
    """TST-REQ-DB-002-02: Validates REQ-DB-002

    Given: a repository attempts to write a model record to the wrong schema
    When: validation runs
    Then: the write is rejected
    """
    registry = RepositoryRegistry()

    with pytest.raises(SchemaViolationError):
        registry.for_model(ModelProvider.OPENAI).ensure_schema("claude")

def test_req_db_003_01_shared_config_audit_system_health_records_persistence_runs() -> None:
    """TST-REQ-DB-003-01: Validates REQ-DB-003

    Given: shared config, audit, and system health records
    When: persistence runs
    Then: shared records are stored in the shared schema
    """
    registry = RepositoryRegistry()
    shared = registry.shared()

    shared.record_config_version(
        environment=Environment.DEVELOPMENT,
        version="v1",
        payload={"global_execution_mode": "dry_run"},
    )
    shared.record_audit_event(
        event_type="config_change",
        actor="yaw",
        action="risk_limit.update",
        environment=Environment.DEVELOPMENT,
        metadata={"max_position": "25"},
    )
    shared.record_system_health(component="postgres", status="healthy")

    config_rows = registry.state.rows("shared.config_versions")
    assert len(config_rows) == 1
    assert config_rows[0]["username"] == SHARED_CONFIG_USERNAME
    assert len(registry.state.rows("shared.audit_events")) == 1
    assert len(registry.state.rows("shared.system_health")) == 1

def test_req_db_003_03_shared_economics_snapshots_persist_monthly_history() -> None:
    """TST-REQ-DB-003-03: Validates REQ-DB-003 and REQ-UI-010

    Given: profitability snapshots for two months
    When: monthly economics history is read
    Then: only the selected month's stored ROI data is returned
    """
    registry = RepositoryRegistry()
    shared = registry.shared()

    shared.record_economics_snapshot(
        environment=Environment.DEVELOPMENT,
        month_key="2026-05",
        trading_realized_pnl_usd=Decimal("4.00"),
        trading_unrealized_pnl_usd=Decimal("1.00"),
        trading_total_pnl_usd=Decimal("5.00"),
        ai_cost_usd=Decimal("0.20"),
        ai_prompt_tokens=100,
        ai_completion_tokens=40,
        ai_total_tokens=140,
        aws_daily_cost_usd=Decimal("1.00"),
        aws_month_to_date_cost_usd=Decimal("30.00"),
        aws_source="user preference fallback",
        aws_scope="fallback",
        aws_estimated=True,
        net_after_costs_usd=Decimal("3.80"),
        profitability_status="profitable",
        payload={"month": "2026-05"},
        created_at=datetime(2026, 5, 31, tzinfo=UTC),
    )
    shared.record_economics_snapshot(
        environment=Environment.DEVELOPMENT,
        month_key="2026-06",
        trading_realized_pnl_usd=Decimal("12.50"),
        trading_unrealized_pnl_usd=Decimal("1.25"),
        trading_total_pnl_usd=Decimal("13.75"),
        ai_cost_usd=Decimal("0.45"),
        ai_prompt_tokens=1200,
        ai_completion_tokens=300,
        ai_total_tokens=1500,
        aws_daily_cost_usd=Decimal("1.00"),
        aws_month_to_date_cost_usd=Decimal("30.00"),
        aws_source="user preference fallback",
        aws_scope="fallback",
        aws_estimated=True,
        net_after_costs_usd=Decimal("12.30"),
        profitability_status="profitable",
        payload={"month": "2026-06"},
        created_at=datetime(2026, 6, 25, tzinfo=UTC),
    )

    rows = shared.economics_snapshots(
        environment=Environment.DEVELOPMENT,
        month_key="2026-06",
    )

    assert len(rows) == 1
    assert rows[0]["month_key"] == "2026-06"
    assert rows[0]["ai_total_tokens"] == 1500
    assert rows[0]["aws_month_to_date_cost_usd"] == Decimal("30.00")
    assert rows[0]["net_after_costs_usd"] == Decimal("12.30")


def test_req_db_003_09_shared_ai_usage_import_rows_keep_provider_attribution() -> None:
    """TST-REQ-DB-003-09: Validates REQ-DB-003, REQ-LLM-002, and REQ-UI-010

    Given: provider-side token usage rows exist
    When: the usage import service stores them
    Then: dashboard economics can separate source, model, run, step, and candidate attribution
    """

    registry = RepositoryRegistry()
    observed = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
    service = AiUsageImportService(
        registry,
        source=StaticAiUsageImportSource(
            rows=(
                ProviderUsageRow(
                    provider=ModelProvider.OPENAI,
                    model="gpt-5-mini",
                    prompt_tokens=100,
                    completion_tokens=40,
                    cost_usd=Decimal("0.12"),
                    observed_at=observed,
                    response_id="resp-1",
                    pipeline_run_id="run-1",
                    pipeline_step="brain",
                    candidate_id="candidate-1",
                    cost_source="provider usage export",
                    raw_payload={"id": "resp-1"},
                ),
            )
        ),
    )

    result = service.import_provider_usage(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        period_start=datetime(2026, 6, 25, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
        triggered_by="yaw",
    )
    usage_rows = registry.shared().ai_usage_events(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
    )
    import_rows = registry.shared().ai_usage_import_runs(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["importedCount"] == 1
    assert usage_rows[0]["model"] == "gpt-5-mini"
    assert usage_rows[0]["pipeline_run_id"] == "run-1"
    assert usage_rows[0]["pipeline_step"] == "brain"
    assert usage_rows[0]["candidate_id"] == "candidate-1"
    assert usage_rows[0]["usage_source"] == "provider_backfill"
    assert usage_rows[0]["cost_source"] == "provider usage export"
    assert usage_rows[0]["response_id"] == "resp-1"
    assert import_rows[0]["status"] == "completed"
    assert import_rows[0]["imported_count"] == 1


def test_req_db_003_10_openai_admin_usage_import_fetches_provider_rows() -> None:
    """TST-REQ-DB-003-10: Validates REQ-LLM-002 and REQ-UI-010

    Given: an OpenAI admin usage source is configured
    When: usage and cost endpoints return bucketed rows
    Then: provider token and cost rows are persisted for dashboard profitability
    """

    registry = RepositoryRegistry()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/organization/usage/completions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1_782_345_600,
                            "results": [
                                {
                                    "model": "gpt-5-mini",
                                    "input_tokens": 120,
                                    "output_tokens": 30,
                                }
                            ],
                        }
                    ]
                },
            )
        if request.url.path.endswith("/organization/costs"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "start_time": 1_782_345_600,
                            "results": [
                                {
                                    "line_item": "gpt-5-mini",
                                    "amount": {"value": "0.42", "currency": "usd"},
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"error": "not found"})

    service = AiUsageImportService(
        registry,
        source=ProviderBackedAiUsageImportSource(
            {"OPENAI_ADMIN_API_KEY": "admin-test-key"},
            transport=httpx.MockTransport(handler),
        ),
    )

    result = service.import_provider_usage(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
        period_start=datetime(2026, 6, 20, tzinfo=UTC),
        period_end=datetime(2026, 6, 25, tzinfo=UTC),
        triggered_by="yaw",
    )
    rows = registry.shared().ai_usage_events(
        environment=Environment.DEVELOPMENT,
        provider=ModelProvider.OPENAI,
    )

    assert result.payload["status"] == "completed"
    assert result.payload["source"] == "provider admin usage api"
    assert result.payload["importedCount"] == 2
    assert rows[0]["prompt_tokens"] == 120
    assert rows[0]["completion_tokens"] == 30
    assert rows[0]["cost_source"] == "openai organization usage endpoint"
    assert rows[1]["cost_usd"] == Decimal("0.42")
    assert rows[1]["cost_source"] == "openai organization costs endpoint"

def test_req_db_003_04_shared_polymarket_history_records_persist_for_step_zero() -> None:
    """TST-REQ-DB-003-04: Validates REQ-DB-003 and REQ-DAT-009

    Given: Polymarket historical market, fill, trade, wallet, and checkpoint rows
    When: the shared repositories persist the records
    Then: Step 0 historical data can be read back for downstream scanner work
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)

    market = shared.record_polymarket_gamma_market(
        environment=Environment.DEVELOPMENT,
        market_id="market-1",
        condition_id="0xcondition",
        question="Will BTC close above 100k?",
        active=False,
        closed=True,
        tokens=[{"token_id": "yes-token", "outcome": "YES"}],
        tags=["crypto"],
        raw_payload={"id": "market-1"},
        fetched_at=observed,
    )
    fill = shared.record_polymarket_chain_fill_event(
        environment=Environment.DEVELOPMENT,
        exchange_contract="0xexchange",
        block_number=123,
        log_index=4,
        transaction_hash="0xtx",
        maker_address="0xABCDEF0000000000000000000000000000000001",
        asset_id="yes-token",
        market_id="market-1",
        raw_event={"event": "OrderFilled"},
        block_timestamp=observed,
    )
    trade = shared.record_polymarket_trade(
        environment=Environment.DEVELOPMENT,
        market_id="market-1",
        condition_id="0xcondition",
        asset_id="yes-token",
        wallet_address="0xABCDEF0000000000000000000000000000000001",
        side="BUY",
        price=Decimal("0.42"),
        size=Decimal("10"),
        notional_usd=Decimal("4.20"),
        realized_pnl_usd=Decimal("1.25"),
        outcome="YES",
        role="maker",
        transaction_hash="0xtx",
        block_number=123,
        raw_event_id=fill["id"],
        market_record_id=market["id"],
        traded_at=observed,
    )
    shared.record_polymarket_wallet_position(
        environment=Environment.DEVELOPMENT,
        wallet_address=trade["wallet_address"],
        market_id="market-1",
        asset_id="yes-token",
        state="closed",
        size=Decimal("10"),
        realized_pnl_usd=Decimal("1.25"),
        entry_price=Decimal("0.42"),
        exit_price=Decimal("0.55"),
        trade_ids=[trade["id"]],
        opened_at=observed,
        closed_at=observed,
    )
    stat = shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address=trade["wallet_address"],
        trade_count=125,
        win_rate=Decimal("0.74"),
        total_realized_pnl_usd=Decimal("212.50"),
        average_hold_seconds=3600,
        source="fixture",
        calculated_at=observed,
    )
    snapshot = shared.record_polymarket_target_wallet_snapshot(
        environment=Environment.DEVELOPMENT,
        min_trade_count=100,
        min_win_rate=Decimal("0.70"),
        wallets=[{"walletAddress": stat["wallet_address"]}],
        source_stat_ids=[stat["id"]],
        created_at=observed,
    )
    checkpoint = shared.upsert_historical_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="polygon_order_filled",
        cursor_type="block_number",
        cursor_value="123",
        status="stored",
        metadata={"window": "120-123"},
        last_success_at=observed,
    )

    assert len(shared.polymarket_gamma_markets(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.polymarket_chain_fill_events(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.polymarket_trades(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.polymarket_wallet_performance_stats(environment=Environment.DEVELOPMENT)) == 1
    assert snapshot["wallet_count"] == 1
    assert checkpoint["cursor_value"] == "123"

def test_req_db_003_05_shared_alpaca_history_records_persist_for_step_zero() -> None:
    """TST-REQ-DB-003-05: Validates REQ-DB-003, REQ-ALP-017, and REQ-DAT-008

    Given: Alpaca order, fill, position, account, bar, P&L, and checkpoint rows
    When: the shared repositories persist the stock broker history
    Then: Step 0 stock data can be read back for scanner and profitability work
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 14, 0, tzinfo=UTC)

    order = shared.record_alpaca_historical_order(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        order_id="order-1",
        symbol="spy",
        side="buy",
        order_type="market",
        status="filled",
        quantity=Decimal("2"),
        filled_quantity=Decimal("2"),
        filled_avg_price=Decimal("500"),
        raw_payload={"id": "order-1"},
        submitted_at=observed,
    )
    fill = shared.record_alpaca_historical_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        activity_id="fill-1",
        order_id=order["order_id"],
        symbol="SPY",
        side="buy",
        quantity=Decimal("2"),
        price=Decimal("500"),
        filled_at=observed,
        raw_payload={"id": "fill-1"},
    )
    position = shared.record_alpaca_historical_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        quantity=Decimal("1"),
        average_entry_price=Decimal("500"),
        market_value=Decimal("505"),
        current_price=Decimal("505"),
        unrealized_pnl_usd=Decimal("5"),
        raw_payload={"symbol": "SPY"},
        observed_at=observed,
    )
    shared.record_alpaca_broker_account_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        account_status="ACTIVE",
        buying_power=Decimal("1000"),
        raw_payload={"id": "acct-1"},
        observed_at=observed,
    )
    shared.record_stock_bar(
        environment=Environment.DEVELOPMENT,
        symbol="SPY",
        timeframe="1Day",
        bar_start_at=observed,
        open_price=Decimal("500"),
        high_price=Decimal("506"),
        low_price=Decimal("499"),
        close_price=Decimal("505"),
        volume=Decimal("1000000"),
        source="alpaca market data api",
        raw_payload={"t": observed.isoformat()},
    )
    pnl = shared.record_alpaca_symbol_pnl_snapshot(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        symbol="SPY",
        open_quantity=Decimal("1"),
        average_entry_price=Decimal("500"),
        realized_pnl_usd=Decimal("0"),
        unrealized_pnl_usd=Decimal("5"),
        total_pnl_usd=Decimal("5"),
        cost_basis=Decimal("500"),
        market_value=Decimal("505"),
        fill_ids=[fill["id"]],
        position_id=position["id"],
        calculated_at=observed,
    )
    shared.upsert_historical_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="alpaca_broker_history:paper",
        cursor_type="timestamp",
        cursor_value=observed.isoformat(),
        status="stored",
    )
    preset = shared.record_alpaca_symbol_preset_snapshot(
        environment=Environment.DEVELOPMENT,
        preset_name="sp500",
        status="refreshed",
        source="html_table",
        source_url="https://example.test/sp500",
        symbols=["AAPL", "MSFT"],
        effective_at=observed,
        refreshed_at=observed,
        message="refreshed fixture",
    )

    assert len(shared.alpaca_historical_orders(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_historical_fills(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_historical_positions(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_broker_account_snapshots(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.stock_bars(environment=Environment.DEVELOPMENT)) == 1
    assert shared.alpaca_symbol_preset_snapshots(environment=Environment.DEVELOPMENT)[0]["id"] == preset["id"]
    assert shared.alpaca_symbol_pnl_snapshots(environment=Environment.DEVELOPMENT)[0]["id"] == pnl["id"]

def test_req_db_003_06_shared_scanner_records_persist_for_phase_two() -> None:
    """TST-REQ-DB-003-06: Validates REQ-DB-003 and REQ-STR-003

    Given: a scanner run and accepted/rejected candidates
    When: the shared repositories persist scanner records
    Then: Phase 2 scanner output can be read back separately from raw market pulls
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    run = shared.record_scanner_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        status="completed",
        config={"polymarket": {"min_depth": "500"}},
        source_pull_ids=["pull-1"],
        accepted_count=1,
        rejected_count=1,
        started_at=observed,
        completed_at=observed,
    )
    accepted = shared.record_scanner_candidate(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=run["id"],
        venue=Venue.POLYMARKET_US.value,
        instrument_id="condition-1:yes-token",
        display_name="Will rates fall? - Yes",
        market_id="condition-1",
        outcome_id="yes-token",
        status="accepted",
        strategy_names=["order_book_depth"],
        price=Decimal("0.45"),
        liquidity=Decimal("1250"),
        spread=Decimal("0.02"),
        hours_to_resolution=Decimal("24"),
        metrics={"bidDepth": "600"},
        source_payload={"id": "candidate-1"},
        created_at=observed,
    )
    shared.record_scanner_candidate(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=run["id"],
        venue=Venue.ALPACA.value,
        instrument_id="alpaca:XYZ",
        display_name="XYZ",
        symbol="XYZ",
        status="rejected",
        refusal_reason="symbol outside universe",
        strategy_names=[],
        metrics={},
        source_payload={"symbol": "XYZ"},
        created_at=observed,
    )

    assert shared.scanner_runs(environment=Environment.DEVELOPMENT)[0]["id"] == run["id"]
    candidates = shared.scanner_candidates(environment=Environment.DEVELOPMENT)
    assert len(candidates) == 2
    assert shared.scanner_candidates(
        environment=Environment.DEVELOPMENT,
        scanner_run_id=run["id"],
        status="accepted",
    )[0]["id"] == accepted["id"]


def test_req_db_003_07_shared_reasoning_records_persist_for_phase_three() -> None:
    """TST-REQ-DB-003-07: Validates REQ-DB-003 and REQ-LLM-003

    Given: a reasoning run and scored output
    When: the shared repositories persist reasoning records
    Then: Phase 3 prompt, response, signal, and token fields can be read back
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    run = shared.record_reasoning_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        scanner_run_id="scanner-1",
        trigger="manual",
        status="completed",
        config={"polymarket": {"prompt_version": "pm-brain-v1"}},
        provider_count=1,
        prompt_count=1,
        scored_count=1,
        skipped_count=0,
        failed_count=0,
        started_at=observed,
        completed_at=observed,
    )
    output = shared.record_reasoning_output(
        environment=Environment.DEVELOPMENT,
        reasoning_run_id=run["id"],
        scanner_candidate_id="candidate-1",
        venue=Venue.POLYMARKET_US.value,
        instrument_id="condition-1:yes-token",
        model_provider=ModelProvider.OPENAI,
        prompt_version="pm-brain-v1",
        status="scored",
        directional_signal="buy_yes",
        signal_strength=Decimal("0.15"),
        confidence=Decimal("0.80"),
        estimated_probability=Decimal("0.60"),
        output_thesis="base rate and disposition support yes",
        cost_usd=Decimal("0.01"),
        prompt_tokens=120,
        completion_tokens=40,
        prompt_payload={"checks": ["base_rate"]},
        response_payload={"estimated_probability": "0.60"},
        check_results=[{"name": "base_rate", "status": "prompted"}],
        created_at=observed,
    )

    assert shared.reasoning_runs(environment=Environment.DEVELOPMENT)[0]["id"] == run["id"]
    outputs = shared.reasoning_outputs(environment=Environment.DEVELOPMENT)
    assert outputs[0]["id"] == output["id"]
    assert outputs[0]["total_tokens"] == 160
    assert shared.reasoning_outputs(
        environment=Environment.DEVELOPMENT,
        reasoning_run_id=run["id"],
        model_provider=ModelProvider.OPENAI,
        status="scored",
    )[0]["directional_signal"] == "buy_yes"


def test_req_db_003_08_shared_strategy_consensus_records_persist_for_phase_four() -> None:
    """TST-REQ-DB-003-08: Validates REQ-DB-003, REQ-STR-007, and REQ-STR-008

    Given: strategy votes and consensus output
    When: the shared repositories persist Phase 4 rows
    Then: votes and approved consensus can be read back for dashboard runs
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    run = shared.record_strategy_consensus_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        reasoning_run_id="reasoning-1",
        trigger="manual",
        status="approved",
        config={"consensus_rule": "default"},
        vote_count=2,
        approved_count=1,
        refused_count=0,
        started_at=observed,
        completed_at=observed,
    )
    vote = shared.record_strategy_vote(
        environment=Environment.DEVELOPMENT,
        consensus_run_id=run["id"],
        reasoning_output_id="reasoning-output-1",
        scanner_candidate_id="candidate-1",
        venue=Venue.POLYMARKET_US.value,
        instrument_id="condition-1:yes-token",
        model_provider=ModelProvider.OPENAI,
        strategy_name="convergence",
        direction=OrderSide.BUY.value,
        confidence=Decimal("0.80"),
        status="accepted",
        inputs_hash="convergence-inputs",
        source_payload={"candidate": "condition-1"},
        created_at=observed,
    )
    output = shared.record_strategy_consensus_output(
        environment=Environment.DEVELOPMENT,
        consensus_run_id=run["id"],
        venue=Venue.POLYMARKET_US.value,
        instrument_id="condition-1:yes-token",
        model_provider=ModelProvider.OPENAI,
        status="approved",
        side=OrderSide.BUY.value,
        size_multiplier=Decimal("0.50"),
        signal_count=1,
        strategy_names=["convergence"],
        source_payload={"vote_ids": [vote["id"]]},
        created_at=observed,
    )
    signal = StrategySignal(
        strategy_name="convergence",
        model_provider=ModelProvider.OPENAI,
        instrument=prediction_instrument(),
        direction=OrderSide.BUY,
        confidence=Decimal("0.80"),
        inputs_hash="convergence-inputs",
    )
    registry.for_model(ModelProvider.OPENAI).record_strategy_signal(signal)

    assert shared.strategy_consensus_runs(environment=Environment.DEVELOPMENT)[0]["id"] == run["id"]
    assert shared.strategy_votes(
        environment=Environment.DEVELOPMENT,
        consensus_run_id=run["id"],
        status="accepted",
    )[0]["id"] == vote["id"]
    assert shared.strategy_consensus_outputs(
        environment=Environment.DEVELOPMENT,
        consensus_run_id=run["id"],
        model_provider=ModelProvider.OPENAI,
        status="approved",
    )[0]["id"] == output["id"]
    assert registry.state.rows("openai.strategy_signals")[0]["strategy_name"] == "convergence"


def test_req_db_003_09_shared_execution_and_exit_records_persist_for_phase_five_six() -> None:
    """TST-REQ-DB-003-09: Validates REQ-DB-003, REQ-EXE-016, and REQ-EXT-005

    Given: execution and exit lifecycle records
    When: the shared repositories persist order and exit intents
    Then: idempotency keys keep retries on the same durable record
    """
    registry = RepositoryRegistry()
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    execution_run = shared.record_execution_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        strategy_consensus_run_id="consensus-1",
        trigger="manual",
        status="completed",
        config={"order_type": "market"},
        intent_count=1,
        submitted_count=0,
        simulated_count=1,
        refused_count=0,
        reconciliation_count=0,
        started_at=observed,
        completed_at=observed,
    )
    order_intent = shared.record_order_intent(
        environment=Environment.DEVELOPMENT,
        execution_run_id=execution_run["id"],
        pipeline_run_id="pipeline-1",
        strategy_consensus_output_id="consensus-output-1",
        venue=Venue.ALPACA.value,
        instrument_id="alpaca:SPY",
        model_provider=ModelProvider.CLAUDE,
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        status="pending",
        notional_usd=Decimal("50"),
        size_multiplier=Decimal("0.5"),
        idempotency_key="entry-key",
        risk_payload={"approved": True},
        source_payload={"symbol": "SPY"},
        created_at=observed,
        updated_at=observed,
    )
    updated_order_intent = shared.record_order_intent(
        environment=Environment.DEVELOPMENT,
        execution_run_id=execution_run["id"],
        pipeline_run_id="pipeline-1",
        strategy_consensus_output_id="consensus-output-1",
        venue=Venue.ALPACA.value,
        instrument_id="alpaca:SPY",
        model_provider=ModelProvider.CLAUDE,
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        status="simulated",
        notional_usd=Decimal("50"),
        size_multiplier=Decimal("0.5"),
        idempotency_key="entry-key",
        risk_payload={"approved": True},
        source_payload={"symbol": "SPY"},
        created_at=observed,
        updated_at=observed,
    )
    exit_run = shared.record_exit_run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-1",
        trigger="manual",
        status="completed",
        config={"alpaca": {"profit_target_pct": "0.08"}},
        open_position_count=1,
        triggered_count=1,
        simulated_count=1,
        submitted_count=0,
        refused_count=0,
        started_at=observed,
        completed_at=observed,
    )
    exit_intent = shared.record_exit_intent(
        environment=Environment.DEVELOPMENT,
        exit_run_id=exit_run["id"],
        pipeline_run_id="pipeline-1",
        venue=Venue.ALPACA.value,
        instrument_id="alpaca:SPY",
        position_id="position-1",
        model_provider=ModelProvider.CLAUDE,
        trigger_type="profit_target",
        status="simulated",
        side=OrderSide.SELL.value,
        quantity=Decimal("1"),
        notional_usd=Decimal("110"),
        threshold=Decimal("0.08"),
        observed_value=Decimal("0.10"),
        idempotency_key="exit-key",
        source_payload={"symbol": "SPY"},
        created_at=observed,
        updated_at=observed,
    )

    assert order_intent["id"] == updated_order_intent["id"]
    assert updated_order_intent["status"] == "simulated"
    assert shared.execution_runs(environment=Environment.DEVELOPMENT)[0]["id"] == execution_run["id"]
    assert shared.order_intents(environment=Environment.DEVELOPMENT)[0]["id"] == order_intent["id"]
    assert shared.exit_runs(environment=Environment.DEVELOPMENT)[0]["id"] == exit_run["id"]
    assert shared.exit_intents(environment=Environment.DEVELOPMENT)[0]["id"] == exit_intent["id"]


def test_req_db_003_02_shared_record_routed_model_schema_repository_validation_runs() -> None:
    """TST-REQ-DB-003-02: Validates REQ-DB-003

    Given: a shared record is routed to a model schema
    When: repository validation runs
    Then: the write is rejected
    """
    registry = RepositoryRegistry()

    with pytest.raises(SchemaViolationError):
        registry.shared().ensure_schema("openai")

def test_req_db_004_01_trade_decision_all_required_fields_persistence_runs_provider() -> None:
    """TST-REQ-DB-004-01: Validates REQ-DB-004

    Given: a trade decision with all required fields
    When: persistence runs
    Then: provider, venue, environment, instrument, signal, decision, order type, size, and timestamp are saved
    """
    decision = TradeDecision(
        model_provider=ModelProvider.OPENAI,
        venue=Venue.POLYMARKET_US,
        environment=Environment.LOCAL,
        instrument=prediction_instrument(),
        signal_inputs={"strategy_signal_ids": ["signal-1"], "confidence": "0.72"},
        decision="buy",
        order_type=OrderType.LIMIT,
        size=Decimal("12.50"),
    )

    row = RepositoryRegistry().for_model(ModelProvider.OPENAI).record_trade_decision(decision)

    assert row["model_provider"] == ModelProvider.OPENAI.value
    assert row["venue"] == Venue.POLYMARKET_US.value
    assert row["environment"] == Environment.LOCAL.value
    assert row["instrument_identifier"] == "market-1:yes"
    assert row["signal_inputs"]["strategy_signal_ids"] == ["signal-1"]
    assert row["decision"] == "buy"
    assert row["order_type"] == OrderType.LIMIT.value
    assert row["size"] == Decimal("12.50")
    assert row["created_at"] is not None

def test_req_db_004_02_trade_decision_missing_required_field_persistence_runs_write() -> None:
    """TST-REQ-DB-004-02: Validates REQ-DB-004

    Given: a trade decision missing a required field
    When: persistence runs
    Then: the write fails and the omission is reported
    """
    with pytest.raises(ValidationError):
        TradeDecision(
            model_provider=ModelProvider.OPENAI,
            venue=Venue.POLYMARKET_US,
            environment=Environment.LOCAL,
            instrument=prediction_instrument(),
            signal_inputs={},
            decision="buy",
            order_type=OrderType.LIMIT,
            size=Decimal("12.50"),
        )
    with pytest.raises(ValidationError):
        TradeDecision(
            model_provider=ModelProvider.OPENAI,
            venue=Venue.POLYMARKET_US,
            environment=Environment.LOCAL,
            instrument=prediction_instrument(),
            signal_inputs={"strategy_signal_ids": ["signal-1"]},
            decision="buy",
            order_type=OrderType.LIMIT,
            size=Decimal("12.50"),
            misspelled_field="ignored would be unsafe",
        )

def test_req_db_005_01_position_state_transition_persistence_runs_prior_state_new() -> None:
    """TST-REQ-DB-005-01: Validates REQ-DB-005

    Given: a position state transition
    When: persistence runs
    Then: prior state, new state, realized P&L, unrealized P&L, and reason are stored
    """
    transition = PositionTransition(
        position_id="pos-1",
        prior_state=PositionState.OPEN,
        new_state=PositionState.CLOSED,
        realized_pnl="4.25",
        unrealized_pnl="0",
        reason="profit target reached",
    )
    registry = RepositoryRegistry()

    row = registry.for_model(ModelProvider.OPENAI).record_position_event(
        transition,
        execution_mode="live",
        idempotency_key="pos-event-1",
    )
    position = registry.state.rows("openai.positions")[0]

    assert row["prior_state"] == PositionState.OPEN.value
    assert row["new_state"] == PositionState.CLOSED.value
    assert row["realized_pnl"] == Decimal("4.25")
    assert row["unrealized_pnl"] == Decimal("0")
    assert row["reason"] == "profit target reached"
    assert position["state"] == PositionState.CLOSED.value

def test_req_db_005_02_invalid_position_state_transition_persistence_runs_transition_rejected() -> None:
    """TST-REQ-DB-005-02: Validates REQ-DB-005

    Given: an invalid position state transition
    When: persistence runs
    Then: the transition is rejected and prior state remains intact
    """
    with pytest.raises(ValidationError):
        PositionTransition(
            position_id="pos-1",
            prior_state=PositionState.OPEN,
            new_state=PositionState.OPEN,
            realized_pnl="0",
            unrealized_pnl="1.25",
            reason="no state change",
        )

def test_req_db_006_01_no_later_archive_policy_configured_retention_settings_validated() -> None:
    """TST-REQ-DB-006-01: Validates REQ-DB-006

    Given: no later archive policy is configured
    When: retention settings are validated
    Then: audit, trade, and position history have no automatic deletion
    """
    policy = retention_policy()

    assert policy.audit_delete_after_days is None
    assert policy.trade_delete_after_days is None
    assert policy.position_delete_after_days is None

def test_req_db_007_01_postgres_available_live_order_checks_require_persistence_persistence() -> None:
    """TST-REQ-DB-007-01: Validates REQ-DB-007

    Given: Postgres is available
    When: live order checks require persistence
    Then: persistence health passes
    """
    state = DatabaseState(available=True)
    gate = live_order_persistence_gate(state)
    session_factory = create_session_factory("postgresql+psycopg://user:pass@localhost:5432/codex_poly_bot")

    with UnitOfWork(state) as unit:
        unit.commit()

    assert gate.live_order_allowed
    assert not gate.degraded
    assert gate.system_health is not None
    assert gate.system_health["status"] == "healthy"
    assert session_factory.kw["expire_on_commit"] is False

def test_req_db_007_03_bare_postgres_dsn_uses_packaged_psycopg_driver() -> None:
    """TST-REQ-DB-007-03: Validates REQ-DB-007

    Given: a deployed bare Postgres DSN
    When: the SQLAlchemy session factory initializes
    Then: the installed psycopg driver is selected instead of psycopg2
    """
    session_factory = create_session_factory("postgresql://user:pass@localhost:5432/codex_poly_bot")

    assert session_factory.kw["bind"].url.drivername == "postgresql+psycopg"

def test_req_db_007_04_postgres_session_factory_bounds_connection_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """TST-REQ-DB-007-04: Validates REQ-DB-007

    Given: production Postgres is temporarily slow to accept connections
    When: the SQLAlchemy session factory initializes
    Then: connection and pool waits are bounded so scheduler ticks can fail fast
    """
    captured: dict[str, object] = {}

    def fake_create_engine(url: object, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs

        class FakeEngine:
            def __init__(self, engine_url: object) -> None:
                self.url = engine_url

        return FakeEngine(url)

    monkeypatch.setattr(db_session_module, "create_engine", fake_create_engine)

    session_factory = db_session_module.create_session_factory(
        "postgresql://user:pass@localhost:5432/codex_poly_bot"
    )

    assert session_factory.kw["bind"].url.drivername == "postgresql+psycopg"
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "pool_timeout": db_session_module.DEFAULT_POOL_TIMEOUT_SECONDS,
        "connect_args": {"connect_timeout": db_session_module.DEFAULT_CONNECT_TIMEOUT_SECONDS},
    }

def test_req_db_007_02_postgres_unavailable_live_order_placement_requested_order_blocked() -> None:
    """TST-REQ-DB-007-02: Validates REQ-DB-007

    Given: Postgres is unavailable
    When: live order placement is requested
    Then: the order is blocked and logs plus dashboard status surface the failure
    """
    state = DatabaseState(available=False)
    gate = live_order_persistence_gate(state)

    assert not gate.live_order_allowed
    assert gate.degraded
    assert gate.reason == "Postgres persistence is unavailable"
    assert gate.system_health is not None
    assert gate.system_health["status"] == "degraded"
    assert gate.log_event is not None
    assert gate.log_event["event_name"] == "postgres.persistence.unavailable"
    with pytest.raises(PersistenceUnavailableError):
        with UnitOfWork(state):
            pass
    with pytest.raises(PersistenceConfigurationError):
        create_session_factory("sqlite:///local.db")
