"""Recurring-funding domain contracts and deterministic identities.

REQ: REQ-FND-001, REQ-FND-002, REQ-FND-005, REQ-FND-006,
REQ-FND-007, REQ-FND-013, REQ-FND-014, REQ-FND-019, REQ-FND-020
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.domain.models import Environment, ModelProvider, Venue


class FundingDirection(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"


class FundingExecutionMode(str, Enum):
    OBSERVE = "observe"
    DIRECT = "direct"


class FundingCadence(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    LOW_BALANCE = "low_balance"


class CashFlowStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    REJECTED = "rejected"
    RETURNED = "returned"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class FundingOccurrenceStatus(str, Enum):
    EXPECTED = "expected"
    RESERVED = "reserved"
    SUBMITTED = "submitted"
    UNKNOWN = "unknown"
    MATCHED = "matched"
    MISSING = "missing"
    REFUSED = "refused"
    REJECTED = "rejected"
    RETURNED = "returned"
    FAILED = "failed"


class FundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def funding_decimal(value: Any, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if positive and parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return parsed


class FundingSchedule(FundingModel):
    """One provider-account funding expectation.

    REQ: REQ-FND-005, REQ-FND-006, REQ-FND-013, REQ-FND-019, REQ-FND-020
    """

    id: str
    enabled: bool
    venue: Venue
    model_provider: ModelProvider
    cadence: FundingCadence
    execution_mode: FundingExecutionMode
    direction: FundingDirection = FundingDirection.DEPOSIT
    amount_usd: Decimal | None = None
    target_balance_usd: Decimal | None = None
    iso_weekday: int | None = None
    day_of_month: int | None = None

    @field_validator("id")
    @classmethod
    def _id_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("funding schedule id is required")
        return normalized

    @field_validator("amount_usd", "target_balance_usd", mode="before")
    @classmethod
    def _money(cls, value: Any, info) -> Decimal | None:
        if value is None:
            return None
        return funding_decimal(value, info.field_name, positive=True)

    @model_validator(mode="after")
    def _validate_schedule(self) -> "FundingSchedule":
        if self.execution_mode == FundingExecutionMode.DIRECT:
            if self.venue != Venue.ALPACA:
                raise ValueError("Polymarket funding is observe-only")
            if self.direction != FundingDirection.DEPOSIT:
                raise ValueError("direct funding supports incoming deposits only")
        if self.cadence == FundingCadence.WEEKLY:
            if self.iso_weekday is None or not 1 <= self.iso_weekday <= 7:
                raise ValueError("weekly funding requires iso_weekday from 1 through 7")
            if self.amount_usd is None:
                raise ValueError("weekly funding requires amount_usd")
            if self.day_of_month is not None or self.target_balance_usd is not None:
                raise ValueError("weekly funding includes only iso_weekday and amount_usd")
        elif self.cadence == FundingCadence.MONTHLY:
            if self.day_of_month is None or not 1 <= self.day_of_month <= 31:
                raise ValueError("monthly funding requires day_of_month from 1 through 31")
            if self.amount_usd is None:
                raise ValueError("monthly funding requires amount_usd")
            if self.iso_weekday is not None or self.target_balance_usd is not None:
                raise ValueError("monthly funding includes only day_of_month and amount_usd")
        else:
            if self.target_balance_usd is None:
                raise ValueError("low-balance funding requires target_balance_usd")
            if self.iso_weekday is not None or self.day_of_month is not None:
                raise ValueError("low-balance funding has no calendar selector")
            if self.execution_mode == FundingExecutionMode.OBSERVE and self.amount_usd is None:
                raise ValueError("observed low-balance funding requires expected amount_usd")
        return self


class FundingConfig(FundingModel):
    """Complete audited funding configuration object.

    REQ: REQ-FND-014, REQ-FND-015, REQ-FND-018, REQ-FND-019
    """

    emergency_stop: bool = False
    direct_transfers_enabled: bool = False
    max_transfer_usd: Decimal = Decimal("0.00")
    max_monthly_transfer_usd: Decimal = Decimal("0.00")
    timezone: Literal["America/New_York"] = "America/New_York"
    missing_after_business_days: Literal[4] = 4
    schedules: tuple[FundingSchedule, ...] = ()

    @field_validator("max_transfer_usd", "max_monthly_transfer_usd", mode="before")
    @classmethod
    def _caps(cls, value: Any, info) -> Decimal:
        return funding_decimal(value, info.field_name)

    @model_validator(mode="after")
    def _unique_schedules(self) -> "FundingConfig":
        schedule_ids = [schedule.id for schedule in self.schedules]
        if len(schedule_ids) != len(set(schedule_ids)):
            raise ValueError("funding schedule IDs must be unique")
        return self


class VenueCashFlow(FundingModel):
    """Allowlisted venue cash-flow record with no bank or credential fields.

    REQ: REQ-FND-001, REQ-FND-002, REQ-FND-003
    """

    environment: Environment
    venue: Venue
    model_providers: tuple[ModelProvider, ...]
    account_ref: str
    venue_transaction_id: str
    activity_type: str
    direction: FundingDirection
    amount_usd: Decimal
    status: CashFlowStatus
    effective_at: datetime
    effective_time_precision: Literal["timestamp", "date"] = "timestamp"
    observed_at: datetime
    updated_at: datetime

    @field_validator("amount_usd", mode="before")
    @classmethod
    def _amount(cls, value: Any) -> Decimal:
        return funding_decimal(value, "amount_usd", positive=True)

    @field_validator("account_ref", "venue_transaction_id", "activity_type")
    @classmethod
    def _text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("funding cash-flow identity fields are required")
        return normalized

    @field_validator("effective_at", "observed_at", "updated_at")
    @classmethod
    def _aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("funding timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _provider_set(self) -> "VenueCashFlow":
        if not self.model_providers:
            raise ValueError("at least one model provider is required")
        object.__setattr__(
            self,
            "model_providers",
            tuple(sorted(set(self.model_providers), key=lambda item: item.value)),
        )
        return self


class FundingOccurrenceKeyInput(FundingModel):
    """Identity fields used to build a deterministic occurrence key."""

    environment: Environment
    venue: Venue
    account_ref: str
    model_provider: ModelProvider
    schedule_id: str
    due_at: datetime
    direction: FundingDirection
    execution_mode: FundingExecutionMode

    @field_validator("account_ref", "schedule_id")
    @classmethod
    def _identity_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("occurrence identity values are required")
        return normalized

    @field_validator("due_at")
    @classmethod
    def _due_time_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("due_at requires a timezone")
        return value.astimezone(UTC)


def build_funding_occurrence_key(value: FundingOccurrenceKeyInput) -> str:
    """Return a stable key for one adjusted schedule occurrence.

    REQ: REQ-FND-007, REQ-FND-016
    """

    parts = (
        value.environment.value,
        value.venue.value,
        value.account_ref,
        value.model_provider.value,
        value.schedule_id,
        value.due_at.astimezone(UTC).isoformat(),
        value.direction.value,
        value.execution_mode.value,
    )
    digest = sha256("|".join(parts).encode("utf-8")).hexdigest()
    return f"funding:{digest}"


__all__ = [
    "CashFlowStatus",
    "FundingCadence",
    "FundingConfig",
    "FundingDirection",
    "FundingExecutionMode",
    "FundingOccurrenceKeyInput",
    "FundingOccurrenceStatus",
    "FundingSchedule",
    "VenueCashFlow",
    "build_funding_occurrence_key",
    "funding_decimal",
]
