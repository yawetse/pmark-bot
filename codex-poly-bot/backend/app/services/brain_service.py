"""Reasoning and LLM scoring orchestration for scanner survivors.

REQ: REQ-LLM-001, REQ-LLM-002, REQ-LLM-003, REQ-LLM-004,
REQ-LLM-005, REQ-STR-003, REQ-UI-004, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Mapping

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import Environment, Instrument, InstrumentType, ModelProvider, ScoringOutput, Venue
from app.services.llm_service import (
    ClaudeMessagesProvider,
    cost_controlled_openai_scoring_model,
    DEFAULT_CLAUDE_SCORING_MODEL,
    DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS,
    DEFAULT_OPENAI_SCORING_REASONING_EFFORT,
    LlmProvider,
    LlmProviderCredential,
    LlmScoreRequest,
    LlmUsageEvent,
    OpenAIResponsesProvider,
    token_pricing_from_env,
)


DEFAULT_REASONING_CONFIG: dict[str, Any] = {
    "max_prompts_per_provider_per_run": 100,
    "polymarket": {
        "prompt_version": "pm-brain-v1",
        "min_confidence": "0.75",
        "min_edge": "0.07",
        "checks": ["base_rate", "news", "whale_check", "disposition"],
    },
    "alpaca": {
        "prompt_version": "stock-brain-v1",
        "min_confidence": "0.60",
        "min_edge": "0.02",
        "inputs": [
            "price_action",
            "historical_bars",
            "volume",
            "sector",
            "index_membership",
            "event_news",
            "risk",
            "liquidity",
        ],
    },
}


@dataclass(frozen=True)
class ReasoningRunResult:
    """Dashboard-ready result for one reasoning run."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class _ProviderPlan:
    provider: LlmProvider
    skip_reason: str | None = None


class BrainService:
    """Score accepted scanner candidates and persist normalized reasoning output."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        providers: tuple[LlmProvider, ...] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.registry = registry
        self.providers = providers
        self.environ = environ or {}

    def run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        scanner_run: dict[str, Any],
        config_payload: dict[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> ReasoningRunResult:
        """Run LLM scoring for accepted scanner candidates and persist outputs."""

        reasoning_config = reasoning_config_from_payload(config_payload)
        accepted_candidates = tuple(
            candidate
            for candidate in scanner_run.get("candidates", ())
            if candidate.get("status") == "accepted"
        )
        provider_plans = self._provider_plans(environment, config_payload)
        outputs: list[dict[str, Any]] = []
        skipped = 0
        failed = 0
        scored = 0
        sent_by_provider: dict[ModelProvider, int] = {}
        max_prompts_per_provider = _positive_int(
            reasoning_config.get("max_prompts_per_provider_per_run"),
            100,
        )

        run_row = self.registry.shared().record_reasoning_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            scanner_run_id=scanner_run.get("id"),
            trigger=trigger,
            status="running",
            config=reasoning_config,
            provider_count=len(provider_plans),
            prompt_count=len(accepted_candidates) * len(provider_plans),
            scored_count=0,
            skipped_count=0,
            failed_count=0,
            started_at=started_at,
            completed_at=completed_at,
        )

        for candidate in accepted_candidates:
            for plan in provider_plans:
                if plan.skip_reason is not None:
                    skipped += 1
                    outputs.append(
                        self._record_skipped_output(
                            environment=environment,
                            reasoning_run_id=run_row["id"],
                            candidate=candidate,
                            provider=plan.provider,
                            config=reasoning_config,
                            reason=plan.skip_reason,
                            created_at=completed_at,
                        )
                    )
                    continue
                sent_count = sent_by_provider.get(plan.provider.model_provider, 0)
                if sent_count >= max_prompts_per_provider:
                    skipped += 1
                    outputs.append(
                        self._record_skipped_output(
                            environment=environment,
                            reasoning_run_id=run_row["id"],
                            candidate=candidate,
                            provider=plan.provider,
                            config=reasoning_config,
                            reason="provider rate limit reached",
                            created_at=completed_at,
                        )
                    )
                    continue
                sent_by_provider[plan.provider.model_provider] = sent_count + 1
                try:
                    outputs.append(
                        self._score_candidate(
                            environment=environment,
                            pipeline_run_id=pipeline_run_id,
                            reasoning_run_id=run_row["id"],
                            candidate=candidate,
                            provider=plan.provider,
                            config=reasoning_config,
                            created_at=completed_at,
                        )
                    )
                    scored += 1
                except Exception as exc:
                    failed += 1
                    outputs.append(
                        self._record_failed_output(
                            environment=environment,
                            reasoning_run_id=run_row["id"],
                            candidate=candidate,
                            provider=plan.provider,
                            config=reasoning_config,
                            reason=str(exc),
                            created_at=completed_at,
                        )
                    )

        status = _reasoning_status(
            candidate_count=len(accepted_candidates),
            provider_count=len(provider_plans),
            scored_count=scored,
            skipped_count=skipped,
            failed_count=failed,
        )
        run_row = self.registry.shared().update_reasoning_run_result(
            reasoning_run_id=run_row["id"],
            status=status,
            scored_count=scored,
            skipped_count=skipped,
            failed_count=failed,
            completed_at=completed_at,
        )
        return ReasoningRunResult(payload=reasoning_run_payload(run_row, outputs))

    def _provider_plans(
        self,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> tuple[_ProviderPlan, ...]:
        providers = self.providers
        if providers is None:
            providers = self._default_providers(environment, config_payload)
        plans: list[_ProviderPlan] = []
        for provider in providers:
            skip_reason = None
            if not provider.enabled:
                skip_reason = "provider disabled or credential missing"
            elif provider.remaining_budget <= Decimal("0"):
                skip_reason = "provider budget exhausted"
            plans.append(_ProviderPlan(provider=provider, skip_reason=skip_reason))
        return tuple(plans)

    def _default_providers(
        self,
        environment: Environment,
        config_payload: dict[str, Any],
    ) -> tuple[LlmProvider, ...]:
        llm_config = config_payload.get("llm", {})
        openai_budget = _remaining_budget(
            registry=self.registry,
            environment=environment,
            provider=ModelProvider.OPENAI,
            budget=_provider_budget(llm_config, ModelProvider.OPENAI),
        )
        claude_budget = _remaining_budget(
            registry=self.registry,
            environment=environment,
            provider=ModelProvider.CLAUDE,
            budget=_provider_budget(llm_config, ModelProvider.CLAUDE),
        )
        openai_settings = llm_config.get(ModelProvider.OPENAI.value, {}).get("settings", {})
        claude_settings = llm_config.get(ModelProvider.CLAUDE.value, {}).get("settings", {})
        return (
            OpenAIResponsesProvider(
                credential=LlmProviderCredential(api_key=self.environ.get("OPENAI_API_KEY")),
                remaining_budget=openai_budget,
                enabled=_provider_enabled(llm_config, ModelProvider.OPENAI),
                model=cost_controlled_openai_scoring_model(openai_settings.get("model")),
                max_output_tokens=_positive_int(
                    openai_settings.get("max_output_tokens"),
                    DEFAULT_OPENAI_SCORING_MAX_OUTPUT_TOKENS,
                ),
                reasoning_effort=_optional_string(
                    openai_settings.get("reasoning_effort"),
                    DEFAULT_OPENAI_SCORING_REASONING_EFFORT,
                ),
                token_pricing=token_pricing_from_env(ModelProvider.OPENAI, self.environ),
            ),
            ClaudeMessagesProvider(
                credential=LlmProviderCredential(api_key=self.environ.get("ANTHROPIC_API_KEY")),
                remaining_budget=claude_budget,
                enabled=_provider_enabled(llm_config, ModelProvider.CLAUDE),
                model=_optional_string(
                    claude_settings.get("model"),
                    DEFAULT_CLAUDE_SCORING_MODEL,
                )
                or DEFAULT_CLAUDE_SCORING_MODEL,
                token_pricing=token_pricing_from_env(ModelProvider.CLAUDE, self.environ),
            ),
        )

    def _score_candidate(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        reasoning_run_id: str,
        candidate: dict[str, Any],
        provider: LlmProvider,
        config: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        instrument = _instrument_from_candidate(candidate)
        prompt_payload = _prompt_payload_for_candidate(candidate, config)
        prompt_version = _prompt_version(candidate, config)
        input_summary = json.dumps(prompt_payload, sort_keys=True, separators=(",", ":"))
        score = provider.score_candidate(
            LlmScoreRequest(
                model_provider=provider.model_provider,
                instrument=instrument,
                prompt_version=prompt_version,
                input_summary=input_summary,
            )
        )
        direction, strength = _directional_signal(candidate, score, config)
        usage_event = _last_usage_event(provider)
        prompt_tokens, completion_tokens, cost_usd = _usage_values(
            usage_event=usage_event,
            prompt_payload=prompt_payload,
            score=score,
        )
        self.registry.shared().record_ai_usage_event(
            environment=environment,
            provider=provider.model_provider,
            model=str(getattr(provider, "model", "")) or None,
            pipeline_run_id=pipeline_run_id,
            pipeline_step="brain",
            candidate_id=candidate.get("id"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            usage_source=usage_event.usage_source if usage_event else "estimated_scoring",
            cost_source=usage_event.cost_source if usage_event else "model cost_estimate fallback",
            response_id=usage_event.response_id if usage_event else None,
            raw_payload=usage_event.raw_payload if usage_event else {"usage": "estimated"},
            created_at=created_at,
        )
        response_payload = {
            "output_thesis": score.output_thesis,
            "confidence": str(score.confidence),
            "estimated_probability": str(score.estimated_probability),
            "cost_estimate": str(score.cost_estimate),
            "directional_signal": direction,
            "signal_strength": str(strength),
        }
        return self.registry.shared().record_reasoning_output(
            environment=environment,
            reasoning_run_id=reasoning_run_id,
            scanner_candidate_id=candidate.get("id"),
            venue=str(candidate.get("venue", "")),
            instrument_id=str(candidate.get("instrumentId") or candidate.get("instrument_id")),
            model_provider=provider.model_provider,
            prompt_version=prompt_version,
            status="scored",
            directional_signal=direction,
            signal_strength=strength,
            confidence=score.confidence,
            estimated_probability=score.estimated_probability,
            output_thesis=score.output_thesis,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_payload=prompt_payload,
            response_payload=response_payload,
            check_results=prompt_payload["checks"],
            created_at=created_at,
        )

    def _record_skipped_output(
        self,
        *,
        environment: Environment,
        reasoning_run_id: str,
        candidate: dict[str, Any],
        provider: LlmProvider,
        config: dict[str, Any],
        reason: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        prompt_payload = _prompt_payload_for_candidate(candidate, config)
        return self.registry.shared().record_reasoning_output(
            environment=environment,
            reasoning_run_id=reasoning_run_id,
            scanner_candidate_id=candidate.get("id"),
            venue=str(candidate.get("venue", "")),
            instrument_id=str(candidate.get("instrumentId") or candidate.get("instrument_id")),
            model_provider=provider.model_provider,
            prompt_version=_prompt_version(candidate, config),
            status="skipped",
            refusal_reason=reason,
            directional_signal="none",
            signal_strength=Decimal("0"),
            cost_usd=Decimal("0"),
            prompt_tokens=0,
            completion_tokens=0,
            prompt_payload=prompt_payload,
            response_payload={"refusal_reason": reason},
            check_results=prompt_payload["checks"],
            created_at=created_at,
        )

    def _record_failed_output(
        self,
        *,
        environment: Environment,
        reasoning_run_id: str,
        candidate: dict[str, Any],
        provider: LlmProvider,
        config: dict[str, Any],
        reason: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        prompt_payload = _prompt_payload_for_candidate(candidate, config)
        return self.registry.shared().record_reasoning_output(
            environment=environment,
            reasoning_run_id=reasoning_run_id,
            scanner_candidate_id=candidate.get("id"),
            venue=str(candidate.get("venue", "")),
            instrument_id=str(candidate.get("instrumentId") or candidate.get("instrument_id")),
            model_provider=provider.model_provider,
            prompt_version=_prompt_version(candidate, config),
            status="failed",
            refusal_reason=reason,
            directional_signal="none",
            signal_strength=Decimal("0"),
            cost_usd=Decimal("0"),
            prompt_tokens=_estimate_tokens(prompt_payload),
            completion_tokens=0,
            prompt_payload=prompt_payload,
            response_payload={"error": reason},
            check_results=prompt_payload["checks"],
            created_at=created_at,
        )


def reasoning_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    """Merge persisted reasoning config with defaults."""

    configured = config_payload.get("reasoning")
    if not isinstance(configured, dict):
        configured = {}
    return {
        "max_prompts_per_provider_per_run": _positive_int(
            configured.get("max_prompts_per_provider_per_run"),
            DEFAULT_REASONING_CONFIG["max_prompts_per_provider_per_run"],
        ),
        "polymarket": {
            **DEFAULT_REASONING_CONFIG["polymarket"],
            **dict(configured.get("polymarket", {})),
        },
        "alpaca": {
            **DEFAULT_REASONING_CONFIG["alpaca"],
            **dict(configured.get("alpaca", {})),
        },
    }


def reasoning_run_payload(
    run_row: dict[str, Any],
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a dashboard-safe reasoning run payload."""

    output_payloads = [_reasoning_output_view(output) for output in outputs]
    return {
        "id": run_row.get("id"),
        "environment": run_row.get("environment"),
        "pipelineRunId": run_row.get("pipeline_run_id"),
        "scannerRunId": run_row.get("scanner_run_id"),
        "trigger": run_row.get("trigger"),
        "status": run_row.get("status"),
        "providerCount": int(run_row.get("provider_count", 0)),
        "promptCount": int(run_row.get("prompt_count", 0)),
        "scoredCount": int(run_row.get("scored_count", 0)),
        "skippedCount": int(run_row.get("skipped_count", 0)),
        "failedCount": int(run_row.get("failed_count", 0)),
        "startedAt": _isoformat_or_none(run_row.get("started_at")),
        "completedAt": _isoformat_or_none(run_row.get("completed_at")),
        "outputs": output_payloads,
    }


def _reasoning_output_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "reasoningRunId": row.get("reasoning_run_id"),
        "scannerCandidateId": row.get("scanner_candidate_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "modelProvider": row.get("model_provider"),
        "promptVersion": row.get("prompt_version"),
        "status": row.get("status"),
        "refusalReason": row.get("refusal_reason"),
        "directionalSignal": row.get("directional_signal"),
        "signalStrength": _string_or_none(row.get("signal_strength")),
        "confidence": _string_or_none(row.get("confidence")),
        "estimatedProbability": _string_or_none(row.get("estimated_probability")),
        "costUsd": _string_or_none(row.get("cost_usd")),
        "promptTokens": int(row.get("prompt_tokens", 0)),
        "completionTokens": int(row.get("completion_tokens", 0)),
        "totalTokens": int(row.get("total_tokens", 0)),
        "checks": row.get("check_results", []),
        "thesis": row.get("output_thesis"),
        "createdAt": _isoformat_or_none(row.get("created_at")),
    }


def _prompt_payload_for_candidate(candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    venue = str(candidate.get("venue", ""))
    if venue == Venue.ALPACA.value:
        return _stock_prompt_payload(candidate, config["alpaca"])
    return _polymarket_prompt_payload(candidate, config["polymarket"])


def _polymarket_prompt_payload(candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    metrics = _mapping(candidate.get("metrics"))
    return {
        "prompt_type": "polymarket_reasoning",
        "candidate": _candidate_context(candidate),
        "instructions": (
            "Run the base-rate, recent-news, target-wallet, and disposition checks. "
            "Return probability, confidence, thesis, and cost estimate."
        ),
        "checks": [
            {
                "name": "base_rate",
                "status": "prompted",
                "input": {
                    "category": metrics.get("category"),
                    "hours_to_resolution": candidate.get("hoursToResolution"),
                },
            },
            {
                "name": "news",
                "status": "needs_provider_data",
                "input": {"lookback_hours": 6},
            },
            {
                "name": "whale_check",
                "status": "available" if metrics.get("targetWalletCount") else "needs_provider_data",
                "input": {
                    "target_wallet_count": metrics.get("targetWalletCount", 0),
                    "target_wallets": metrics.get("targetWallets", []),
                },
            },
            {
                "name": "disposition",
                "status": "prompted",
                "input": {"biases": ["recency_bias", "anchoring", "narrative_fallacy"]},
            },
        ],
        "normalization": {
            "min_confidence": str(config.get("min_confidence", "0.75")),
            "min_edge": str(config.get("min_edge", "0.07")),
            "signals": ["buy_yes", "buy_no", "hold"],
        },
    }


def _stock_prompt_payload(candidate: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    metrics = _mapping(candidate.get("metrics"))
    source_payload = _mapping(candidate.get("sourcePayload") or candidate.get("source_payload"))
    return {
        "prompt_type": "stock_reasoning",
        "candidate": _candidate_context(candidate),
        "instructions": (
            "Evaluate the stock candidate with price action, bars, volume, sector, "
            "index membership, event/news context, risk, and liquidity."
        ),
        "checks": [
            {"name": "price_action", "status": "available", "input": metrics},
            {
                "name": "historical_bars",
                "status": "available" if source_payload.get("bar") or metrics else "needs_provider_data",
                "input": source_payload.get("bar", {}),
            },
            {"name": "volume", "status": "available", "input": metrics},
            {
                "name": "sector",
                "status": "needs_provider_data",
                "input": {"sector": source_payload.get("sector")},
            },
            {
                "name": "index_membership",
                "status": "available" if source_payload.get("presetMembership") else "prompted",
                "input": {"presets": source_payload.get("presetMembership", [])},
            },
            {"name": "event_news", "status": "needs_provider_data", "input": {"lookback_hours": 24}},
            {"name": "risk", "status": "prompted", "input": {"spread": candidate.get("spread")}},
            {"name": "liquidity", "status": "available", "input": {"liquidity": candidate.get("liquidity")}},
        ],
        "normalization": {
            "min_confidence": str(config.get("min_confidence", "0.60")),
            "min_edge": str(config.get("min_edge", "0.02")),
            "signals": ["bullish", "bearish", "neutral"],
        },
    }


def _candidate_context(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "venue": candidate.get("venue"),
        "instrument_id": candidate.get("instrumentId") or candidate.get("instrument_id"),
        "display_name": candidate.get("displayName") or candidate.get("display_name"),
        "symbol": candidate.get("symbol"),
        "market_id": candidate.get("marketId") or candidate.get("market_id"),
        "outcome_id": candidate.get("outcomeId") or candidate.get("outcome_id"),
        "price": candidate.get("price"),
        "liquidity": candidate.get("liquidity"),
        "spread": candidate.get("spread"),
        "hours_to_resolution": candidate.get("hoursToResolution") or candidate.get("hours_to_resolution"),
        "strategy_names": candidate.get("strategyNames") or candidate.get("strategy_names") or [],
        "scanner_metrics": candidate.get("metrics", {}),
    }


def _instrument_from_candidate(candidate: dict[str, Any]) -> Instrument:
    venue_value = str(candidate.get("venue", Venue.POLYMARKET_US.value))
    venue = Venue(venue_value) if venue_value in {item.value for item in Venue} else Venue.POLYMARKET_US
    if venue == Venue.ALPACA:
        symbol = str(candidate.get("symbol") or candidate.get("instrumentId") or "UNKNOWN").upper()
        return Instrument(
            venue=venue,
            instrument_type=InstrumentType.STOCK,
            symbol=symbol,
            market_id=symbol,
            outcome_id=None,
            display_name=str(candidate.get("displayName") or symbol),
        )
    return Instrument(
        venue=venue,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id=str(candidate.get("marketId") or candidate.get("market_id") or candidate.get("instrumentId")),
        outcome_id=str(candidate.get("outcomeId") or candidate.get("outcome_id") or "unknown"),
        display_name=str(candidate.get("displayName") or candidate.get("display_name") or "Prediction market"),
    )


def _directional_signal(
    candidate: dict[str, Any],
    score: ScoringOutput,
    config: dict[str, Any],
) -> tuple[str, Decimal]:
    venue = str(candidate.get("venue", ""))
    current_price = _decimal(candidate.get("price"), Decimal("0.50"))
    if venue == Venue.ALPACA.value:
        midpoint = Decimal("0.50")
        edge = score.estimated_probability - midpoint
        threshold = _decimal(config["alpaca"].get("min_edge"), Decimal("0.02"))
        if edge >= threshold:
            return "bullish", abs(edge)
        if edge <= -threshold:
            return "bearish", abs(edge)
        return "neutral", abs(edge)
    edge = score.estimated_probability - current_price
    threshold = _decimal(config["polymarket"].get("min_edge"), Decimal("0.07"))
    if edge >= threshold:
        return "buy_yes", abs(edge)
    if edge <= -threshold:
        return "buy_no", abs(edge)
    return "hold", abs(edge)


def _prompt_version(candidate: dict[str, Any], config: dict[str, Any]) -> str:
    venue = str(candidate.get("venue", ""))
    if venue == Venue.ALPACA.value:
        return str(config["alpaca"].get("prompt_version", "stock-brain-v1"))
    return str(config["polymarket"].get("prompt_version", "pm-brain-v1"))


def _reasoning_status(
    *,
    candidate_count: int,
    provider_count: int,
    scored_count: int,
    skipped_count: int,
    failed_count: int,
) -> str:
    if candidate_count == 0:
        return "no_candidates"
    if provider_count == 0:
        return "blocked"
    if scored_count == 0 and failed_count:
        return "failed"
    if scored_count == 0 and skipped_count:
        return "skipped"
    if failed_count or skipped_count:
        return "partial"
    return "completed"


def _provider_budget(llm_config: dict[str, Any], provider: ModelProvider) -> Decimal:
    return _decimal(llm_config.get(provider.value, {}).get("budget_usd"), Decimal("0"))


def _provider_enabled(llm_config: dict[str, Any], provider: ModelProvider) -> bool:
    raw = llm_config.get(provider.value, {}).get("enabled", True)
    return bool(raw)


def _remaining_budget(
    *,
    registry: RepositoryRegistry,
    environment: Environment,
    provider: ModelProvider,
    budget: Decimal,
) -> Decimal:
    try:
        rows = [
            row
            for row in registry.state.rows("shared.ai_usage_events")
            if row.get("environment") == environment.value and row.get("provider") == provider.value
        ]
    except PersistenceUnavailableError:
        return Decimal("0")
    spent = sum((_decimal(row.get("cost_usd"), Decimal("0")) for row in rows), Decimal("0"))
    return budget - spent


def _usage_values(
    *,
    usage_event: LlmUsageEvent | None,
    prompt_payload: dict[str, Any],
    score: ScoringOutput,
) -> tuple[int, int, Decimal]:
    if usage_event is not None:
        return usage_event.prompt_tokens, usage_event.completion_tokens, usage_event.cost_usd
    prompt_tokens = _estimate_tokens(prompt_payload)
    completion_tokens = max(1, len(score.output_thesis) // 4)
    return prompt_tokens, completion_tokens, score.cost_estimate


def _last_usage_event(provider: LlmProvider) -> LlmUsageEvent | None:
    event = getattr(provider, "last_usage_event", None)
    return event if isinstance(event, LlmUsageEvent) else None


def _estimate_tokens(payload: dict[str, Any]) -> int:
    return max(1, len(json.dumps(payload, sort_keys=True)) // 4)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _decimal(value: Any, default: Decimal) -> Decimal:
    if value is None or value == "":
        return default
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default
    if not decimal.is_finite():
        return default
    return decimal


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _optional_string(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    parsed = str(value).strip()
    return parsed or default


def _isoformat_or_none(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)
