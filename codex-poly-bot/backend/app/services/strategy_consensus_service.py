"""Strategy vote and consensus orchestration for scored candidates.

REQ: REQ-STR-004, REQ-STR-005, REQ-STR-006, REQ-STR-007,
REQ-STR-008, REQ-UI-004, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import (
    Environment,
    Instrument,
    InstrumentType,
    ModelProvider,
    OrderSide,
    ScoringOutput,
    StrategySignal,
    Venue,
)
from app.strategies import (
    ArbitrageStrategy,
    ConvergenceStrategy,
    MarketCandidate,
    WhaleCopyStrategy,
    apply_strategy_consensus,
)


DEFAULT_STRATEGY_CONSENSUS_CONFIG: dict[str, Any] = {
    "consensus_rule": "default",
    "polymarket": {
        "min_arbitrage_dislocation": "0.10",
        "min_convergence_gap": "0.07",
        "whale_copy_delay_seconds": 0,
    },
    "alpaca": {
        "event_strategy_names": ["gap", "unusual_volume"],
    },
}


@dataclass(frozen=True)
class StrategyConsensusRunResult:
    """Dashboard-ready strategy consensus result."""

    payload: dict[str, Any]


class StrategyConsensusService:
    """Create strategy votes from reasoning output and apply consensus rules."""

    def __init__(self, registry: RepositoryRegistry) -> None:
        self.registry = registry

    def run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        scanner_run: dict[str, Any],
        reasoning_run: dict[str, Any],
        config_payload: dict[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> StrategyConsensusRunResult:
        """Persist strategy votes and one consensus output per scored reasoning row."""

        config = strategy_consensus_config_from_payload(config_payload)
        candidates = self._accepted_candidates(environment, scanner_run)
        candidates_by_id = _candidates_by_id(candidates)
        scored_outputs = self._scored_outputs(environment, reasoning_run)

        run_row = self.registry.shared().record_strategy_consensus_run(
            environment=environment,
            pipeline_run_id=pipeline_run_id,
            reasoning_run_id=reasoning_run.get("id"),
            trigger=trigger,
            status="running",
            config=config,
            vote_count=0,
            approved_count=0,
            refused_count=0,
            started_at=started_at,
            completed_at=completed_at,
        )

        votes: list[dict[str, Any]] = []
        outputs: list[dict[str, Any]] = []
        approved_count = 0
        refused_count = 0

        for output in scored_outputs:
            candidate = _candidate_for_output(output, candidates_by_id)
            if candidate is None:
                votes.append(
                    self._record_skipped_vote(
                        environment=environment,
                        run_id=run_row["id"],
                        output=output,
                        strategy_name="candidate_lookup",
                        refusal_reason="scanner candidate unavailable",
                        created_at=completed_at,
                    )
                )
                outputs.append(
                    self._record_consensus_output(
                        environment=environment,
                        run_id=run_row["id"],
                        output=output,
                        result_status="refused",
                        refusal_reason="scanner candidate unavailable",
                        signal_count=0,
                        strategy_names=(),
                        size_multiplier=Decimal("0"),
                        side=None,
                        source_payload={"output": _json_ready(output)},
                        created_at=completed_at,
                    )
                )
                refused_count += 1
                continue

            signal_votes, skipped_votes = self._strategy_votes_for_output(
                environment=environment,
                run_id=run_row["id"],
                candidate=candidate,
                output=output,
                config=config,
                config_payload=config_payload,
                created_at=completed_at,
            )
            votes.extend(skipped_votes)
            votes.extend(signal_votes)
            signals = tuple(vote["_signal"] for vote in signal_votes if vote.get("_signal"))
            consensus = apply_strategy_consensus(
                signals,
                enabled_strategies=_enabled_strategy_names(candidate, config_payload),
                consensus_rule=str(config["consensus_rule"]),
            )
            if consensus.approved:
                approved_count += 1
                status = "approved"
            else:
                refused_count += 1
                status = "refused"
            outputs.append(
                self._record_consensus_output(
                    environment=environment,
                    run_id=run_row["id"],
                    output=output,
                    result_status=status,
                    refusal_reason=consensus.refusal_reason,
                    signal_count=consensus.signal_count,
                    strategy_names=consensus.strategy_names,
                    size_multiplier=consensus.size_multiplier,
                    side=consensus.side,
                    source_payload={
                        "output": _json_ready(output),
                        "candidate": _json_ready(candidate),
                    },
                    created_at=completed_at,
                )
            )

        status = _run_status(
            scored_count=len(scored_outputs),
            approved_count=approved_count,
            refused_count=refused_count,
            accepted_vote_count=sum(1 for vote in votes if vote.get("status") == "accepted"),
        )
        run_row = self.registry.shared().update_strategy_consensus_run_result(
            consensus_run_id=run_row["id"],
            status=status,
            vote_count=len(votes),
            approved_count=approved_count,
            refused_count=refused_count,
            completed_at=completed_at,
        )
        return StrategyConsensusRunResult(
            payload=strategy_consensus_run_payload(run_row, votes, outputs)
        )

    def _accepted_candidates(
        self,
        environment: Environment,
        scanner_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        scanner_run_id = scanner_run.get("id")
        if scanner_run_id:
            try:
                rows = self.registry.shared().scanner_candidates(
                    environment=environment,
                    scanner_run_id=str(scanner_run_id),
                    status="accepted",
                )
                if rows:
                    return rows
            except PersistenceUnavailableError:
                pass
        return [
            candidate
            for candidate in scanner_run.get("candidates", [])
            if candidate.get("status") == "accepted"
        ]

    def _scored_outputs(
        self,
        environment: Environment,
        reasoning_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        reasoning_run_id = reasoning_run.get("id")
        if reasoning_run_id:
            try:
                rows = self.registry.shared().reasoning_outputs(
                    environment=environment,
                    reasoning_run_id=str(reasoning_run_id),
                    status="scored",
                )
                if rows:
                    return rows
            except PersistenceUnavailableError:
                pass
        return [
            output
            for output in reasoning_run.get("outputs", [])
            if output.get("status") == "scored"
        ]

    def _strategy_votes_for_output(
        self,
        *,
        environment: Environment,
        run_id: str,
        candidate: dict[str, Any],
        output: dict[str, Any],
        config: dict[str, Any],
        config_payload: dict[str, Any],
        created_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        venue = _venue_value(candidate, output)
        if venue == Venue.ALPACA.value:
            return self._stock_votes_for_output(
                environment=environment,
                run_id=run_id,
                candidate=candidate,
                output=output,
                config=config,
                created_at=created_at,
            )
        return self._polymarket_votes_for_output(
            environment=environment,
            run_id=run_id,
            candidate=candidate,
            output=output,
            config=config,
            config_payload=config_payload,
            created_at=created_at,
        )

    def _polymarket_votes_for_output(
        self,
        *,
        environment: Environment,
        run_id: str,
        candidate: dict[str, Any],
        output: dict[str, Any],
        config: dict[str, Any],
        config_payload: dict[str, Any],
        created_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        signals: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        model_provider = _model_provider(output)
        market_candidate = _market_candidate(candidate)
        score = _scoring_output(candidate, output)
        polymarket_config = config["polymarket"]

        if _strategy_enabled(config_payload, "arbitrage"):
            signal = ArbitrageStrategy(
                min_dislocation=_decimal(
                    polymarket_config.get("min_arbitrage_dislocation"),
                    Decimal("0.10"),
                )
            ).evaluate(market_candidate, model_provider=model_provider)
            if signal is None:
                skipped.append(
                    self._record_skipped_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        strategy_name="arbitrage",
                        refusal_reason=_arbitrage_refusal(candidate),
                        created_at=created_at,
                    )
                )
            else:
                signals.append(
                    self._persist_signal_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        signal=signal,
                        source_payload={"candidate": candidate, "strategy": "arbitrage"},
                        created_at=created_at,
                    )
                )

        if _strategy_enabled(config_payload, "convergence"):
            signal = ConvergenceStrategy(
                min_probability_gap=_decimal(
                    polymarket_config.get("min_convergence_gap"),
                    Decimal("0.07"),
                )
            ).evaluate(score, current_price=market_candidate.current_price)
            if signal is None:
                skipped.append(
                    self._record_skipped_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        strategy_name="convergence",
                        refusal_reason="convergence gap below threshold",
                        created_at=created_at,
                    )
                )
            else:
                signals.append(
                    self._persist_signal_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        signal=signal,
                        source_payload={"candidate": candidate, "strategy": "convergence"},
                        created_at=created_at,
                    )
                )

        if _strategy_enabled(config_payload, "whale_copy"):
            signal = self._whale_copy_signal(
                market_candidate=market_candidate,
                candidate=candidate,
                output=output,
                config=polymarket_config,
            )
            if signal is None:
                skipped.append(
                    self._record_skipped_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        strategy_name="whale_copy",
                        refusal_reason=_whale_copy_refusal(candidate, output),
                        created_at=created_at,
                    )
                )
            else:
                signals.append(
                    self._persist_signal_vote(
                        environment=environment,
                        run_id=run_id,
                        output=output,
                        candidate=candidate,
                        signal=signal,
                        source_payload={"candidate": candidate, "strategy": "whale_copy"},
                        created_at=created_at,
                    )
                )
        return signals, skipped

    def _stock_votes_for_output(
        self,
        *,
        environment: Environment,
        run_id: str,
        candidate: dict[str, Any],
        output: dict[str, Any],
        config: dict[str, Any],
        created_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        signals: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        strategies = set(_strategy_names(candidate))
        metrics = _mapping(candidate.get("metrics"))
        event_names = set(config["alpaca"].get("event_strategy_names", ["gap", "unusual_volume"]))

        signal = _stock_momentum_signal(candidate, output, metrics) if "momentum" in strategies else None
        if signal is None:
            skipped.append(
                self._record_skipped_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    strategy_name="momentum",
                    refusal_reason="momentum scanner threshold not met",
                    created_at=created_at,
                )
            )
        else:
            signals.append(
                self._persist_signal_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    signal=signal,
                    source_payload={"candidate": candidate, "strategy": "momentum"},
                    created_at=created_at,
                )
            )

        signal = (
            _stock_mean_reversion_signal(candidate, output, metrics)
            if "mean_reversion" in strategies
            else None
        )
        if signal is None:
            skipped.append(
                self._record_skipped_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    strategy_name="mean_reversion",
                    refusal_reason="mean-reversion scanner threshold not met",
                    created_at=created_at,
                )
            )
        else:
            signals.append(
                self._persist_signal_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    signal=signal,
                    source_payload={"candidate": candidate, "strategy": "mean_reversion"},
                    created_at=created_at,
                )
            )

        signal = _stock_event_signal(candidate, output, metrics) if strategies & event_names else None
        if signal is None:
            skipped.append(
                self._record_skipped_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    strategy_name="event",
                    refusal_reason="event or unusual-volume scanner threshold not met",
                    created_at=created_at,
                )
            )
        else:
            signals.append(
                self._persist_signal_vote(
                    environment=environment,
                    run_id=run_id,
                    output=output,
                    candidate=candidate,
                    signal=signal,
                    source_payload={"candidate": candidate, "strategy": "event"},
                    created_at=created_at,
                )
            )

        return signals, skipped

    def _whale_copy_signal(
        self,
        *,
        market_candidate: MarketCandidate,
        candidate: dict[str, Any],
        output: dict[str, Any],
        config: dict[str, Any],
    ) -> StrategySignal | None:
        metrics = _mapping(candidate.get("metrics"))
        wallets = [
            str(wallet).lower()
            for wallet in metrics.get("targetWallets", [])
            if str(wallet).strip()
        ]
        if not wallets:
            return None
        side = _model_side(output)
        if side is None:
            return None
        delay_seconds = _int(config.get("whale_copy_delay_seconds"), 0)
        action_age = _int(metrics.get("targetWalletActionAgeSeconds"), delay_seconds)
        return WhaleCopyStrategy(
            target_wallets=frozenset(wallets),
            delay_seconds=delay_seconds,
        ).evaluate(
            market_candidate,
            model_provider=_model_provider(output),
            wallet_id=wallets[0],
            action_age_seconds=action_age,
            side=side,
        )

    def _persist_signal_vote(
        self,
        *,
        environment: Environment,
        run_id: str,
        output: dict[str, Any],
        candidate: dict[str, Any],
        signal: StrategySignal,
        source_payload: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        self.registry.for_model(signal.model_provider).record_strategy_signal(signal)
        persisted = signal.model_copy(update={"persisted": True})
        row = self.registry.shared().record_strategy_vote(
            environment=environment,
            consensus_run_id=run_id,
            reasoning_output_id=_row_id(output),
            scanner_candidate_id=_scanner_candidate_id(candidate, output),
            venue=_venue_value(candidate, output),
            instrument_id=_instrument_id(candidate, output),
            model_provider=signal.model_provider,
            strategy_name=signal.strategy_name,
            direction=signal.direction.value,
            confidence=signal.confidence,
            status="accepted",
            inputs_hash=signal.inputs_hash,
            source_payload=source_payload,
            created_at=created_at,
        )
        return {**row, "_signal": persisted}

    def _record_skipped_vote(
        self,
        *,
        environment: Environment,
        run_id: str,
        output: dict[str, Any],
        strategy_name: str,
        refusal_reason: str,
        created_at: datetime,
        candidate: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.registry.shared().record_strategy_vote(
            environment=environment,
            consensus_run_id=run_id,
            reasoning_output_id=_row_id(output),
            scanner_candidate_id=_scanner_candidate_id(candidate, output),
            venue=_venue_value(candidate, output),
            instrument_id=_instrument_id(candidate, output),
            model_provider=_model_provider(output),
            strategy_name=strategy_name,
            status="skipped",
            refusal_reason=refusal_reason,
            source_payload={
                "candidate": _json_ready(candidate or {}),
                "output": _json_ready(output),
            },
            created_at=created_at,
        )

    def _record_consensus_output(
        self,
        *,
        environment: Environment,
        run_id: str,
        output: dict[str, Any],
        result_status: str,
        refusal_reason: str | None,
        signal_count: int,
        strategy_names: tuple[str, ...] | list[str],
        size_multiplier: Decimal,
        side: OrderSide | None,
        source_payload: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        return self.registry.shared().record_strategy_consensus_output(
            environment=environment,
            consensus_run_id=run_id,
            venue=str(source_payload.get("candidate", {}).get("venue") or _venue_value(None, output)),
            instrument_id=str(
                source_payload.get("candidate", {}).get("instrument_id")
                or source_payload.get("candidate", {}).get("instrumentId")
                or _instrument_id(None, output)
            ),
            model_provider=_model_provider(output),
            status=result_status,
            side=side.value if side is not None else None,
            size_multiplier=size_multiplier,
            signal_count=signal_count,
            strategy_names=list(strategy_names),
            refusal_reason=refusal_reason,
            source_payload=source_payload,
            created_at=created_at,
        )


def strategy_consensus_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    """Merge strategy consensus defaults with persisted config."""

    configured = config_payload.get("strategy_consensus")
    if not isinstance(configured, dict):
        configured = {}
    polymarket = configured.get("polymarket") if isinstance(configured.get("polymarket"), dict) else {}
    alpaca = configured.get("alpaca") if isinstance(configured.get("alpaca"), dict) else {}
    return {
        "consensus_rule": str(
            configured.get("consensus_rule", DEFAULT_STRATEGY_CONSENSUS_CONFIG["consensus_rule"])
        ),
        "polymarket": {
            **DEFAULT_STRATEGY_CONSENSUS_CONFIG["polymarket"],
            **polymarket,
        },
        "alpaca": {
            **DEFAULT_STRATEGY_CONSENSUS_CONFIG["alpaca"],
            **alpaca,
        },
    }


def strategy_consensus_run_payload(
    run_row: dict[str, Any],
    votes: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a dashboard-safe strategy consensus payload."""

    clean_votes = [_strategy_vote_view(vote) for vote in votes]
    clean_outputs = [_strategy_consensus_output_view(output) for output in outputs]
    return {
        "id": run_row.get("id"),
        "environment": run_row.get("environment"),
        "pipelineRunId": run_row.get("pipeline_run_id"),
        "reasoningRunId": run_row.get("reasoning_run_id"),
        "trigger": run_row.get("trigger"),
        "status": run_row.get("status"),
        "voteCount": int(run_row.get("vote_count", len(clean_votes))),
        "approvedCount": int(run_row.get("approved_count", 0)),
        "refusedCount": int(run_row.get("refused_count", 0)),
        "startedAt": _isoformat_or_none(run_row.get("started_at")),
        "completedAt": _isoformat_or_none(run_row.get("completed_at")),
        "votes": clean_votes,
        "outputs": clean_outputs,
    }


def _strategy_vote_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "consensusRunId": row.get("consensus_run_id"),
        "reasoningOutputId": row.get("reasoning_output_id"),
        "scannerCandidateId": row.get("scanner_candidate_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "modelProvider": row.get("model_provider"),
        "strategyName": row.get("strategy_name"),
        "direction": row.get("direction"),
        "confidence": _string_or_none(row.get("confidence")),
        "status": row.get("status"),
        "refusalReason": row.get("refusal_reason"),
        "inputsHash": row.get("inputs_hash"),
        "createdAt": _isoformat_or_none(row.get("created_at")),
    }


def _strategy_consensus_output_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "consensusRunId": row.get("consensus_run_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "modelProvider": row.get("model_provider"),
        "status": row.get("status"),
        "side": row.get("side"),
        "sizeMultiplier": _string_or_none(row.get("size_multiplier")),
        "signalCount": int(row.get("signal_count", 0)),
        "strategyNames": row.get("strategy_names", []),
        "refusalReason": row.get("refusal_reason"),
        "createdAt": _isoformat_or_none(row.get("created_at")),
    }


def _stock_momentum_signal(
    candidate: dict[str, Any],
    output: dict[str, Any],
    metrics: dict[str, Any],
) -> StrategySignal | None:
    momentum = _decimal_or_none(metrics.get("momentumPct"))
    if momentum is None or momentum == Decimal("0"):
        return None
    return _stock_signal(
        candidate,
        output,
        strategy_name="momentum",
        direction=OrderSide.BUY if momentum > 0 else OrderSide.SELL,
        confidence=_confidence_from_gap(momentum),
        inputs_hash=f"stock_momentum:{_instrument_id(candidate, output)}:{momentum}",
    )


def _stock_mean_reversion_signal(
    candidate: dict[str, Any],
    output: dict[str, Any],
    metrics: dict[str, Any],
) -> StrategySignal | None:
    deviation = _decimal_or_none(metrics.get("meanReversionPct"))
    if deviation is None or deviation == Decimal("0"):
        return None
    return _stock_signal(
        candidate,
        output,
        strategy_name="mean_reversion",
        direction=OrderSide.SELL if deviation > 0 else OrderSide.BUY,
        confidence=_confidence_from_gap(deviation),
        inputs_hash=f"stock_mean_reversion:{_instrument_id(candidate, output)}:{deviation}",
    )


def _stock_event_signal(
    candidate: dict[str, Any],
    output: dict[str, Any],
    metrics: dict[str, Any],
) -> StrategySignal | None:
    side = _model_side(output)
    if side is None:
        return None
    event_score = (
        _decimal_or_none(metrics.get("gapPct"))
        or _decimal_or_none(metrics.get("unusualVolumeRatio"))
        or Decimal("0")
    )
    return _stock_signal(
        candidate,
        output,
        strategy_name="event",
        direction=side,
        confidence=_decimal_or_none(_confidence_value(output)) or _confidence_from_gap(event_score),
        inputs_hash=f"stock_event:{_instrument_id(candidate, output)}:{_directional_signal(output)}:{event_score}",
    )


def _stock_signal(
    candidate: dict[str, Any],
    output: dict[str, Any],
    *,
    strategy_name: str,
    direction: OrderSide,
    confidence: Decimal,
    inputs_hash: str,
) -> StrategySignal:
    return StrategySignal(
        strategy_name=strategy_name,
        model_provider=_model_provider(output),
        instrument=_instrument(candidate, output),
        direction=direction,
        confidence=confidence,
        inputs_hash=inputs_hash,
    )


def _scoring_output(candidate: dict[str, Any], output: dict[str, Any]) -> ScoringOutput:
    return ScoringOutput(
        model_provider=_model_provider(output),
        prompt_version=str(output.get("prompt_version") or output.get("promptVersion") or "unknown"),
        input_summary=str(output.get("input_summary") or output.get("inputSummary") or "reasoning output"),
        output_thesis=str(output.get("output_thesis") or output.get("thesis") or "No thesis recorded."),
        confidence=_decimal(_confidence_value(output), Decimal("0.50")),
        estimated_probability=_decimal(
            output.get("estimated_probability") or output.get("estimatedProbability"),
            Decimal("0.50"),
        ),
        cost_estimate=_decimal(output.get("cost_usd") or output.get("costUsd"), Decimal("0")),
        instrument=_instrument(candidate, output),
    )


def _market_candidate(candidate: dict[str, Any]) -> MarketCandidate:
    metrics = _mapping(candidate.get("metrics"))
    source_payload = _mapping(candidate.get("source_payload") or candidate.get("sourcePayload"))
    related_price = _decimal_or_none(
        source_payload.get("relatedPrice")
        or source_payload.get("related_price")
        or metrics.get("relatedPrice")
        or metrics.get("related_price")
    )
    related_group = (
        source_payload.get("relatedGroup")
        or source_payload.get("related_group")
        or metrics.get("relatedGroup")
        or metrics.get("related_group")
    )
    return MarketCandidate(
        instrument=_instrument(candidate, None),
        current_price=_decimal(candidate.get("price"), Decimal("0.50")),
        liquidity=_decimal(candidate.get("liquidity"), Decimal("0")),
        spread=_decimal(candidate.get("spread"), Decimal("0")),
        hours_to_resolution=_decimal(
            candidate.get("hours_to_resolution") or candidate.get("hoursToResolution"),
            Decimal("24"),
        ),
        related_group=None if related_group is None else str(related_group),
        related_price=related_price,
    )


def _instrument(candidate: dict[str, Any] | None, output: dict[str, Any] | None) -> Instrument:
    venue_value = _venue_value(candidate, output)
    venue = Venue(venue_value) if venue_value in {item.value for item in Venue} else Venue.POLYMARKET_US
    if venue == Venue.ALPACA:
        symbol = str(
            (candidate or {}).get("symbol")
            or (output or {}).get("symbol")
            or _instrument_id(candidate, output).replace(f"{Venue.ALPACA.value}:", "")
            or "UNKNOWN"
        ).upper()
        return Instrument(
            venue=venue,
            instrument_type=InstrumentType.STOCK,
            symbol=symbol,
            market_id=symbol,
            outcome_id=None,
            display_name=str((candidate or {}).get("display_name") or (candidate or {}).get("displayName") or symbol),
        )
    return Instrument(
        venue=venue,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        market_id=str(
            (candidate or {}).get("market_id")
            or (candidate or {}).get("marketId")
            or _instrument_id(candidate, output)
        ),
        outcome_id=str(
            (candidate or {}).get("outcome_id")
            or (candidate or {}).get("outcomeId")
            or "unknown"
        ),
        display_name=str(
            (candidate or {}).get("display_name")
            or (candidate or {}).get("displayName")
            or _instrument_id(candidate, output)
        ),
    )


def _candidate_for_output(
    output: dict[str, Any],
    candidates_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in (
        output.get("scanner_candidate_id"),
        output.get("scannerCandidateId"),
        output.get("instrument_id"),
        output.get("instrumentId"),
    ):
        if key and str(key) in candidates_by_id:
            return candidates_by_id[str(key)]
    return None


def _candidates_by_id(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        for key in (
            candidate.get("id"),
            candidate.get("instrument_id"),
            candidate.get("instrumentId"),
            candidate.get("market_id"),
            candidate.get("marketId"),
            candidate.get("symbol"),
        ):
            if key:
                indexed[str(key)] = candidate
    return indexed


def _enabled_strategy_names(candidate: dict[str, Any], config_payload: dict[str, Any]) -> frozenset[str]:
    if _venue_value(candidate, None) == Venue.ALPACA.value:
        scanner_strategies = config_payload.get("scanner", {}).get("alpaca", {}).get("strategies", {})
        enabled = set()
        if scanner_strategies.get("momentum", {}).get("enabled", True):
            enabled.add("momentum")
        if scanner_strategies.get("mean_reversion", {}).get("enabled", True):
            enabled.add("mean_reversion")
        if scanner_strategies.get("gap", {}).get("enabled", True) or scanner_strategies.get(
            "unusual_volume", {}
        ).get("enabled", True):
            enabled.add("event")
        return frozenset(enabled or {"momentum", "mean_reversion", "event"})
    return frozenset(
        name
        for name in ("arbitrage", "convergence", "whale_copy")
        if _strategy_enabled(config_payload, name)
    )


def _strategy_enabled(config_payload: dict[str, Any], strategy_name: str) -> bool:
    strategies = config_payload.get("strategies")
    if not isinstance(strategies, dict):
        return True
    strategy = strategies.get(strategy_name)
    if not isinstance(strategy, dict):
        return True
    return bool(strategy.get("enabled", True))


def _run_status(
    *,
    scored_count: int,
    approved_count: int,
    refused_count: int,
    accepted_vote_count: int,
) -> str:
    if scored_count == 0:
        return "no_scores"
    if approved_count and refused_count:
        return "partial"
    if approved_count:
        return "approved"
    if accepted_vote_count:
        return "refused"
    return "no_votes"


def _arbitrage_refusal(candidate: dict[str, Any]) -> str:
    metrics = _mapping(candidate.get("metrics"))
    source_payload = _mapping(candidate.get("source_payload") or candidate.get("sourcePayload"))
    has_related_price = any(
        value is not None
        for value in (
            source_payload.get("relatedPrice"),
            source_payload.get("related_price"),
            metrics.get("relatedPrice"),
            metrics.get("related_price"),
        )
    )
    return "arbitrage gap below threshold" if has_related_price else "related market price unavailable"


def _whale_copy_refusal(candidate: dict[str, Any], output: dict[str, Any]) -> str:
    metrics = _mapping(candidate.get("metrics"))
    wallets = metrics.get("targetWallets", [])
    if not wallets:
        return "target wallet history unavailable"
    if _model_side(output) is None:
        return "model direction is neutral"
    return "target wallet delay not satisfied"


def _model_provider(output: dict[str, Any]) -> ModelProvider:
    value = str(output.get("model_provider") or output.get("modelProvider") or ModelProvider.OPENAI.value)
    return ModelProvider(value) if value in {item.value for item in ModelProvider} else ModelProvider.OPENAI


def _model_side(output: dict[str, Any]) -> OrderSide | None:
    signal = _directional_signal(output)
    if signal in {"buy_yes", "bullish"}:
        return OrderSide.BUY
    if signal in {"buy_no", "bearish"}:
        return OrderSide.SELL
    return None


def _directional_signal(output: dict[str, Any]) -> str:
    return str(output.get("directional_signal") or output.get("directionalSignal") or "none")


def _strategy_names(candidate: dict[str, Any]) -> list[str]:
    value = candidate.get("strategy_names") or candidate.get("strategyNames") or []
    return [str(item) for item in value if str(item).strip()]


def _venue_value(candidate: dict[str, Any] | None, output: dict[str, Any] | None) -> str:
    return str(
        (candidate or {}).get("venue")
        or (output or {}).get("venue")
        or Venue.POLYMARKET_US.value
    )


def _instrument_id(candidate: dict[str, Any] | None, output: dict[str, Any] | None) -> str:
    return str(
        (candidate or {}).get("instrument_id")
        or (candidate or {}).get("instrumentId")
        or (output or {}).get("instrument_id")
        or (output or {}).get("instrumentId")
        or "unknown"
    )


def _scanner_candidate_id(candidate: dict[str, Any] | None, output: dict[str, Any]) -> str | None:
    value = (
        (candidate or {}).get("id")
        or output.get("scanner_candidate_id")
        or output.get("scannerCandidateId")
    )
    return None if value is None else str(value)


def _row_id(row: dict[str, Any]) -> str | None:
    value = row.get("id")
    return None if value is None else str(value)


def _confidence_value(output: dict[str, Any]) -> Any:
    return output.get("confidence") or output.get("confidenceScore")


def _confidence_from_gap(gap: Decimal) -> Decimal:
    return min(Decimal("0.99"), Decimal("0.50") + abs(gap))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _decimal(value: Any, default: Decimal) -> Decimal:
    parsed = _decimal_or_none(value)
    return default if parsed is None else parsed


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _isoformat_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
