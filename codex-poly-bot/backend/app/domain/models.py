"""Pure domain models and validation.

REQ: REQ-VEN-001, REQ-ALP-001, REQ-ALP-002, REQ-DB-004, REQ-DB-005,
REQ-LLM-003, REQ-STR-007, REQ-EXE-008, REQ-EXE-016, REQ-EXT-001,
REQ-CMP-001, REQ-CMP-003, REQ-OBS-001, REQ-KAL-001
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Venue(str, Enum):
    """Supported trading venues.

    REQ: REQ-VEN-001, REQ-ALP-001, REQ-KAL-001
    """

    POLYMARKET_US = "polymarket_us"
    POLYMARKET_INTERNATIONAL = "polymarket_international"
    ALPACA = "alpaca"
    KALSHI = "kalshi"


class InstrumentType(str, Enum):
    """Supported instrument types.

    REQ: REQ-ALP-001, REQ-ALP-002, REQ-CMP-001
    """

    PREDICTION_MARKET = "prediction_market"
    STOCK = "stock"
    ETF = "etf"


class ModelProvider(str, Enum):
    """Supported model providers."""

    OPENAI = "openai"
    CLAUDE = "claude"


class Environment(str, Enum):
    """Runtime environments."""

    LOCAL = "local"
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class OrderType(str, Enum):
    """Order types supported by the domain."""

    LIMIT = "limit"
    MARKET = "market"


class OrderSide(str, Enum):
    """Order sides supported by the domain."""

    BUY = "buy"
    SELL = "sell"


class PositionState(str, Enum):
    """Position states recorded by persistence."""

    OPEN = "open"
    CLOSED = "closed"
    EXITING = "exiting"


class OrderEventType(str, Enum):
    """Order lifecycle events.

    REQ: REQ-EXE-016
    """

    REFUSED = "refused"
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELED = "canceled"
    FAILED = "failed"


class ExitTriggerType(str, Enum):
    """Exit trigger categories.

    REQ: REQ-EXT-001
    """

    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    VOLUME_SPIKE = "volume_spike"
    STALE_THESIS = "stale_thesis"
    STALE_POSITION = "stale_position"
    MARKET_HOURS = "market_hours"


class DomainModel(BaseModel):
    """Base model with strict enum and Decimal handling."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not decimal.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return decimal


def _positive(value: Decimal, field_name: str) -> Decimal:
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _non_negative(value: Decimal, field_name: str) -> Decimal:
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _probability(value: Decimal, field_name: str) -> Decimal:
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


def supported_venues() -> set[Venue]:
    """Return all venues supported by v1.

    REQ: REQ-VEN-001, REQ-ALP-001, REQ-KAL-001
    """

    return {
        Venue.POLYMARKET_US,
        Venue.POLYMARKET_INTERNATIONAL,
        Venue.ALPACA,
        Venue.KALSHI,
    }


def supported_polymarket_venues() -> set[Venue]:
    """Return supported Polymarket venues.

    REQ: REQ-VEN-001
    """

    return {Venue.POLYMARKET_US, Venue.POLYMARKET_INTERNATIONAL}


def supported_prediction_market_venues() -> set[Venue]:
    """Return every supported prediction-market venue.

    REQ: REQ-VEN-001, REQ-KAL-001
    """

    return {*supported_polymarket_venues(), Venue.KALSHI}


class Instrument(DomainModel):
    """Venue-neutral tradable identifier.

    REQ: REQ-VEN-001, REQ-ALP-001, REQ-ALP-002, REQ-DB-004, REQ-CMP-001
    """

    venue: Venue
    instrument_type: InstrumentType
    display_name: str
    symbol: str | None = None
    market_id: str | None = None
    outcome_id: str | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name is required")
        return value

    @model_validator(mode="after")
    def _validate_identifiers(self) -> Instrument:
        if self.venue == Venue.ALPACA:
            if self.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
                raise ValueError("Alpaca v1 instruments must be stocks or ETFs")
            if not self.symbol or not self.symbol.strip():
                raise ValueError("Alpaca instruments require symbol")
            return self
        if self.instrument_type != InstrumentType.PREDICTION_MARKET:
            raise ValueError("prediction-market venue instruments must be prediction markets")
        if not self.market_id or not self.market_id.strip() or not self.outcome_id or not self.outcome_id.strip():
            raise ValueError("prediction-market instruments require market_id and outcome_id")
        return self

    @property
    def identifier(self) -> str:
        """Return the venue-native identifier."""

        if self.venue == Venue.ALPACA:
            return self.symbol or ""
        return f"{self.market_id}:{self.outcome_id}"


def eligible_alpaca_instruments(instruments: list[Instrument]) -> list[Instrument]:
    """Return only Alpaca stock and ETF instruments.

    REQ: REQ-ALP-001, REQ-ALP-002
    """

    return [
        instrument
        for instrument in instruments
        if instrument.venue == Venue.ALPACA
        and instrument.instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}
    ]


class TradeDecision(DomainModel):
    """Persistable trade decision payload.

    REQ: REQ-DB-004
    """

    model_provider: ModelProvider
    venue: Venue
    environment: Environment
    instrument: Instrument
    signal_inputs: dict[str, Any]
    decision: str
    order_type: OrderType
    size: Decimal
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("size", mode="before")
    @classmethod
    def _size_decimal(cls, value: Any) -> Decimal:
        return _positive(_decimal(value, "size"), "size")

    @field_validator("decision")
    @classmethod
    def _decision_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("decision is required")
        return value

    @model_validator(mode="after")
    def _signals_required(self) -> TradeDecision:
        if not self.signal_inputs:
            raise ValueError("signal_inputs are required")
        if self.instrument.venue != self.venue:
            raise ValueError("decision venue must match instrument venue")
        return self


class PositionTransition(DomainModel):
    """Position state transition payload.

    REQ: REQ-DB-005
    """

    position_id: str
    prior_state: PositionState
    new_state: PositionState
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("position_id", "reason")
    @classmethod
    def _text_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value

    @field_validator("realized_pnl", "unrealized_pnl", mode="before")
    @classmethod
    def _pnl_decimal(cls, value: Any) -> Decimal:
        return _decimal(value, "pnl")

    @model_validator(mode="after")
    def _state_changes(self) -> PositionTransition:
        if self.prior_state == self.new_state:
            raise ValueError("position transition must change state")
        return self


class ScoringOutput(DomainModel):
    """One LLM scoring output.

    REQ: REQ-LLM-003
    """

    model_provider: ModelProvider
    prompt_version: str
    input_summary: str
    output_thesis: str
    confidence: Decimal
    estimated_probability: Decimal
    cost_estimate: Decimal
    instrument: Instrument
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("prompt_version", "input_summary", "output_thesis")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text fields are required")
        return value

    @field_validator("confidence", "estimated_probability", mode="before")
    @classmethod
    def _probability_fields(cls, value: Any) -> Decimal:
        return _probability(_decimal(value, "probability"), "probability")

    @field_validator("cost_estimate", mode="before")
    @classmethod
    def _cost_decimal(cls, value: Any) -> Decimal:
        return _non_negative(_decimal(value, "cost_estimate"), "cost_estimate")


class StrategySignal(DomainModel):
    """Strategy signal recorded before execution decisions.

    REQ: REQ-STR-007
    """

    strategy_name: str
    model_provider: ModelProvider
    instrument: Instrument
    direction: OrderSide
    confidence: Decimal
    inputs_hash: str
    persisted: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("strategy_name", "inputs_hash")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy signal text fields are required")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> Decimal:
        return _probability(_decimal(value, "confidence"), "confidence")


def ensure_signals_persisted(signals: list[StrategySignal]) -> bool:
    """Return whether all strategy signals are persisted before decision creation.

    REQ: REQ-STR-007
    """

    return bool(signals) and all(signal.persisted for signal in signals)


class RiskDecision(DomainModel):
    """Risk sizing result.

    REQ: REQ-EXE-008
    """

    approved: bool
    approved_notional: Decimal | None = None
    refusal_reason: str | None = None

    @field_validator("approved_notional", mode="before")
    @classmethod
    def _approved_notional_decimal(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        return _positive(_decimal(value, "approved_notional"), "approved_notional")

    @model_validator(mode="after")
    def _validate_result(self) -> RiskDecision:
        if self.approved and self.approved_notional is None:
            raise ValueError("approved risk decisions require approved_notional")
        if not self.approved and not self.refusal_reason:
            raise ValueError("refused risk decisions require refusal_reason")
        return self


def kelly_sized_notional(
    *,
    probability: Decimal | str | None,
    decimal_odds: Decimal | str | None,
    bankroll: Decimal | str | None,
    risk_cap: Decimal | str | None,
) -> RiskDecision:
    """Calculate Kelly notional and cap it by risk limits.

    REQ: REQ-EXE-008
    """

    if probability is None or decimal_odds is None or bankroll is None or risk_cap is None:
        return RiskDecision(approved=False, refusal_reason="missing Kelly sizing input")
    p = _probability(_decimal(probability, "probability"), "probability")
    odds = _positive(_decimal(decimal_odds, "decimal_odds"), "decimal_odds")
    capital = _positive(_decimal(bankroll, "bankroll"), "bankroll")
    cap = _positive(_decimal(risk_cap, "risk_cap"), "risk_cap")
    edge = odds - Decimal("1")
    if edge <= 0:
        return RiskDecision(approved=False, refusal_reason="decimal odds must exceed 1")
    fraction = ((edge * p) - (Decimal("1") - p)) / edge
    if fraction <= 0:
        return RiskDecision(approved=False, refusal_reason="Kelly size is non-positive")
    return RiskDecision(approved=True, approved_notional=min(capital * fraction, cap))


class OrderEvent(DomainModel):
    """Order lifecycle event shown in dashboard status.

    REQ: REQ-EXE-016
    """

    order_id: str
    event_type: OrderEventType
    venue: Venue
    model_provider: ModelProvider
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("order_id", "message")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("order event text fields are required")
        return value


class EventPersistenceResult(DomainModel):
    """Result of persisting an order event.

    REQ: REQ-EXE-016
    """

    event: OrderEvent
    persisted: bool
    dashboard_visible: bool
    degraded: bool
    error_message: str | None = None

    @model_validator(mode="after")
    def _degraded_has_error(self) -> EventPersistenceResult:
        if self.degraded and not self.error_message:
            raise ValueError("degraded event persistence requires error_message")
        return self


def record_order_event(event: OrderEvent, *, persistence_ok: bool) -> EventPersistenceResult:
    """Build an order event persistence result.

    REQ: REQ-EXE-016
    """

    if persistence_ok:
        return EventPersistenceResult(
            event=event,
            persisted=True,
            dashboard_visible=True,
            degraded=False,
        )
    return EventPersistenceResult(
        event=event,
        persisted=False,
        dashboard_visible=True,
        degraded=True,
        error_message="order event persistence failed",
    )


class PositionSnapshot(DomainModel):
    """Open position snapshot used by exit monitoring and comparison metrics."""

    position_id: str
    instrument: Instrument
    state: PositionState
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")

    @field_validator("position_id")
    @classmethod
    def _position_id_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("position_id is required")
        return value

    @field_validator("realized_pnl", "unrealized_pnl", mode="before")
    @classmethod
    def _pnl_decimal(cls, value: Any) -> Decimal:
        return _decimal(value, "pnl")


class ExitTrigger(DomainModel):
    """Configured or observed exit trigger.

    REQ: REQ-EXT-001
    """

    trigger_type: ExitTriggerType
    position_id: str
    threshold: Decimal
    observed_value: Decimal
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("position_id", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("exit trigger text fields are required")
        return value

    @field_validator("threshold", "observed_value", mode="before")
    @classmethod
    def _trigger_decimal(cls, value: Any) -> Decimal:
        return _decimal(value, "trigger value")


def evaluate_exit_triggers(
    positions: list[PositionSnapshot],
    triggers: list[ExitTrigger],
) -> list[ExitTrigger]:
    """Return exit triggers applicable to open positions.

    REQ: REQ-EXT-001
    """

    open_position_ids = {position.position_id for position in positions if position.state == PositionState.OPEN}
    return [trigger for trigger in triggers if trigger.position_id in open_position_ids]


class ComparisonMetric(DomainModel):
    """Calculated comparison metric or unavailable marker.

    REQ: REQ-CMP-001, REQ-CMP-003
    """

    metric_name: str
    model_provider: ModelProvider
    venue: Venue
    environment: Environment
    instrument_type: InstrumentType
    value: Decimal | None = None
    unavailable_reason: str | None = None
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("metric_name")
    @classmethod
    def _metric_name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("metric_name is required")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def _value_decimal(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        return _decimal(value, "metric value")

    @model_validator(mode="after")
    def _value_or_reason(self) -> ComparisonMetric:
        if self.value is None and not self.unavailable_reason:
            raise ValueError("unavailable metrics require unavailable_reason")
        return self


def metric_group_key(metric: ComparisonMetric) -> tuple[ModelProvider, Venue, Environment, InstrumentType]:
    """Return grouping key for comparison metrics.

    REQ: REQ-CMP-001
    """

    return (metric.model_provider, metric.venue, metric.environment, metric.instrument_type)


def calculate_return_to_risk(
    *,
    model_provider: ModelProvider,
    venue: Venue,
    environment: Environment,
    instrument_type: InstrumentType,
    total_return: Decimal | str | None,
    max_drawdown: Decimal | str | None,
) -> ComparisonMetric:
    """Calculate return-to-risk with unavailable handling.

    REQ: REQ-CMP-003
    """

    if total_return is None or max_drawdown is None:
        return ComparisonMetric(
            metric_name="return_to_risk",
            model_provider=model_provider,
            venue=venue,
            environment=environment,
            instrument_type=instrument_type,
            unavailable_reason="missing return or drawdown",
        )
    drawdown = _decimal(max_drawdown, "max_drawdown")
    if drawdown == 0:
        return ComparisonMetric(
            metric_name="return_to_risk",
            model_provider=model_provider,
            venue=venue,
            environment=environment,
            instrument_type=instrument_type,
            unavailable_reason="drawdown is zero",
        )
    return ComparisonMetric(
        metric_name="return_to_risk",
        model_provider=model_provider,
        venue=venue,
        environment=environment,
        instrument_type=instrument_type,
        value=_decimal(total_return, "total_return") / abs(drawdown),
    )


SECRET_MARKERS = ("secret", "token", "key", "password", "private")


def redact_metadata_value(value: Any) -> Any:
    """Redact nested structured log metadata values.

    REQ: REQ-OBS-001
    """

    if isinstance(value, dict):
        return redact_metadata(value)
    if isinstance(value, list):
        return [redact_metadata_value(item) for item in value]
    return value


def redact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Redact secret-like structured log metadata.

    REQ: REQ-OBS-001
    """

    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(marker in key.lower() for marker in SECRET_MARKERS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = redact_metadata_value(value)
    return redacted


class StructuredLogEvent(DomainModel):
    """Structured log event emitted by services.

    REQ: REQ-OBS-001
    """

    event_name: str
    correlation_id: str
    environment: Environment
    venue: Venue | None = None
    model_provider: ModelProvider | None = None
    entity_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_name", "correlation_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("structured log text fields are required")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _redacted_metadata(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("metadata must be an object")
        return redact_metadata(value)
