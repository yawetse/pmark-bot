"""Red-phase tests for Cross-Market Comparison Analytics."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain import (
    ComparisonMetric,
    Environment,
    InstrumentType,
    ModelProvider,
    Venue,
    calculate_return_to_risk,
    metric_group_key,
)
from app.services import (
    ComparisonGroup,
    PerformanceRecord,
    compare_model_performance,
    mark_comparison_metric_unavailable,
)


def test_req_cmp_001_01_trades_positions_across_providers_venues_environments_instrument_types() -> None:
    """TST-REQ-CMP-001-01: Validates REQ-CMP-001

    Given: trades and positions across providers, venues, environments, and instrument types
    When: metrics are calculated
    Then: results are grouped by those dimensions
    """
    metric = ComparisonMetric(
        metric_name="realized_pnl",
        model_provider=ModelProvider.CLAUDE,
        venue=Venue.ALPACA,
        environment=Environment.DEVELOPMENT,
        instrument_type=InstrumentType.ETF,
        value="12.5",
    )

    assert metric_group_key(metric) == (
        ModelProvider.CLAUDE,
        Venue.ALPACA,
        Environment.DEVELOPMENT,
        InstrumentType.ETF,
    )


def test_req_cmp_001_02_records_missing_grouping_dimensions_metrics_calculated_invalid_records() -> None:
    """TST-REQ-CMP-001-02: Validates REQ-CMP-001

    Given: records missing grouping dimensions
    When: metrics are calculated
    Then: invalid records are excluded or marked unavailable with a reason
    """
    with pytest.raises(ValidationError):
        ComparisonMetric(
            metric_name="realized_pnl",
            model_provider=ModelProvider.CLAUDE,
            environment=Environment.DEVELOPMENT,
            instrument_type=InstrumentType.ETF,
            value="12.5",
        )

def test_req_cmp_002_01_claude_openai_performance_data_polymarket_alpaca_comparison_runs() -> None:
    """TST-REQ-CMP-002-01: Validates REQ-CMP-002

    Given: Claude and OpenAI performance data for Polymarket and Alpaca
    When: comparison runs
    Then: model performance is compared across both markets
    """
    summary = compare_model_performance(
        (
            PerformanceRecord(
                group=ComparisonGroup(
                    ModelProvider.CLAUDE,
                    Venue.POLYMARKET_US,
                    Environment.DEVELOPMENT,
                    InstrumentType.PREDICTION_MARKET,
                ),
                realized_pnl=Decimal("12"),
                unrealized_pnl=Decimal("3"),
                model_cost=Decimal("1.5"),
                open_exposure=Decimal("20"),
                wins=2,
                losses=1,
                max_drawdown=Decimal("-4"),
            ),
            PerformanceRecord(
                group=ComparisonGroup(
                    ModelProvider.OPENAI,
                    Venue.ALPACA,
                    Environment.DEVELOPMENT,
                    InstrumentType.ETF,
                ),
                realized_pnl=Decimal("8"),
                unrealized_pnl=Decimal("2"),
                model_cost=Decimal("1"),
                open_exposure=Decimal("50"),
                wins=1,
                losses=1,
                max_drawdown=Decimal("-5"),
            ),
        )
    )

    assert summary.metric_for(
        ModelProvider.CLAUDE,
        Venue.POLYMARKET_US,
        "realized_pnl",
    ).value == Decimal("12")
    assert summary.metric_for(ModelProvider.OPENAI, Venue.ALPACA, "trade_count").value == Decimal("2")

def test_req_cmp_002_02_one_market_no_eligible_data_comparison_runs_missing() -> None:
    """TST-REQ-CMP-002-02: Validates REQ-CMP-002

    Given: one market has no eligible data
    When: comparison runs
    Then: the missing market is marked unavailable without blocking other comparisons
    """
    expected_alpaca = ComparisonGroup(
        ModelProvider.OPENAI,
        Venue.ALPACA,
        Environment.DEVELOPMENT,
        InstrumentType.ETF,
    )
    summary = compare_model_performance(
        (
            PerformanceRecord(
                group=ComparisonGroup(
                    ModelProvider.CLAUDE,
                    Venue.POLYMARKET_US,
                    Environment.DEVELOPMENT,
                    InstrumentType.PREDICTION_MARKET,
                ),
                realized_pnl=Decimal("12"),
                unrealized_pnl=Decimal("3"),
                model_cost=Decimal("1.5"),
                open_exposure=Decimal("20"),
                wins=2,
                losses=1,
                max_drawdown=Decimal("-4"),
            ),
        ),
        expected_groups=(expected_alpaca,),
    )

    metric = summary.metric_for(ModelProvider.OPENAI, Venue.ALPACA, "realized_pnl")

    assert metric.value is None
    assert metric.unavailable_reason == "no eligible data"
    assert summary.metric_for(ModelProvider.CLAUDE, Venue.POLYMARKET_US, "realized_pnl").value == Decimal("12")

def test_req_cmp_003_01_complete_trade_position_model_cost_data_comparison_metrics() -> None:
    """TST-REQ-CMP-003-01: Validates REQ-CMP-003

    Given: complete trade, position, and model cost data
    When: comparison metrics are calculated
    Then: documented formulas produce realized P&L, unrealized P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk
    """
    metric = calculate_return_to_risk(
        model_provider=ModelProvider.OPENAI,
        venue=Venue.POLYMARKET_US,
        environment=Environment.LOCAL,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        total_return="20",
        max_drawdown="-5",
    )

    assert metric.value == Decimal("4")
    assert metric.unavailable_reason is None

def test_req_cmp_003_02_divide_zero_missing_input_documented_formula_metrics_calculated() -> None:
    """TST-REQ-CMP-003-02: Validates REQ-CMP-003

    Given: divide-by-zero or missing input for a documented formula
    When: metrics are calculated
    Then: the metric is unavailable rather than invalid
    """
    metric = calculate_return_to_risk(
        model_provider=ModelProvider.OPENAI,
        venue=Venue.POLYMARKET_US,
        environment=Environment.LOCAL,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        total_return="20",
        max_drawdown="0",
    )

    assert metric.value is None
    assert metric.unavailable_reason == "drawdown is zero"

def test_req_cmp_004_01_insufficient_data_metric_dashboard_api_comparison_output_produced() -> None:
    """TST-REQ-CMP-004-01: Validates REQ-CMP-004

    Given: insufficient data for a metric
    When: dashboard or API comparison output is produced
    Then: the metric value is unavailable rather than zero
    """
    metric = mark_comparison_metric_unavailable(
        ComparisonGroup(
            ModelProvider.OPENAI,
            Venue.POLYMARKET_US,
            Environment.DEVELOPMENT,
            InstrumentType.PREDICTION_MARKET,
        ),
        "win_rate",
        "insufficient closed trades",
    )

    assert metric.value is None
    assert metric.unavailable_reason == "insufficient closed trades"
