"""Deterministic strategy engine primitives.

REQ: REQ-STR-001, REQ-STR-003, REQ-STR-004, REQ-STR-005,
REQ-STR-006, REQ-STR-008
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain import (
    Instrument,
    ModelProvider,
    OrderSide,
    ScoringOutput,
    StrategySignal,
    Venue,
)
from app.venues.polymarket import VenueCallResult


DEFAULT_TRADING_LOOP_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class LoopScheduleDecision:
    """Decision for the next trading loop run.

    REQ: REQ-STR-001
    """

    should_run: bool
    interval_seconds: int
    next_run_at: datetime
    drift_seconds: int = 0
    skipped_reason: str | None = None


@dataclass(frozen=True)
class MarketCandidate:
    """Market candidate before deterministic filtering and scoring.

    REQ: REQ-STR-003, REQ-STR-004, REQ-STR-006
    """

    instrument: Instrument
    current_price: Decimal
    liquidity: Decimal
    active: bool = True
    stale_data: bool = False
    spread: Decimal = Decimal("0")
    hours_to_resolution: Decimal = Decimal("24")
    related_group: str | None = None
    related_price: Decimal | None = None


@dataclass(frozen=True)
class CandidateFilterConfig:
    """Deterministic filters applied before LLM scoring.

    REQ: REQ-STR-003
    """

    enabled_venues: frozenset[Venue]
    min_liquidity: Decimal = Decimal("100")
    max_spread: Decimal = Decimal("0.05")
    min_hours_to_resolution: Decimal = Decimal("1")
    max_hours_to_resolution: Decimal = Decimal("720")
    symbol_universe: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateFilterResult:
    """Filtered candidates plus first refusal reason per rejected input.

    REQ: REQ-STR-003
    """

    candidates: tuple[MarketCandidate, ...]
    refusal_reasons: tuple[str, ...] = ()

    @property
    def scoring_instruments(self) -> tuple[Instrument, ...]:
        """Return instruments to send to LLM scoring.

        REQ: REQ-STR-003
        """

        return tuple(candidate.instrument for candidate in self.candidates)


@dataclass(frozen=True)
class StrategyConsensusResult:
    """Consensus result before risk and execution.

    REQ: REQ-STR-008
    """

    approved: bool
    side: OrderSide | None = None
    size_multiplier: Decimal = Decimal("0")
    refusal_reason: str | None = None
    signal_count: int = 0
    strategy_names: tuple[str, ...] = ()


class ArbitrageStrategy:
    """Related-market price dislocation strategy.

    REQ: REQ-STR-004
    """

    def __init__(self, *, min_dislocation: Decimal = Decimal("0.10")) -> None:
        self.min_dislocation = _as_decimal(min_dislocation)

    def evaluate(
        self,
        candidate: MarketCandidate,
        *,
        model_provider: ModelProvider,
    ) -> StrategySignal | None:
        """Return a signal when related-market dislocation is large enough.

        REQ: REQ-STR-004
        """

        if (
            candidate.stale_data
            or candidate.related_group is None
            or candidate.related_price is None
        ):
            return None
        gap = candidate.related_price - candidate.current_price
        if abs(gap) < self.min_dislocation:
            return None
        return _build_signal(
            strategy_name="arbitrage",
            model_provider=model_provider,
            instrument=candidate.instrument,
            direction=OrderSide.BUY if gap > 0 else OrderSide.SELL,
            confidence=_confidence_from_gap(gap),
            inputs_hash=(
                f"arbitrage:{candidate.instrument.identifier}:"
                f"{candidate.related_group}:{candidate.current_price}:"
                f"{candidate.related_price}"
            ),
        )


class ConvergenceStrategy:
    """Model-estimate convergence strategy.

    REQ: REQ-STR-005
    """

    def __init__(self, *, min_probability_gap: Decimal = Decimal("0.10")) -> None:
        self.min_probability_gap = _as_decimal(min_probability_gap)

    def evaluate(
        self,
        score: ScoringOutput,
        *,
        current_price: Decimal,
    ) -> StrategySignal | None:
        """Return a signal when model estimate diverges from market price.

        REQ: REQ-STR-005
        """

        midpoint = _as_decimal(current_price)
        gap = score.estimated_probability - midpoint
        if abs(gap) < self.min_probability_gap:
            return None
        return _build_signal(
            strategy_name="convergence",
            model_provider=score.model_provider,
            instrument=score.instrument,
            direction=OrderSide.BUY if gap > 0 else OrderSide.SELL,
            confidence=score.confidence,
            inputs_hash=(
                f"convergence:{score.instrument.identifier}:"
                f"{score.estimated_probability}:{midpoint}"
            ),
        )


class WhaleCopyStrategy:
    """Target-wallet delayed copy strategy.

    REQ: REQ-STR-006
    """

    def __init__(
        self,
        *,
        target_wallets: frozenset[str],
        delay_seconds: int = 60,
    ) -> None:
        self.target_wallets = frozenset(
            wallet.strip() for wallet in target_wallets if wallet.strip()
        )
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        self.delay_seconds = delay_seconds

    def evaluate(
        self,
        candidate: MarketCandidate,
        *,
        model_provider: ModelProvider,
        wallet_id: str,
        action_age_seconds: int,
        side: OrderSide,
    ) -> StrategySignal | None:
        """Return a signal for configured wallet activity after the delay.

        REQ: REQ-STR-006
        """

        if candidate.stale_data:
            return None
        if wallet_id not in self.target_wallets:
            return None
        if action_age_seconds < self.delay_seconds:
            return None
        return _build_signal(
            strategy_name="whale_copy",
            model_provider=model_provider,
            instrument=candidate.instrument,
            direction=side,
            confidence=Decimal("0.65"),
            inputs_hash=(
                f"whale_copy:{candidate.instrument.identifier}:"
                f"{wallet_id}:{action_age_seconds}:{side.value}"
            ),
        )


def default_trading_loop_interval_seconds() -> int:
    """Return the approved default trading loop interval.

    REQ: REQ-STR-001
    """

    return DEFAULT_TRADING_LOOP_INTERVAL_SECONDS


def schedule_next_trading_loop(
    *,
    last_started_at: datetime,
    now: datetime,
    interval_seconds: int = DEFAULT_TRADING_LOOP_INTERVAL_SECONDS,
    running: bool = False,
) -> LoopScheduleDecision:
    """Determine whether the trading loop should run without overlap.

    REQ: REQ-STR-001
    """

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    next_run_at = last_started_at + timedelta(seconds=interval_seconds)
    if running:
        return LoopScheduleDecision(
            should_run=False,
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
            skipped_reason="trading loop already running",
        )
    if now < next_run_at:
        return LoopScheduleDecision(
            should_run=False,
            interval_seconds=interval_seconds,
            next_run_at=next_run_at,
        )
    return LoopScheduleDecision(
        should_run=True,
        interval_seconds=interval_seconds,
        next_run_at=next_run_at,
        drift_seconds=max(0, int((now - next_run_at).total_seconds())),
    )


def filter_strategy_candidates(
    candidates: tuple[MarketCandidate, ...],
    config: CandidateFilterConfig,
) -> CandidateFilterResult:
    """Apply deterministic filters before any LLM scoring request.

    REQ: REQ-STR-003
    """

    accepted: list[MarketCandidate] = []
    refusal_reasons: list[str] = []
    symbol_universe = {symbol.upper() for symbol in config.symbol_universe}

    for candidate in candidates:
        refusal = _candidate_refusal(candidate, config, symbol_universe)
        if refusal is not None:
            refusal_reasons.append(refusal)
            continue
        accepted.append(candidate)
    return CandidateFilterResult(
        candidates=tuple(accepted),
        refusal_reasons=tuple(refusal_reasons),
    )


def apply_strategy_consensus(
    signals: tuple[StrategySignal, ...],
    *,
    enabled_strategies: frozenset[str],
    consensus_rule: str = "default",
) -> StrategyConsensusResult:
    """Apply default strategy consensus before creating an order decision.

    REQ: REQ-STR-008
    """

    validation = validate_consensus_rule(consensus_rule)
    if not validation.ok:
        return StrategyConsensusResult(
            approved=False,
            refusal_reason=validation.refusal_reason,
        )

    eligible = tuple(
        signal
        for signal in signals
        if signal.persisted and signal.strategy_name in enabled_strategies
    )
    if not eligible:
        return StrategyConsensusResult(
            approved=False,
            refusal_reason="no directional strategy consensus",
        )

    sides = {signal.direction for signal in eligible}
    if len(sides) > 1:
        return StrategyConsensusResult(
            approved=False,
            refusal_reason="strategy direction conflict",
            signal_count=len(eligible),
            strategy_names=tuple(signal.strategy_name for signal in eligible),
        )

    side = eligible[0].direction
    size_multiplier = Decimal("1") if len(eligible) >= 2 else Decimal("0.5")
    return StrategyConsensusResult(
        approved=True,
        side=side,
        size_multiplier=size_multiplier,
        signal_count=len(eligible),
        strategy_names=tuple(signal.strategy_name for signal in eligible),
    )


def validate_consensus_rule(consensus_rule: str) -> VenueCallResult:
    """Validate consensus rule names before a trading loop uses them.

    REQ: REQ-STR-008
    """

    if consensus_rule != "default":
        return VenueCallResult(
            ok=False,
            refusal_reasons=("unsupported consensus rule",),
            payload={"consensus_rule": consensus_rule},
        )
    return VenueCallResult(ok=True, payload={"consensus_rule": consensus_rule})


def _candidate_refusal(
    candidate: MarketCandidate,
    config: CandidateFilterConfig,
    symbol_universe: set[str],
) -> str | None:
    if candidate.instrument.venue not in config.enabled_venues:
        return "venue disabled"
    if not candidate.active:
        return "market inactive"
    if candidate.stale_data:
        return "stale market data"
    if candidate.liquidity < config.min_liquidity:
        return "liquidity below minimum"
    if candidate.spread > config.max_spread:
        return "spread too wide"
    if candidate.hours_to_resolution < config.min_hours_to_resolution:
        return "resolution too near"
    if candidate.hours_to_resolution > config.max_hours_to_resolution:
        return "resolution too far"
    if (
        symbol_universe
        and candidate.instrument.venue == Venue.ALPACA
        and (candidate.instrument.symbol or "").upper() not in symbol_universe
    ):
        return "symbol outside universe"
    return None


def _build_signal(
    *,
    strategy_name: str,
    model_provider: ModelProvider,
    instrument: Instrument,
    direction: OrderSide,
    confidence: Decimal,
    inputs_hash: str,
) -> StrategySignal:
    return StrategySignal(
        strategy_name=strategy_name,
        model_provider=model_provider,
        instrument=instrument,
        direction=direction,
        confidence=confidence,
        inputs_hash=inputs_hash,
        persisted=False,
    )


def _confidence_from_gap(gap: Decimal) -> Decimal:
    return min(Decimal("0.99"), Decimal("0.50") + abs(gap))


def _as_decimal(value: Any) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal
