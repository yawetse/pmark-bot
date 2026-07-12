"""LLM scoring orchestration helpers.

REQ: REQ-LLM-001, REQ-LLM-002, REQ-LLM-003, REQ-LLM-004,
REQ-LLM-005, REQ-OBS-001
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Protocol

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment, Instrument, ModelProvider, ScoringOutput
from app.venues.polymarket import VenueCallResult


SCORING_SYSTEM_PROMPT = (
    "Return one JSON object with output_thesis, confidence, "
    "estimated_probability, and cost_estimate for the candidate. "
    "Use the requested checks in the output thesis. "
    "confidence and estimated_probability must be decimal strings between 0 and 1, "
    "for example \"0.64\". cost_estimate is the estimated model API call cost in "
    "USD as a decimal string, for example \"0.01\". Do not include percentages, "
    "currency symbols, ranges, units, markdown, or prose outside the JSON object."
)
OPENAI_SCORING_MODEL_OPTIONS = ("gpt-5-nano", "gpt-5-mini")
DEFAULT_OPENAI_SCORING_MODEL = "gpt-5-mini"
DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS = 4096
DEFAULT_OPENAI_SCORING_REASONING_EFFORT = "minimal"
DEFAULT_CLAUDE_SCORING_MODEL = "claude-sonnet-5"
DEFAULT_CLAUDE_SCORING_MAX_TOKENS = 4096
DEFAULT_SCORING_FALLBACK_COST_ESTIMATE = Decimal("0.01")


def cost_controlled_openai_scoring_model(value: Any) -> str:
    """Return an allowed OpenAI scoring model, defaulting away from full GPT-5."""

    candidate = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "gpt5-nano": "gpt-5-nano",
        "gpt5-mini": "gpt-5-mini",
    }
    normalized = aliases.get(candidate, candidate)
    if normalized in OPENAI_SCORING_MODEL_OPTIONS:
        return normalized
    return DEFAULT_OPENAI_SCORING_MODEL

SCORING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "output_thesis": {"type": "string"},
        "confidence": {"type": "string"},
        "estimated_probability": {"type": "string"},
        "cost_estimate": {"type": "string"},
    },
    "required": [
        "output_thesis",
        "confidence",
        "estimated_probability",
        "cost_estimate",
    ],
}


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


@dataclass(frozen=True)
class LlmProviderCredential:
    """Resolved provider API credential metadata.

    REQ: REQ-LLM-001
    """

    api_key: str | None
    credential_ref: str | None = None

    @property
    def present(self) -> bool:
        return bool((self.api_key or "").strip())


@dataclass(frozen=True)
class TokenPricing:
    """Configurable token pricing used when provider responses include usage.

    REQ: REQ-LLM-002, REQ-OBS-005
    """

    input_cost_per_million_tokens: Decimal = Decimal("0")
    output_cost_per_million_tokens: Decimal = Decimal("0")

    def cost_for(self, *, prompt_tokens: int, completion_tokens: int) -> Decimal:
        prompt_cost = (Decimal(prompt_tokens) / Decimal("1000000")) * self.input_cost_per_million_tokens
        completion_cost = (
            Decimal(completion_tokens) / Decimal("1000000")
        ) * self.output_cost_per_million_tokens
        return prompt_cost + completion_cost


@dataclass(frozen=True)
class LlmUsageEvent:
    """Provider response usage normalized for dashboard economics.

    REQ: REQ-LLM-002, REQ-OBS-005
    """

    provider: ModelProvider
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    cost_source: str
    response_id: str | None = None
    pipeline_run_id: str | None = None
    pipeline_step: str | None = None
    candidate_id: str | None = None
    usage_source: str = "provider_response"
    raw_payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LlmUsageRecorder(Protocol):
    """Persistence boundary for provider-side token usage events.

    REQ: REQ-LLM-002, REQ-OBS-005
    """

    def record_usage(self, event: LlmUsageEvent) -> None:
        """Persist one normalized provider usage event."""


@dataclass(frozen=True)
class RepositoryLlmUsageRecorder:
    """Record provider token usage in the shared AI usage table.

    REQ: REQ-LLM-002, REQ-OBS-005
    """

    registry: RepositoryRegistry
    environment: Environment

    def record_usage(self, event: LlmUsageEvent) -> None:
        shared = self.registry.shared()
        row = shared.record_ai_usage_event(
            environment=self.environment,
            provider=event.provider,
            model=event.model,
            pipeline_run_id=event.pipeline_run_id,
            pipeline_step=event.pipeline_step,
            candidate_id=event.candidate_id,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            cost_usd=event.cost_usd,
            usage_source=event.usage_source,
            cost_source=event.cost_source,
            response_id=event.response_id,
            raw_payload=event.raw_payload,
            created_at=event.created_at,
        )
        shared.record_audit_event(
            event_type="ai_usage_import",
            actor="system",
            action="llm.provider_usage.record",
            environment=self.environment,
            entity_id=row["id"],
            metadata={
                "provider": event.provider.value,
                "model": event.model,
                "prompt_tokens": event.prompt_tokens,
                "completion_tokens": event.completion_tokens,
                "total_tokens": event.total_tokens,
                "cost_usd": str(event.cost_usd),
                "cost_source": event.cost_source,
                "response_id": event.response_id,
                "pipeline_run_id": event.pipeline_run_id,
                "pipeline_step": event.pipeline_step,
                "candidate_id": event.candidate_id,
                "usage_source": event.usage_source,
            },
        )


class LlmProvider(Protocol):
    """Provider protocol used by the scoring orchestration helpers.

    REQ: REQ-LLM-001, REQ-LLM-004
    """

    model_provider: ModelProvider
    remaining_budget: Decimal
    enabled: bool

    def score_candidate(self, request: LlmScoreRequest) -> ScoringOutput:
        """Return a normalized scoring output for a request."""


class LlmProviderTransport(Protocol):
    """HTTP transport boundary for external LLM providers.

    REQ: REQ-LLM-001, REQ-OBS-001
    """

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Post JSON to a provider and return parsed JSON."""


@dataclass(frozen=True)
class HttpxProviderTransport:
    """Default HTTP transport used by external provider adapters.

    REQ: REQ-LLM-001, REQ-OBS-001
    """

    timeout_seconds: float = 30.0

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


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


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter for normalized scoring.

    REQ: REQ-LLM-001, REQ-LLM-003, REQ-OBS-001
    """

    model_provider = ModelProvider.OPENAI

    def __init__(
        self,
        *,
        credential: LlmProviderCredential,
        transport: LlmProviderTransport | None = None,
        remaining_budget: Decimal = Decimal("0"),
        enabled: bool = True,
        model: str = DEFAULT_OPENAI_SCORING_MODEL,
        base_url: str = "https://api.openai.com",
        max_output_tokens: int = DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS,
        reasoning_effort: str | None = DEFAULT_OPENAI_SCORING_REASONING_EFFORT,
        usage_recorder: LlmUsageRecorder | None = None,
        token_pricing: TokenPricing | None = None,
    ) -> None:
        self.credential = credential
        self.transport = transport or HttpxProviderTransport()
        self.remaining_budget = _as_decimal(remaining_budget)
        self.enabled = enabled and credential.present
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.usage_recorder = usage_recorder
        self.token_pricing = token_pricing
        self.last_usage_event: LlmUsageEvent | None = None

    def score_candidate(self, request: LlmScoreRequest) -> ScoringOutput:
        """Send a scoring request through OpenAI's Responses API.

        REQ: REQ-LLM-001, REQ-LLM-003
        """

        self.last_usage_event = None
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": _scoring_user_prompt(request)},
            ],
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "codex_poly_score",
                    "schema": SCORING_JSON_SCHEMA,
                    "strict": True,
                }
            },
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        body = self.transport.post_json(
            url=f"{self.base_url}/v1/responses",
            headers={
                "Authorization": f"Bearer {self.credential.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        score = _score_from_provider_text(
            text=_openai_response_text(body),
            request=request,
            model_provider=self.model_provider,
        )
        self._record_usage(body=body, fallback_cost=score.cost_estimate)
        return score

    def _record_usage(self, *, body: dict[str, Any], fallback_cost: Decimal) -> None:
        event = _usage_event_from_provider_response(
            body=body,
            model_provider=self.model_provider,
            model=self.model,
            fallback_cost=fallback_cost,
            token_pricing=self.token_pricing,
        )
        self.last_usage_event = event
        if event is None:
            return
        if self.usage_recorder is None:
            return
        try:
            self.usage_recorder.record_usage(event)
        except Exception:
            return


class ClaudeMessagesProvider:
    """Anthropic Claude Messages API adapter for normalized scoring.

    REQ: REQ-LLM-001, REQ-LLM-003, REQ-OBS-001
    """

    model_provider = ModelProvider.CLAUDE

    def __init__(
        self,
        *,
        credential: LlmProviderCredential,
        transport: LlmProviderTransport | None = None,
        remaining_budget: Decimal = Decimal("0"),
        enabled: bool = True,
        model: str = DEFAULT_CLAUDE_SCORING_MODEL,
        base_url: str = "https://api.anthropic.com",
        max_tokens: int = DEFAULT_CLAUDE_SCORING_MAX_TOKENS,
        usage_recorder: LlmUsageRecorder | None = None,
        token_pricing: TokenPricing | None = None,
    ) -> None:
        self.credential = credential
        self.transport = transport or HttpxProviderTransport()
        self.remaining_budget = _as_decimal(remaining_budget)
        self.enabled = enabled and credential.present
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.usage_recorder = usage_recorder
        self.token_pricing = token_pricing
        self.last_usage_event: LlmUsageEvent | None = None

    def score_candidate(self, request: LlmScoreRequest) -> ScoringOutput:
        """Send a scoring request through Anthropic's Messages API.

        REQ: REQ-LLM-001, REQ-LLM-003
        """

        self.last_usage_event = None
        body = self.transport.post_json(
            url=f"{self.base_url}/v1/messages",
            headers={
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "x-api-key": str(self.credential.api_key),
            },
            payload={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": SCORING_SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": _scoring_user_prompt(request),
                    }
                ],
            },
        )
        score = _score_from_provider_text(
            text=_claude_response_text(body),
            request=request,
            model_provider=self.model_provider,
        )
        self._record_usage(body=body, fallback_cost=score.cost_estimate)
        return score

    def _record_usage(self, *, body: dict[str, Any], fallback_cost: Decimal) -> None:
        event = _usage_event_from_provider_response(
            body=body,
            model_provider=self.model_provider,
            model=self.model,
            fallback_cost=fallback_cost,
            token_pricing=self.token_pricing,
        )
        self.last_usage_event = event
        if event is None:
            return
        if self.usage_recorder is None:
            return
        try:
            self.usage_recorder.record_usage(event)
        except Exception:
            return


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


def reconcile_scoring_cost(
    ledger: LlmBudgetLedger,
    score: ScoringOutput,
    *,
    actual_cost: Decimal | str | None = None,
) -> VenueCallResult:
    """Reconcile returned or estimated scoring cost into budget status.

    REQ: REQ-LLM-002, REQ-LLM-003, REQ-LLM-004
    """

    cost_source = "actual" if actual_cost is not None else "estimated"
    cost = _as_decimal(actual_cost if actual_cost is not None else score.cost_estimate)
    result = record_provider_cost(
        ledger,
        score.model_provider,
        score.model_provider,
        cost,
    )
    if not result.ok:
        return result
    budget = ledger.budgets.get(score.model_provider, Decimal("0"))
    spent = ledger.spent.get(score.model_provider, Decimal("0"))
    return VenueCallResult(
        ok=True,
        payload={
            "budget_status": {
                "budget": str(budget),
                "provider": score.model_provider.value,
                "remaining": str(budget - spent),
                "spent": str(spent),
            },
            "cost": str(cost),
            "cost_source": cost_source,
            "instrument_id": score.instrument.identifier,
            "provider": score.model_provider.value,
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


def _scoring_user_prompt(request: LlmScoreRequest) -> str:
    return (
        f"Provider: {request.model_provider.value}\n"
        f"Prompt version: {request.prompt_version}\n"
        f"Instrument: {request.instrument.identifier}\n"
        f"Context: {request.input_summary}"
    )


def _openai_response_text(body: dict[str, Any]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in body.get("output", ()):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", ()):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not include output text")


def _claude_response_text(body: dict[str, Any]) -> str:
    for content in body.get("content", ()):
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise ValueError("Claude response did not include text content")


def _score_from_provider_text(
    *,
    text: str,
    request: LlmScoreRequest,
    model_provider: ModelProvider,
) -> ScoringOutput:
    payload = _provider_json_payload(text)
    return ScoringOutput(
        model_provider=model_provider,
        prompt_version=request.prompt_version,
        input_summary=request.input_summary,
        output_thesis=payload["output_thesis"],
        confidence=_coerce_probability_text(payload["confidence"], "confidence"),
        estimated_probability=_coerce_probability_text(
            payload["estimated_probability"],
            "estimated_probability",
        ),
        cost_estimate=_coerce_cost_estimate(payload["cost_estimate"]),
        instrument=request.instrument,
    )


def _provider_json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("provider scoring response must be a JSON object")
    return payload


_NUMERIC_TEXT_RE = re.compile(r"[-+]?(?:\d+(?:,\d{3})*|\d*\.\d+|\d+)")
_QUALITATIVE_PROBABILITY = {
    "very low": Decimal("0.15"),
    "low": Decimal("0.25"),
    "moderate-low": Decimal("0.35"),
    "medium-low": Decimal("0.35"),
    "moderate": Decimal("0.50"),
    "medium": Decimal("0.50"),
    "moderate-high": Decimal("0.65"),
    "medium-high": Decimal("0.65"),
    "high": Decimal("0.75"),
    "very high": Decimal("0.85"),
}


def _coerce_probability_text(value: Any, field_name: str) -> Decimal:
    if isinstance(value, int | float | Decimal):
        decimal = _as_decimal(value)
        return _normalize_probability_decimal(decimal, field_name)
    text = str(value).strip()
    try:
        return _normalize_probability_decimal(_as_decimal(text), field_name)
    except ValueError:
        pass

    normalized_text = text.lower().strip()
    if normalized_text in _QUALITATIVE_PROBABILITY:
        return _QUALITATIVE_PROBABILITY[normalized_text]

    match = _NUMERIC_TEXT_RE.search(text)
    if match is None:
        raise ValueError(f"{field_name} must be a decimal probability")
    decimal = _as_decimal(match.group(0).replace(",", ""))
    if "%" in text or decimal > 1:
        decimal = decimal / Decimal("100")
    return _normalize_probability_decimal(decimal, field_name)


def _normalize_probability_decimal(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def _coerce_cost_estimate(value: Any) -> Decimal:
    if isinstance(value, int | float | Decimal):
        return _safe_model_call_cost(_as_decimal(value))

    text = str(value).strip()
    try:
        return _safe_model_call_cost(_as_decimal(text))
    except ValueError:
        pass

    money_match = re.search(r"\$\s*(" + _NUMERIC_TEXT_RE.pattern + ")", text)
    match = money_match or _NUMERIC_TEXT_RE.search(text)
    if match is None:
        return DEFAULT_SCORING_FALLBACK_COST_ESTIMATE
    raw = match.group(1) if money_match else match.group(0)
    return _safe_model_call_cost(_as_decimal(raw.replace(",", "")))


def _safe_model_call_cost(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        return DEFAULT_SCORING_FALLBACK_COST_ESTIMATE
    if value > Decimal("10"):
        return DEFAULT_SCORING_FALLBACK_COST_ESTIMATE
    return value


def _usage_event_from_provider_response(
    *,
    body: dict[str, Any],
    model_provider: ModelProvider,
    model: str,
    fallback_cost: Decimal,
    token_pricing: TokenPricing | None,
) -> LlmUsageEvent | None:
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return None
    if model_provider == ModelProvider.OPENAI:
        prompt_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
        completion_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    else:
        prompt_tokens = (
            _usage_int(usage, "input_tokens")
            + _usage_int(usage, "cache_creation_input_tokens")
            + _usage_int(usage, "cache_read_input_tokens")
        )
        completion_tokens = _usage_int(usage, "output_tokens")
    if prompt_tokens == 0 and completion_tokens == 0:
        return None

    if token_pricing is None:
        cost = fallback_cost
        cost_source = "model cost_estimate fallback"
    else:
        cost = token_pricing.cost_for(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        cost_source = "provider tokens x configured rate"

    return LlmUsageEvent(
        provider=model_provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        cost_source=cost_source,
        response_id=body.get("id") if isinstance(body.get("id"), str) else None,
        raw_payload={"usage": dict(usage)},
    )


def token_pricing_from_env(
    model_provider: ModelProvider,
    environ: Mapping[str, str],
) -> TokenPricing | None:
    """Return optional provider token rates from environment variables.

    REQ: REQ-LLM-002, REQ-OBS-005
    """

    prefix = "OPENAI" if model_provider == ModelProvider.OPENAI else "ANTHROPIC"
    input_rate = _optional_decimal(environ.get(f"{prefix}_INPUT_COST_PER_MILLION_TOKENS"))
    output_rate = _optional_decimal(environ.get(f"{prefix}_OUTPUT_COST_PER_MILLION_TOKENS"))
    if input_rate is None and output_rate is None:
        return None
    return TokenPricing(
        input_cost_per_million_tokens=input_rate or Decimal("0"),
        output_cost_per_million_tokens=output_rate or Decimal("0"),
    )


def _usage_int(usage: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        return max(0, parsed)
    return 0


def _optional_decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return _as_decimal(value)


def _as_decimal(value: Decimal | str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
