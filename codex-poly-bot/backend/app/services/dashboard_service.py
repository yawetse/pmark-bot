"""Dashboard view-model helpers.

REQ: REQ-UI-001, REQ-UI-004, REQ-UI-009, REQ-UI-010, REQ-UI-011
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain import ModelProvider
from app.services.comparison_service import (
    ComparisonGroup,
    ComparisonSummary,
    PerformanceRecord,
    compare_model_performance,
)
from app.services.wallet_service import CredentialStatus


@dataclass(frozen=True)
class DashboardShellResult:
    """Dashboard shell load result.

    REQ: REQ-UI-001
    """

    status_code: int
    data_source: str | None
    public_message: str
    degraded_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class DashboardStatusResult:
    """Dashboard status section view model.

    REQ: REQ-UI-004
    """

    sections: dict[str, dict[str, Any]]
    visible_sections: tuple[str, ...]
    degraded_sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelProviderSummary:
    """Provider-specific model dashboard summary.

    REQ: REQ-UI-010
    """

    model_provider: ModelProvider
    positions: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    budget_usd: Decimal = Decimal("0")
    pnl: Decimal = Decimal("0")


@dataclass(frozen=True)
class ComparisonDashboardView:
    """Dashboard comparison view with degraded section markers.

    REQ: REQ-UI-011
    """

    metrics: tuple[Any, ...]
    degraded_sections: tuple[str, ...] = ()


REQUIRED_STATUS_SECTIONS = (
    "venue",
    "model",
    "wallet",
    "ingestion",
    "loop",
    "position",
    "order",
    "notification",
)


def build_dashboard_shell(
    *,
    backend_available: bool,
    frontend_available: bool,
    backend_error: str | None = None,
) -> DashboardShellResult:
    """Return a Next.js dashboard shell backed by FastAPI status.

    REQ: REQ-UI-001
    """

    if not frontend_available:
        return DashboardShellResult(
            status_code=503,
            data_source=None,
            public_message="dashboard frontend unavailable",
            degraded_sections=("frontend",),
        )
    if not backend_available:
        return DashboardShellResult(
            status_code=503,
            data_source=None,
            public_message="dashboard API unavailable",
            degraded_sections=("api",),
        )
    return DashboardShellResult(
        status_code=200,
        data_source="fastapi",
        public_message="dashboard ready",
    )


def build_dashboard_status(sources: dict[str, Any]) -> DashboardStatusResult:
    """Build dashboard status sections and mark unavailable sources degraded.

    REQ: REQ-UI-004
    """

    sections: dict[str, dict[str, Any]] = {}
    degraded: list[str] = []
    for section in REQUIRED_STATUS_SECTIONS:
        value = sources.get(section)
        if value is None:
            sections[section] = {"status": "degraded", "data": None}
            degraded.append(section)
            continue
        sections[section] = {"status": "ok", "data": value}
    return DashboardStatusResult(
        sections=sections,
        visible_sections=REQUIRED_STATUS_SECTIONS,
        degraded_sections=tuple(degraded),
    )


def render_wallet_dashboard_status(status: CredentialStatus) -> dict[str, Any]:
    """Return wallet status without private credential values.

    REQ: REQ-UI-009
    """

    return status.dashboard_payload()


def build_model_provider_summary(
    *,
    records: tuple[dict[str, Any], ...],
    budgets: dict[ModelProvider, Decimal],
    provider: ModelProvider,
) -> ModelProviderSummary:
    """Build provider-specific positions, decisions, budget, and P&L.

    REQ: REQ-UI-010
    """

    provider_records = tuple(record for record in records if record.get("model_provider") == provider)
    positions = tuple(
        str(record["position_id"])
        for record in provider_records
        if record.get("position_id") is not None
    )
    decisions = tuple(
        str(record["decision_id"])
        for record in provider_records
        if record.get("decision_id") is not None
    )
    pnl = sum((_as_decimal(record.get("pnl", Decimal("0"))) for record in provider_records), Decimal("0"))
    return ModelProviderSummary(
        model_provider=provider,
        positions=positions,
        decisions=decisions,
        budget_usd=_as_decimal(budgets.get(provider, Decimal("0"))),
        pnl=pnl,
    )


def build_comparison_dashboard_view(
    records: tuple[PerformanceRecord, ...],
    *,
    expected_groups: tuple[ComparisonGroup, ...] = (),
) -> ComparisonDashboardView:
    """Build comparison metrics for dashboard rendering.

    REQ: REQ-UI-011
    """

    summary: ComparisonSummary = compare_model_performance(
        records,
        expected_groups=expected_groups,
    )
    degraded = ("comparison",) if any(metric.value is None for metric in summary.metrics) else ()
    return ComparisonDashboardView(
        metrics=summary.metrics,
        degraded_sections=degraded,
    )


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
