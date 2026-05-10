"""Comparison analytics helpers.

REQ: REQ-CMP-002, REQ-CMP-004
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain import ComparisonMetric, Environment, InstrumentType, ModelProvider, Venue


@dataclass(frozen=True)
class ComparisonGroup:
    """Grouping dimensions for comparison metrics.

    REQ: REQ-CMP-002
    """

    model_provider: ModelProvider
    venue: Venue
    environment: Environment
    instrument_type: InstrumentType


@dataclass(frozen=True)
class PerformanceRecord:
    """Aggregatable model and venue performance input.

    REQ: REQ-CMP-002
    """

    group: ComparisonGroup
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    model_cost: Decimal
    open_exposure: Decimal
    wins: int
    losses: int
    max_drawdown: Decimal


@dataclass(frozen=True)
class ComparisonSummary:
    """Dashboard-ready comparison metric collection.

    REQ: REQ-CMP-002, REQ-CMP-004
    """

    metrics: tuple[ComparisonMetric, ...]

    def metric_for(
        self,
        model_provider: ModelProvider,
        venue: Venue,
        metric_name: str,
        *,
        environment: Environment | None = None,
        instrument_type: InstrumentType | None = None,
    ) -> ComparisonMetric:
        """Return the first metric matching the requested dimensions.

        REQ: REQ-CMP-002, REQ-CMP-004
        """

        for metric in self.metrics:
            if metric.model_provider != model_provider:
                continue
            if metric.venue != venue or metric.metric_name != metric_name:
                continue
            if environment is not None and metric.environment != environment:
                continue
            if instrument_type is not None and metric.instrument_type != instrument_type:
                continue
            return metric
        raise KeyError((model_provider, venue, metric_name))


def compare_model_performance(
    records: tuple[PerformanceRecord, ...],
    *,
    expected_groups: tuple[ComparisonGroup, ...] = (),
) -> ComparisonSummary:
    """Aggregate model performance across Polymarket and Alpaca groups.

    REQ: REQ-CMP-002, REQ-CMP-004
    """

    grouped: dict[ComparisonGroup, list[PerformanceRecord]] = {}
    for record in records:
        grouped.setdefault(record.group, []).append(record)

    metrics: list[ComparisonMetric] = []
    for group, group_records in grouped.items():
        metrics.extend(_metrics_for_group(group, group_records))

    for group in expected_groups:
        if group not in grouped:
            metrics.append(
                mark_comparison_metric_unavailable(
                    group,
                    "realized_pnl",
                    "no eligible data",
                )
            )

    return ComparisonSummary(metrics=tuple(metrics))


def mark_comparison_metric_unavailable(
    group: ComparisonGroup,
    metric_name: str,
    reason: str,
) -> ComparisonMetric:
    """Build an unavailable metric marker instead of returning zero.

    REQ: REQ-CMP-004
    """

    return ComparisonMetric(
        metric_name=metric_name,
        model_provider=group.model_provider,
        venue=group.venue,
        environment=group.environment,
        instrument_type=group.instrument_type,
        unavailable_reason=reason,
    )


def _metrics_for_group(
    group: ComparisonGroup,
    records: list[PerformanceRecord],
) -> tuple[ComparisonMetric, ...]:
    realized = sum((_as_decimal(record.realized_pnl) for record in records), Decimal("0"))
    unrealized = sum((_as_decimal(record.unrealized_pnl) for record in records), Decimal("0"))
    model_cost = sum((_as_decimal(record.model_cost) for record in records), Decimal("0"))
    exposure = sum((_as_decimal(record.open_exposure) for record in records), Decimal("0"))
    wins = sum(record.wins for record in records)
    losses = sum(record.losses for record in records)
    trade_count = wins + losses
    max_drawdown = min((_as_decimal(record.max_drawdown) for record in records), default=Decimal("0"))

    metrics = [
        _metric(group, "realized_pnl", realized),
        _metric(group, "unrealized_pnl", unrealized),
        _metric(group, "model_cost", model_cost),
        _metric(group, "open_exposure", exposure),
        _metric(group, "trade_count", Decimal(trade_count)),
        _metric(group, "max_drawdown", max_drawdown),
    ]
    if trade_count == 0:
        metrics.append(mark_comparison_metric_unavailable(group, "win_rate", "no closed trades"))
    else:
        metrics.append(_metric(group, "win_rate", Decimal(wins) / Decimal(trade_count)))
    if max_drawdown == 0:
        metrics.append(mark_comparison_metric_unavailable(group, "return_to_risk", "drawdown is zero"))
    else:
        metrics.append(_metric(group, "return_to_risk", realized / abs(max_drawdown)))
    return tuple(metrics)


def _metric(group: ComparisonGroup, metric_name: str, value: Decimal) -> ComparisonMetric:
    return ComparisonMetric(
        metric_name=metric_name,
        model_provider=group.model_provider,
        venue=group.venue,
        environment=group.environment,
        instrument_type=group.instrument_type,
        value=value,
    )


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
