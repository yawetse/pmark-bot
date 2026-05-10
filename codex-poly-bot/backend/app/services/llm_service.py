"""LLM scoring orchestration helpers.

REQ: REQ-LLM-001, REQ-LLM-002, REQ-LLM-004, REQ-LLM-005
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.domain import Instrument, ModelProvider, ScoringOutput
from app.venues.polymarket import VenueCallResult


@dataclass(frozen=True)
class LlmScoreRequest:
    """A model-provider scoring request for one candidate instrument.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    model_provider: ModelProvider
    instrument: Instrument
    prompt_version: str = "pm-v1"
    input_summary: str = "candidate market context"


@dataclass(frozen=True)
class ScoringQueueResult:
    """Scoring queue build result with skipped provider details.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    requests: tuple[LlmScoreRequest, ...]
    skipped_providers: tuple[ModelProvider, ...] = ()


@dataclass(frozen=True)
class ScoringFailure:
    """A provider/instrument scoring failure.

    REQ: REQ-LLM-005
    """

    model_provider: ModelProvider
    instrument_id: str
    reason: str


@dataclass(frozen=True)
class ScoringRunResult:
    """Result of one scoring pass across eligible providers.

    REQ: REQ-LLM-001, REQ-LLM-004, REQ-LLM-005
    """

    ok: bool
    scores: tuple[ScoringOutput, ...] = ()
    skipped_providers: tuple[ModelProvider, ...] = ()
    failures: tuple[ScoringFailure, ...] = ()


@dataclass
class LlmBudgetLedger:
    """Mutable budget ledger keyed by model provider.

    REQ: REQ-LLM-002
    """

    budgets: dict[ModelProvider, Decimal]
    spent: dict[ModelProvider, Decimal] = field(default_factory=dict)


class LlmProvider(Protocol):
    """Provider protocol used by the scoring orchestration helpers.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    model_provider: ModelProvider
    remaining_budget: Decimal
    enabled: bool

    def score_candidate(self, request: LlmScoreRequest) -> ScoringOutput:
        """Return a normalized scoring output for a request."""


class FakeLlmProvider:
    """Deterministic provider used by spec tests.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        *,
        remaining_budget: Decimal = Decimal("1.00"),
        enabled: bool = True,
        cost_estimate: Decimal = Decimal("0.01"),
    ) -> None:
        self.model_provider = model_provider
        self.remaining_budget = _as_decimal(remaining_budget)
        self.enabled = enabled
        self.cost_estimate = _as_decimal(cost_estimate)
        self.call_count = 0

    def score_candidate(self, request: LlmScoreRequest) -> ScoringOutput:
        """Return a deterministic score and count provider invocations.

        REQ: REQ-LLM-001
        """

        self.call_count += 1
        return ScoringOutput(
            model_provider=self.model_provider,
            prompt_version=request.prompt_version,
            input_summary=request.input_summary,
            output_thesis="candidate clears baseline scoring threshold",
            confidence=Decimal("0.70"),
            estimated_probability=Decimal("0.60"),
            cost_estimate=self.cost_estimate,
            instrument=request.instrument,
        )


def build_scoring_queue(
    instruments: tuple[Instrument, ...],
    providers: tuple[LlmProvider, ...],
) -> ScoringQueueResult:
    """Build requests only for enabled providers with budget remaining.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    requests: list[LlmScoreRequest] = []
    skipped: list[ModelProvider] = []
    for provider in providers:
        if not provider.enabled or provider.remaining_budget <= Decimal("0"):
            skipped.append(provider.model_provider)
            continue
        for instrument in instruments:
            requests.append(
                LlmScoreRequest(
                    model_provider=provider.model_provider,
                    instrument=instrument,
                )
            )
    return ScoringQueueResult(
        requests=tuple(requests),
        skipped_providers=tuple(dict.fromkeys(skipped)),
    )


def run_llm_scoring(
    instruments: tuple[Instrument, ...],
    providers: tuple[LlmProvider, ...],
) -> ScoringRunResult:
    """Run scoring for each eligible provider independently.

    REQ: REQ-LLM-001, REQ-LLM-004, REQ-LLM-005
    """

    queue = build_scoring_queue(instruments, providers)
    provider_lookup = {provider.model_provider: provider for provider in providers}
    scores: list[ScoringOutput] = []
    failures: list[ScoringFailure] = []

    for request in queue.requests:
        provider = provider_lookup[request.model_provider]
        try:
            scores.append(provider.score_candidate(request))
        except Exception as exc:  # pragma: no cover
            failures.append(
                ScoringFailure(
                    model_provider=request.model_provider,
                    instrument_id=request.instrument.identifier,
                    reason=str(exc),
                )
            )

    return ScoringRunResult(
        ok=not failures,
        scores=tuple(scores),
        skipped_providers=queue.skipped_providers,
        failures=tuple(failures),
    )


def record_provider_cost(
    ledger: LlmBudgetLedger,
    expected_provider: ModelProvider,
    event_provider: ModelProvider,
    cost: Decimal,
) -> VenueCallResult:
    """Record scoring cost against the correct provider budget.

    REQ: REQ-LLM-002, REQ-LLM-004
    """

    if expected_provider != event_provider:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("provider budget mismatch",),
            payload={
                "expected_provider": expected_provider.value,
                "event_provider": event_provider.value,
            },
        )

    charge = _as_decimal(cost)
    current_spend = ledger.spent.get(expected_provider, Decimal("0"))
    budget = ledger.budgets.get(expected_provider, Decimal("0"))
    if current_spend + charge > budget:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("DEFERRED_BUDGET_EXHAUSTED",),
            payload={
                "provider": expected_provider.value,
                "budget": str(budget),
                "spent": str(current_spend),
                "charge": str(charge),
            },
        )

    ledger.spent[expected_provider] = current_spend + charge
    return VenueCallResult(
        ok=True,
        payload={
            "provider": expected_provider.value,
            "spent": str(ledger.spent[expected_provider]),
            "remaining": str(budget - ledger.spent[expected_provider]),
        },
    )


def check_scoring_failure_gate(
    *,
    failures: tuple[ScoringFailure, ...],
    model_provider: ModelProvider,
    instrument: Instrument,
) -> VenueCallResult:
    """Block execution when the same loop has a failed provider score.

    REQ: REQ-LLM-005
    """

    for failure in failures:
        if (
            failure.model_provider == model_provider
            and failure.instrument_id == instrument.identifier
        ):
            return VenueCallResult(
                ok=False,
                refusal_reasons=("SCORING_MISSING_OR_FAILED",),
                payload={"reason": failure.reason},
            )
    return VenueCallResult(
        ok=True,
        payload={
            "model_provider": model_provider.value,
            "instrument_id": instrument.identifier,
        },
    )


def _as_decimal(value: Decimal) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
