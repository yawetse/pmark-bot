"""Recurring funding schedules, cash-flow persistence, and reconciliation.

REQ: REQ-FND-001 through REQ-FND-012, REQ-FND-016 through REQ-FND-020
"""

from __future__ import annotations

import calendar
import base64
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Any, Iterable
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.db import (
    PersistenceUnavailableError,
    RepositoryRegistry,
    SHARED_CONFIG_USERNAME,
    UnitOfWork,
    normalize_config_username,
)
from app.db.schema import SHARED_SCHEMA
from app.adapters.aws.ses import EmailMessage
from app.domain import (
    CashFlowStatus,
    Environment,
    FundingCadence,
    FundingConfig,
    FundingDirection,
    FundingExecutionMode,
    FundingOccurrenceKeyInput,
    FundingOccurrenceStatus,
    FundingSchedule,
    ModelProvider,
    Venue,
    VenueCashFlow,
    build_funding_occurrence_key,
    funding_decimal,
)


EASTERN = ZoneInfo("America/New_York")
VENUE_CASH_FLOWS_TABLE = f"{SHARED_SCHEMA}.venue_cash_flows"
FUNDING_OCCURRENCES_TABLE = f"{SHARED_SCHEMA}.funding_occurrences"
FUNDING_SYNC_STATE_TABLE = f"{SHARED_SCHEMA}.funding_sync_state"
FUNDING_ALERT_OUTBOX_TABLE = f"{SHARED_SCHEMA}.funding_alert_outbox"
FUNDING_AMOUNT_QUANTUM = Decimal("0.00000001")
FUNDING_MATCH_TOLERANCE = Decimal("0.01")
FUNDING_API_LIMIT = 100
FUNDING_MAX_API_LIMIT = 500
FUNDING_MAX_HISTORY_DAYS = 365
FUNDING_BOUNDARY_FRESHNESS_SECONDS = 120
_TERMINAL_CASH_STATUSES = {
    CashFlowStatus.COMPLETED.value,
    CashFlowStatus.REJECTED.value,
    CashFlowStatus.RETURNED.value,
    CashFlowStatus.FAILED.value,
    CashFlowStatus.CANCELED.value,
}


@dataclass(frozen=True)
class AdjustedTradingPerformance:
    beginning_value_usd: Decimal
    ending_value_usd: Decimal
    completed_deposits_usd: Decimal
    completed_withdrawals_usd: Decimal
    adjusted_pnl_usd: Decimal | None
    weighted_denominator_usd: Decimal | None
    modified_dietz_return: Decimal | None
    unavailable_reason: str | None = None


def _money(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(FUNDING_AMOUNT_QUANTUM, rounding=ROUND_HALF_UP)


def funding_account_ref(venue: Venue, account_identity: str) -> str:
    """Return a stable, sanitized account reference.

    REQ: REQ-FND-002, REQ-FND-013
    """

    identity = account_identity.strip()
    if not identity:
        raise ValueError("account identity is required")
    digest = sha256(f"{venue.value}|{identity}".encode("utf-8")).hexdigest()
    return f"{venue.value}-{digest[:12]}"


def _observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + 7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)


def us_federal_holidays(year: int) -> set[date]:
    """Return observed federal holidays used by the funding calendar."""

    holidays = {
        _observed_fixed_holiday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(date(year, 6, 19)),
        _observed_fixed_holiday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_fixed_holiday(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(date(year, 12, 25)),
    }
    holidays.add(_observed_fixed_holiday(date(year + 1, 1, 1)))
    return holidays


def is_business_day(value: date) -> bool:
    return value.weekday() < 5 and value not in (
        us_federal_holidays(value.year)
        | us_federal_holidays(value.year - 1)
    )


def adjust_to_business_day(value: date) -> date:
    adjusted = value
    while not is_business_day(adjusted):
        adjusted += timedelta(days=1)
    return adjusted


def add_business_days(value: date | datetime, count: int) -> date | datetime:
    """Move forward by business days while preserving Eastern wall-clock time."""

    if count < 0:
        raise ValueError("business day count cannot be negative")
    local_value = value.astimezone(EASTERN) if isinstance(value, datetime) else None
    current_date = local_value.date() if local_value is not None else value
    remaining = count
    while remaining:
        current_date += timedelta(days=1)
        if is_business_day(current_date):
            remaining -= 1
    if isinstance(value, datetime):
        assert local_value is not None
        local_time = time(
            local_value.hour,
            local_value.minute,
            local_value.second,
            local_value.microsecond,
        )
        return datetime.combine(current_date, local_time, tzinfo=EASTERN).astimezone(UTC)
    return current_date


def schedule_due_at(schedule: FundingSchedule, period_anchor: date) -> datetime:
    """Resolve one weekly or monthly due time at 09:00 Eastern.

    REQ: REQ-FND-005
    """

    if schedule.cadence == FundingCadence.MONTHLY:
        assert schedule.day_of_month is not None
        day = min(schedule.day_of_month, calendar.monthrange(period_anchor.year, period_anchor.month)[1])
        due_date = date(period_anchor.year, period_anchor.month, day)
    elif schedule.cadence == FundingCadence.WEEKLY:
        assert schedule.iso_weekday is not None
        due_date = period_anchor + timedelta(
            days=(schedule.iso_weekday - period_anchor.isoweekday()) % 7
        )
    else:
        raise ValueError("low-balance schedules do not have a calendar due time")
    due_date = adjust_to_business_day(due_date)
    return datetime.combine(due_date, time(9, 0), tzinfo=EASTERN).astimezone(UTC)


def calculate_low_balance_gap(
    target_balance: Decimal | str,
    confirmed_buying_power: Decimal | str,
    *,
    snapshot_fresh: bool = True,
) -> Decimal:
    """Return the positive gap from a fresh venue-confirmed balance.

    REQ: REQ-FND-006
    """

    if not snapshot_fresh:
        raise ValueError("fresh confirmed portfolio snapshot is required")
    target = funding_decimal(target_balance, "target_balance", positive=True)
    buying_power = funding_decimal(confirmed_buying_power, "confirmed_buying_power")
    return max(Decimal("0"), target - buying_power)


def adjusted_trading_performance(
    *,
    beginning_value: Decimal | str,
    ending_value: Decimal | str,
    cash_flows: Iterable[tuple[datetime, FundingDirection, Decimal]],
    period_start: datetime,
    period_end: datetime,
    boundaries_fresh: bool = True,
) -> AdjustedTradingPerformance:
    """Calculate cash-flow-adjusted P&L and Modified Dietz return.

    REQ: REQ-FND-011, REQ-FND-012
    """

    beginning = _money(beginning_value)
    ending = _money(ending_value)
    if period_start.tzinfo is None or period_end.tzinfo is None or period_end <= period_start:
        raise ValueError("performance period requires ordered timezone-aware boundaries")
    if not boundaries_fresh:
        return AdjustedTradingPerformance(
            beginning,
            ending,
            Decimal("0"),
            Decimal("0"),
            None,
            None,
            None,
            "boundary_snapshot_unavailable",
        )
    duration = Decimal(str((period_end - period_start).total_seconds()))
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    net_flows = Decimal("0")
    weighted_flows = Decimal("0")
    for effective_at, direction, raw_amount in cash_flows:
        if effective_at.tzinfo is None or not period_start <= effective_at <= period_end:
            continue
        amount = funding_decimal(raw_amount, "cash_flow_amount", positive=True)
        signed = amount if direction == FundingDirection.DEPOSIT else -amount
        if direction == FundingDirection.DEPOSIT:
            deposits += amount
        else:
            withdrawals += amount
        remaining = Decimal(str((period_end - effective_at).total_seconds()))
        weight = remaining / duration
        net_flows += signed
        weighted_flows += signed * weight
    adjusted_pnl = _money(ending - beginning - net_flows)
    denominator = _money(beginning + weighted_flows)
    if denominator <= 0:
        return AdjustedTradingPerformance(
            beginning,
            ending,
            _money(deposits),
            _money(withdrawals),
            adjusted_pnl,
            denominator,
            None,
            "non_positive_modified_dietz_denominator",
        )
    return AdjustedTradingPerformance(
        beginning,
        ending,
        _money(deposits),
        _money(withdrawals),
        adjusted_pnl,
        denominator,
        (adjusted_pnl / denominator).quantize(FUNDING_AMOUNT_QUANTUM, rounding=ROUND_HALF_UP),
    )


def _parse_time(value: Any, *, observed_at: datetime) -> tuple[datetime, str]:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return observed_at.astimezone(UTC), "timestamp"
        if len(text) == 10:
            parsed_date = date.fromisoformat(text)
            return (
                datetime.combine(parsed_date, time(9, 0), tzinfo=EASTERN).astimezone(UTC),
                "date",
            )
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC), "timestamp"


def _activity_amount(raw: Any) -> Decimal | None:
    if isinstance(raw, dict):
        raw = raw.get("value") or raw.get("amount")
    try:
        amount = abs(Decimal(str(raw)))
    except Exception:
        return None
    return amount if amount > 0 and amount.is_finite() else None


def _cash_status(raw: Any) -> CashFlowStatus:
    value = str(raw or "completed").strip().lower()
    mapping = {
        "complete": CashFlowStatus.COMPLETED,
        "completed": CashFlowStatus.COMPLETED,
        "cleared": CashFlowStatus.COMPLETED,
        "executed": CashFlowStatus.COMPLETED,
        "settled": CashFlowStatus.COMPLETED,
        "pending": CashFlowStatus.PENDING,
        "rejected": CashFlowStatus.REJECTED,
        "returned": CashFlowStatus.RETURNED,
        "failed": CashFlowStatus.FAILED,
        "canceled": CashFlowStatus.CANCELED,
        "cancelled": CashFlowStatus.CANCELED,
    }
    return mapping.get(value, CashFlowStatus.UNKNOWN)


def normalize_alpaca_funding_activity(
    raw: dict[str, Any],
    *,
    environment: Environment,
    provider: ModelProvider,
    account_ref: str,
    observed_at: datetime,
) -> VenueCashFlow | None:
    """Normalize Alpaca CSD, CSW, and explicitly directed TRANS activity."""

    activity_type = str(raw.get("activity_type") or raw.get("type") or "").strip().upper()
    direction: FundingDirection | None = None
    if activity_type == "CSD":
        direction = FundingDirection.DEPOSIT
    elif activity_type == "CSW":
        direction = FundingDirection.WITHDRAWAL
    elif activity_type == "TRANS":
        raw_direction = str(
            raw.get("direction")
            or raw.get("transfer_direction")
            or raw.get("subtype")
            or raw.get("activity_subtype")
            or ""
        ).strip().lower()
        if raw_direction in {"deposit", "incoming", "in", "cash_deposit", "cash deposit"}:
            direction = FundingDirection.DEPOSIT
        elif raw_direction in {
            "withdrawal",
            "outgoing",
            "out",
            "cash_withdrawal",
            "cash withdrawal",
        }:
            direction = FundingDirection.WITHDRAWAL
        else:
            try:
                signed_amount = Decimal(str(raw.get("net_amount")))
            except Exception:
                signed_amount = Decimal("0")
            if signed_amount > 0:
                direction = FundingDirection.DEPOSIT
            elif signed_amount < 0:
                direction = FundingDirection.WITHDRAWAL
    if direction is None:
        return None
    transaction_id = str(raw.get("id") or raw.get("transaction_id") or "").strip()
    amount = _activity_amount(raw.get("net_amount") or raw.get("amount"))
    if not transaction_id or amount is None:
        return None
    venue_updated_at, precision = _parse_time(
        raw.get("date") or raw.get("transaction_time") or raw.get("updated_at"),
        observed_at=observed_at,
    )
    return VenueCashFlow(
        environment=environment,
        venue=Venue.ALPACA,
        model_providers=(provider,),
        account_ref=account_ref,
        venue_transaction_id=transaction_id,
        activity_type=activity_type,
        direction=direction,
        amount_usd=amount,
        status=_cash_status(raw.get("status")),
        effective_at=venue_updated_at,
        effective_time_precision=precision,
        observed_at=observed_at,
        updated_at=venue_updated_at,
    )


def normalize_polymarket_funding_activity(
    raw: dict[str, Any],
    *,
    environment: Environment,
    provider: ModelProvider,
    account_ref: str,
    observed_at: datetime,
) -> VenueCashFlow | None:
    """Normalize documented Polymarket US deposit and withdrawal activity."""

    activity_type = str(raw.get("type") or raw.get("activityType") or "").strip().upper()
    change = raw.get("accountBalanceChange")
    if not isinstance(change, dict):
        change = raw
    raw_direction = str(change.get("direction") or raw.get("direction") or "").strip().lower()
    direction: FundingDirection | None
    if activity_type in {"ACCOUNT_DEPOSIT", "ACCOUNT_ADVANCED_DEPOSIT"}:
        direction = FundingDirection.DEPOSIT
    elif activity_type == "ACCOUNT_WITHDRAWAL":
        direction = FundingDirection.WITHDRAWAL
    elif raw_direction in {"deposit", "incoming", "credit", "in"}:
        direction = FundingDirection.DEPOSIT
    elif raw_direction in {"withdrawal", "outgoing", "debit", "out"}:
        direction = FundingDirection.WITHDRAWAL
    else:
        try:
            signed_amount = Decimal(str(change.get("amount")))
        except Exception:
            signed_amount = Decimal("0")
        direction = (
            FundingDirection.DEPOSIT
            if signed_amount > 0
            else FundingDirection.WITHDRAWAL
            if signed_amount < 0
            else None
        )
    if direction is None:
        return None
    transaction_id = str(
        change.get("transactionId")
        or raw.get("transactionId")
        or raw.get("id")
        or raw.get("activityId")
        or ""
    ).strip()
    amount = _activity_amount(
        change.get("amount") or raw.get("amount") or raw.get("cashValue")
    )
    if not transaction_id or amount is None:
        return None
    venue_updated_at, precision = _parse_time(
        change.get("time")
        or change.get("updateTime")
        or raw.get("updateTime")
        or raw.get("createTime")
        or raw.get("date"),
        observed_at=observed_at,
    )
    return VenueCashFlow(
        environment=environment,
        venue=Venue.POLYMARKET_US,
        model_providers=(provider,),
        account_ref=account_ref,
        venue_transaction_id=transaction_id,
        activity_type=activity_type,
        direction=direction,
        amount_usd=amount,
        status=_cash_status(change.get("status") or raw.get("status")),
        effective_at=venue_updated_at,
        effective_time_precision=precision,
        observed_at=observed_at,
        updated_at=venue_updated_at,
    )


class FundingRepository:
    """Persistence boundary for funding state and compare-before-update transitions."""

    def __init__(self, registry: RepositoryRegistry):
        self.registry = registry
        self.state = registry.state

    def upsert_cash_flow(self, cash_flow: VenueCashFlow) -> dict[str, Any]:
        filters = {
            "environment": cash_flow.environment.value,
            "venue": cash_flow.venue.value,
            "account_ref": cash_flow.account_ref,
            "venue_transaction_id": cash_flow.venue_transaction_id,
        }
        values = {
            **filters,
            "model_providers": sorted(provider.value for provider in cash_flow.model_providers),
            "activity_type": cash_flow.activity_type,
            "direction": cash_flow.direction.value,
            "amount_usd": cash_flow.amount_usd,
            "venue_status": cash_flow.status.value,
            "effective_at": cash_flow.effective_at,
            "effective_time_precision": cash_flow.effective_time_precision,
            "observed_at": cash_flow.observed_at,
            "updated_at": cash_flow.updated_at,
        }
        lock_key = "funding-cash-flow:" + "|".join(str(filters[key]) for key in filters)
        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(lock_key)
            rows = self.state.rows(VENUE_CASH_FLOWS_TABLE, filters=filters)
            if rows:
                current = rows[0]
                providers = sorted(
                    set(current.get("model_providers", [])) | set(values["model_providers"])
                )
                updates: dict[str, Any] = {
                    "model_providers": providers,
                    "observed_at": max(current["observed_at"], cash_flow.observed_at),
                }
                current_terminal = current["venue_status"] in _TERMINAL_CASH_STATUSES
                incoming_terminal = cash_flow.status.value in _TERMINAL_CASH_STATUSES
                if not current_terminal and (
                    incoming_terminal or cash_flow.updated_at >= current["updated_at"]
                ):
                    updates.update(
                        {
                            key: value
                            for key, value in values.items()
                            if key not in {"observed_at", "model_providers"}
                        }
                    )
                persisted = self.state.update_by_id(
                    VENUE_CASH_FLOWS_TABLE,
                    current["id"],
                    updates,
                )
            else:
                persisted = self.state.insert(
                    VENUE_CASH_FLOWS_TABLE,
                    {"id": str(uuid4()), **values, "created_at": datetime.now(UTC)},
                )
            unit.commit()
            return persisted

    def list_cash_flows(
        self,
        environment: Environment,
        *,
        limit: int = FUNDING_API_LIMIT,
    ) -> list[dict[str, Any]]:
        rows = self.state.rows(
            VENUE_CASH_FLOWS_TABLE,
            filters={"environment": environment.value},
        )
        return sorted(
            rows,
            key=lambda row: (row["effective_at"], row["id"]),
            reverse=True,
        )[: max(1, min(int(limit), FUNDING_MAX_API_LIMIT))]

    def materialize_occurrence(
        self,
        *,
        schedule: FundingSchedule,
        environment: Environment,
        account_ref: str,
        config_owner: str,
        config_version: str,
        due_at: datetime,
        match_deadline_at: datetime,
        expected_amount_usd: Decimal | str | None = None,
        triggering_snapshot_id: str | None = None,
        low_balance_episode_key: str | None = None,
    ) -> dict[str, Any]:
        amount = funding_decimal(
            expected_amount_usd if expected_amount_usd is not None else schedule.amount_usd,
            "expected_amount_usd",
            positive=True,
        )
        key = build_funding_occurrence_key(
            FundingOccurrenceKeyInput(
                environment=environment,
                venue=schedule.venue,
                account_ref=account_ref,
                model_provider=schedule.model_provider,
                schedule_id=schedule.id,
                due_at=due_at,
                direction=schedule.direction,
                execution_mode=schedule.execution_mode,
            )
        )
        snapshot = schedule.model_dump(mode="json")
        snapshot_hash = sha256(repr(sorted(snapshot.items())).encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(key)
            existing = self.state.rows(
                FUNDING_OCCURRENCES_TABLE,
                filters={"idempotency_key": key},
            )
            if existing:
                unit.commit()
                return existing[0]
            persisted = self.state.insert(
                FUNDING_OCCURRENCES_TABLE,
                {
                "id": str(uuid4()),
                "idempotency_key": key,
                "schedule_id": schedule.id,
                "config_owner": config_owner,
                "config_version": config_version,
                "schedule_snapshot": snapshot,
                "schedule_hash": snapshot_hash,
                "environment": environment.value,
                "venue": schedule.venue.value,
                "model_provider": schedule.model_provider.value,
                "account_ref": account_ref,
                "direction": schedule.direction.value,
                "execution_mode": schedule.execution_mode.value,
                "cadence": schedule.cadence.value,
                "expected_amount_usd": amount,
                "submitted_amount_usd": None,
                "reserved_amount_usd": None,
                "reserved_at": None,
                "triggering_snapshot_id": triggering_snapshot_id,
                "low_balance_episode_key": low_balance_episode_key,
                "due_at": due_at.astimezone(UTC),
                "match_deadline_at": match_deadline_at.astimezone(UTC),
                "status": FundingOccurrenceStatus.EXPECTED.value,
                "matched_cash_flow_id": None,
                "request_fingerprint": None,
                "provider_transfer_id": None,
                "post_attempted_at": None,
                "alerted_at": None,
                "recovery_alerted_at": None,
                "refusal_reason": None,
                "created_at": now,
                "updated_at": now,
                },
            )
            unit.commit()
            return persisted

    def occurrence(self, occurrence_id: str) -> dict[str, Any] | None:
        rows = self.state.rows(FUNDING_OCCURRENCES_TABLE, ids={occurrence_id})
        return rows[0] if rows else None

    def list_occurrences(
        self,
        environment: Environment,
        *,
        limit: int = FUNDING_API_LIMIT,
    ) -> list[dict[str, Any]]:
        rows = self.state.rows(
            FUNDING_OCCURRENCES_TABLE,
            filters={"environment": environment.value},
        )
        return sorted(rows, key=lambda row: (row["due_at"], row["id"]), reverse=True)[
            : max(1, min(int(limit), FUNDING_MAX_API_LIMIT))
        ]

    def update_occurrence(self, occurrence_id: str, **values: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "matched_cash_flow_id",
            "submitted_amount_usd",
            "reserved_amount_usd",
            "reserved_at",
            "request_fingerprint",
            "provider_transfer_id",
            "post_attempted_at",
            "alerted_at",
            "recovery_alerted_at",
            "refusal_reason",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        updates["updated_at"] = datetime.now(UTC)
        return dict(self.state.update_by_id(FUNDING_OCCURRENCES_TABLE, occurrence_id, updates))

    def reconcile_occurrence(
        self,
        occurrence_id: str,
        *,
        coverage_through_at: datetime | None,
        now: datetime,
        allow_missing: bool = True,
    ) -> dict[str, Any]:
        initial = self.occurrence(occurrence_id)
        if initial is None:
            raise PersistenceUnavailableError("funding occurrence was not found")
        account_lock = (
            f"funding-reconcile:{initial['environment']}:{initial['venue']}:{initial['account_ref']}"
        )
        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(account_lock)
            occurrence = self.occurrence(occurrence_id)
            if occurrence is None:
                raise PersistenceUnavailableError("funding occurrence was not found")
            if occurrence["status"] in {
                FundingOccurrenceStatus.MATCHED.value,
                FundingOccurrenceStatus.REFUSED.value,
                FundingOccurrenceStatus.REJECTED.value,
                FundingOccurrenceStatus.RETURNED.value,
                FundingOccurrenceStatus.FAILED.value,
            }:
                unit.commit()
                return occurrence
            used_flow_ids = {
                row.get("matched_cash_flow_id")
                for row in self.state.rows(FUNDING_OCCURRENCES_TABLE)
                if row.get("matched_cash_flow_id")
            }
            candidates = []
            for cash_flow in self.state.rows(
                VENUE_CASH_FLOWS_TABLE,
                filters={
                    "environment": occurrence["environment"],
                    "venue": occurrence["venue"],
                    "account_ref": occurrence["account_ref"],
                    "direction": occurrence["direction"],
                    "venue_status": CashFlowStatus.COMPLETED.value,
                },
            ):
                if cash_flow["id"] in used_flow_ids:
                    continue
                if not (
                    occurrence["due_at"]
                    <= cash_flow["effective_at"]
                    <= occurrence["match_deadline_at"]
                ):
                    continue
                target = occurrence.get("submitted_amount_usd") or occurrence[
                    "expected_amount_usd"
                ]
                if (
                    abs(
                        Decimal(str(cash_flow["amount_usd"]))
                        - Decimal(str(target))
                    )
                    <= FUNDING_MATCH_TOLERANCE
                ):
                    candidates.append(cash_flow)
            if len(candidates) == 1:
                prior_missing = occurrence["status"] == FundingOccurrenceStatus.MISSING.value
                matched = self.update_occurrence(
                    occurrence_id,
                    status=FundingOccurrenceStatus.MATCHED.value,
                    matched_cash_flow_id=candidates[0]["id"],
                    recovery_alerted_at=now if prior_missing else None,
                )
                if prior_missing:
                    self._enqueue_alert_locked(matched, transition_type="recovery", at=now)
                unit.commit()
                return matched
            if (
                allow_missing
                and
                occurrence["status"] != FundingOccurrenceStatus.MISSING.value
                and now > occurrence["match_deadline_at"]
                and coverage_through_at is not None
                and coverage_through_at > occurrence["match_deadline_at"]
            ):
                missing = self.update_occurrence(
                    occurrence_id,
                    status=FundingOccurrenceStatus.MISSING.value,
                    alerted_at=now,
                )
                self._enqueue_alert_locked(missing, transition_type="failure", at=now)
                unit.commit()
                return missing
            unit.commit()
            return occurrence

    def enqueue_alert(self, occurrence: dict[str, Any], *, transition_type: str) -> dict[str, Any]:
        """Enqueue a transition independently when no state change is required."""

        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(
                f"funding-alert:{occurrence['environment']}:{occurrence['id']}:{transition_type}"
            )
            alert = self._enqueue_alert_locked(
                occurrence,
                transition_type=transition_type,
                at=datetime.now(UTC),
            )
            unit.commit()
            return alert

    def _enqueue_alert_locked(
        self,
        occurrence: dict[str, Any],
        *,
        transition_type: str,
        at: datetime,
    ) -> dict[str, Any]:
        transition_key = f"{occurrence['environment']}:{occurrence['id']}:{transition_type}"
        rows = self.state.rows(
            FUNDING_ALERT_OUTBOX_TABLE,
            filters={"transition_key": transition_key},
        )
        if rows:
            return rows[0]
        return self.state.insert(
            FUNDING_ALERT_OUTBOX_TABLE,
            {
                "id": str(uuid4()),
                "transition_key": transition_key,
                "occurrence_id": occurrence["id"],
                "environment": occurrence["environment"],
                "transition_type": transition_type,
                "delivery_status": "pending",
                "attempt_count": 0,
                "next_attempt_at": at,
                "provider_message_id": None,
                "last_error": None,
                "created_at": at,
                "updated_at": at,
            },
        )

    def transition_with_alert(
        self,
        occurrence_id: str,
        *,
        status: FundingOccurrenceStatus,
        transition_type: str,
        at: datetime,
        **values: Any,
    ) -> dict[str, Any]:
        """Persist a terminal occurrence transition and its outbox row atomically."""

        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(f"funding-occurrence:{occurrence_id}")
            current = self.occurrence(occurrence_id)
            if current is None:
                raise PersistenceUnavailableError("funding occurrence was not found")
            alerted_field = (
                "recovery_alerted_at" if transition_type == "recovery" else "alerted_at"
            )
            updated = self.update_occurrence(
                occurrence_id,
                status=status.value,
                **{alerted_field: at},
                **values,
            )
            self._enqueue_alert_locked(updated, transition_type=transition_type, at=at)
            unit.commit()
            return updated

    def alerts(self, environment: Environment) -> list[dict[str, Any]]:
        return self.state.rows(
            FUNDING_ALERT_OUTBOX_TABLE,
            filters={"environment": environment.value},
        )

    def monthly_reserved_amount(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
        at: datetime,
        exclude_occurrence_id: str | None = None,
    ) -> Decimal:
        local = at.astimezone(EASTERN)
        total = Decimal("0")
        for row in self.state.rows(
            FUNDING_OCCURRENCES_TABLE,
            filters={
                "environment": environment.value,
                "venue": venue.value,
                "account_ref": account_ref,
            },
        ):
            if row["id"] == exclude_occurrence_id:
                continue
            if row["status"] not in {
                FundingOccurrenceStatus.RESERVED.value,
                FundingOccurrenceStatus.SUBMITTED.value,
                FundingOccurrenceStatus.UNKNOWN.value,
                FundingOccurrenceStatus.MATCHED.value,
                FundingOccurrenceStatus.MISSING.value,
            }:
                continue
            if (
                row["status"] == FundingOccurrenceStatus.MISSING.value
                and (
                    row.get("execution_mode") != FundingExecutionMode.DIRECT.value
                    or row.get("post_attempted_at") is None
                )
            ):
                continue
            reserved_at = row.get("reserved_at")
            amount = row.get("reserved_amount_usd")
            if not isinstance(reserved_at, datetime) or amount is None:
                continue
            reserved_local = reserved_at.astimezone(EASTERN)
            if (reserved_local.year, reserved_local.month) == (local.year, local.month):
                total += Decimal(str(amount))
        return total

    def claim_direct_occurrence(
        self,
        occurrence_id: str,
        *,
        broker_account_ref: str | None,
        broker_secrets_available: bool,
        kill_switch_active: bool,
        at: datetime,
    ) -> dict[str, Any]:
        initial = self.occurrence(occurrence_id)
        if initial is None:
            raise PersistenceUnavailableError("funding occurrence was not found")
        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(
                f"funding-controls:{initial['environment']}:global"
            )
            self.state.lock_transaction_key(
                "funding-controls:"
                f"{initial['environment']}:{normalize_config_username(initial.get('config_owner'))}"
            )
            self.state.lock_transaction_key(
                f"funding:{initial['environment']}:{initial['venue']}:{initial['account_ref']}"
            )
            current = self.occurrence(occurrence_id)
            assert current is not None
            if (
                current.get("post_attempted_at") is not None
                or current["status"] != FundingOccurrenceStatus.EXPECTED.value
            ):
                unit.commit()
                return current
            config = self._current_funding_config_locked(current)
            schedule = None
            if config is not None:
                schedules = [
                    candidate
                    for candidate in config.schedules
                    if candidate.id == current["schedule_id"] and candidate.enabled
                ]
                if len(schedules) == 1:
                    candidate = schedules[0]
                    if candidate.model_dump(mode="json") == current["schedule_snapshot"]:
                        schedule = candidate
            refusal_reason = self._atomic_refusal_reason(
                current=current,
                config=config,
                schedule=schedule,
                broker_account_ref=broker_account_ref,
                broker_secrets_available=broker_secrets_available,
                kill_switch_active=kill_switch_active or self._kill_switch_active_locked(current),
            )
            amount_usd: Decimal | None = None
            if refusal_reason is None:
                assert config is not None and schedule is not None
                amount_usd = Decimal(str(current["expected_amount_usd"]))
                if amount_usd > config.max_transfer_usd:
                    if schedule.cadence in {FundingCadence.WEEKLY, FundingCadence.MONTHLY}:
                        refusal_reason = "per_transfer_limit_exceeded"
                    else:
                        amount_usd = config.max_transfer_usd
                reserved = self.monthly_reserved_amount(
                    environment=Environment(current["environment"]),
                    venue=Venue(current["venue"]),
                    account_ref=current["account_ref"],
                    at=at,
                    exclude_occurrence_id=current["id"],
                )
                remaining = config.max_monthly_transfer_usd - reserved
                if refusal_reason is None and remaining <= 0:
                    refusal_reason = "monthly_limit_exhausted"
                elif refusal_reason is None and amount_usd > remaining:
                    if schedule.cadence in {FundingCadence.WEEKLY, FundingCadence.MONTHLY}:
                        refusal_reason = "monthly_limit_exceeded"
                    else:
                        amount_usd = remaining
                if refusal_reason is None and amount_usd <= 0:
                    refusal_reason = "non_positive_transfer_amount"
            pending = [
                row
                for row in self.state.rows(
                    FUNDING_OCCURRENCES_TABLE,
                    filters={
                        "environment": current["environment"],
                        "venue": current["venue"],
                        "account_ref": current["account_ref"],
                    },
                )
                if row["id"] != occurrence_id
                and row["status"]
                in {
                    FundingOccurrenceStatus.RESERVED.value,
                    FundingOccurrenceStatus.SUBMITTED.value,
                    FundingOccurrenceStatus.UNKNOWN.value,
                    FundingOccurrenceStatus.MISSING.value,
                }
                and row.get("post_attempted_at") is not None
            ]
            if refusal_reason is None and pending:
                refusal_reason = "pending_transfer_exists"
            if refusal_reason is not None:
                claimed = self.update_occurrence(
                    occurrence_id,
                    status=FundingOccurrenceStatus.REFUSED.value,
                    refusal_reason=refusal_reason,
                )
                unit.commit()
                return claimed
            assert amount_usd is not None
            request_fingerprint = sha256(
                f"{current['id']}|{current['account_ref']}|{amount_usd:.8f}|incoming-ach".encode(
                    "utf-8"
                )
            ).hexdigest()
            claimed = self.update_occurrence(
                occurrence_id,
                status=FundingOccurrenceStatus.RESERVED.value,
                submitted_amount_usd=amount_usd,
                reserved_amount_usd=amount_usd,
                reserved_at=at,
                request_fingerprint=request_fingerprint,
                post_attempted_at=at,
            )
            unit.commit()
            return claimed

    def _current_funding_config_locked(self, occurrence: dict[str, Any]) -> FundingConfig | None:
        owner = normalize_config_username(occurrence.get("config_owner"))
        rows = [
            row
            for row in self.state.rows(f"{SHARED_SCHEMA}.config_versions")
            if row.get("environment") == occurrence["environment"] and row.get("active")
        ]
        owner_rows = [
            row for row in rows if normalize_config_username(row.get("username")) == owner
        ]
        if not owner_rows and owner != SHARED_CONFIG_USERNAME:
            owner_rows = [
                row
                for row in rows
                if normalize_config_username(row.get("username")) == SHARED_CONFIG_USERNAME
            ]
        if not owner_rows:
            return None
        latest = max(owner_rows, key=lambda row: row["created_at"])
        try:
            return FundingConfig.model_validate((latest.get("payload") or {}).get("funding", {}))
        except (TypeError, ValueError):
            return None

    def _kill_switch_active_locked(self, occurrence: dict[str, Any]) -> bool:
        rows = self.state.rows(
            f"{SHARED_SCHEMA}.operational_controls",
            filters={
                "environment": occurrence["environment"],
                "control": "global_kill_switch",
            },
        )
        return bool(rows and rows[0].get("active"))

    @staticmethod
    def _atomic_refusal_reason(
        *,
        current: dict[str, Any],
        config: FundingConfig | None,
        schedule: FundingSchedule | None,
        broker_account_ref: str | None,
        broker_secrets_available: bool,
        kill_switch_active: bool,
    ) -> str | None:
        if kill_switch_active:
            return "global_kill_switch_active"
        if config is None:
            return "funding_config_unavailable"
        if config.emergency_stop:
            return "funding_emergency_stop_active"
        if not config.direct_transfers_enabled:
            return "direct_transfers_disabled"
        if config.max_transfer_usd <= 0:
            return "per_transfer_limit_zero"
        if config.max_monthly_transfer_usd <= 0:
            return "monthly_limit_zero"
        if current["execution_mode"] != FundingExecutionMode.DIRECT.value:
            return "occurrence_not_direct"
        if current["venue"] != Venue.ALPACA.value:
            return "direct_venue_unsupported"
        if current["direction"] != FundingDirection.DEPOSIT.value:
            return "direct_direction_unsupported"
        if schedule is None:
            return "schedule_changed_or_unavailable"
        if not broker_secrets_available:
            return "broker_secrets_unavailable"
        if broker_account_ref is None or current["account_ref"] != broker_account_ref:
            return "broker_account_mismatch"
        if Decimal(str(current["expected_amount_usd"])) <= 0:
            return "non_positive_transfer_amount"
        return None

    def set_sync_state(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
        coverage_through_at: datetime | None,
        head_transaction_id: str | None = None,
        backfill_cursor: str | None = None,
        backfill_complete: bool = False,
        last_error_code: str | None = None,
    ) -> dict[str, Any]:
        filters = {
            "environment": environment.value,
            "venue": venue.value,
            "account_ref": account_ref,
        }
        values = {
            **filters,
            "head_transaction_id": head_transaction_id,
            "head_synced_at": datetime.now(UTC) if head_transaction_id else None,
            "coverage_through_at": coverage_through_at,
            "backfill_cursor": backfill_cursor,
            "backfill_complete": backfill_complete,
            "last_error_code": last_error_code,
            "updated_at": datetime.now(UTC),
        }
        lock_key = f"funding-sync:{environment.value}:{venue.value}:{account_ref}"
        with UnitOfWork(self.state) as unit:
            self.state.lock_transaction_key(lock_key)
            rows = self.state.rows(FUNDING_SYNC_STATE_TABLE, filters=filters)
            if rows:
                persisted = self.state.update_by_id(
                    FUNDING_SYNC_STATE_TABLE,
                    rows[0]["id"],
                    values,
                )
            else:
                persisted = self.state.insert(
                    FUNDING_SYNC_STATE_TABLE,
                    {"id": str(uuid4()), **values},
                )
            unit.commit()
            return persisted

    def sync_state(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
    ) -> dict[str, Any] | None:
        rows = self.state.rows(
            FUNDING_SYNC_STATE_TABLE,
            filters={
                "environment": environment.value,
                "venue": venue.value,
                "account_ref": account_ref,
            },
        )
        return rows[0] if rows else None


class FundingService:
    """Application service for funding history and serialized dashboard reads."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        direct_service: Any | None = None,
        notification_adapter: Any | None = None,
        notification_recipients: tuple[str, ...] = (),
    ):
        self.registry = registry
        self.repository = FundingRepository(registry)
        self.direct_service = direct_service
        self.notification_adapter = notification_adapter
        self.notification_recipients = tuple(
            recipient.strip() for recipient in notification_recipients if recipient.strip()
        )

    def history_payload(
        self,
        environment: Environment,
        *,
        limit: int = FUNDING_API_LIMIT,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        cash_cursor: str | None = None,
        occurrence_cursor: str | None = None,
    ) -> dict[str, Any]:
        if (start_at is not None and start_at.tzinfo is None) or (
            end_at is not None and end_at.tzinfo is None
        ):
            raise ValueError("funding history timestamps require a timezone")
        period_end = (end_at or datetime.now(UTC)).astimezone(UTC)
        period_start = (start_at or (period_end - timedelta(days=30))).astimezone(UTC)
        if period_start >= period_end:
            raise ValueError("funding history start must precede end")
        if period_end - period_start > timedelta(days=FUNDING_MAX_HISTORY_DAYS):
            raise ValueError("funding history interval cannot exceed one year")
        raw_cash_flows = sorted(
            [
            row
            for row in self.registry.state.rows(
                VENUE_CASH_FLOWS_TABLE,
                filters={"environment": environment.value},
            )
            if period_start <= row["effective_at"] <= period_end
            ],
            key=lambda row: (row["effective_at"], row["id"]),
            reverse=True,
        )
        raw_occurrences = sorted(
            [
            row
            for row in self.registry.state.rows(
                FUNDING_OCCURRENCES_TABLE,
                filters={"environment": environment.value},
            )
            if period_start <= row["due_at"] <= period_end
            ],
            key=lambda row: (row["due_at"], row["id"]),
            reverse=True,
        )
        cash_page, next_cash_cursor = self._history_page(
            raw_cash_flows,
            limit=limit,
            cursor=cash_cursor,
            kind="cash",
            timestamp_field="effective_at",
        )
        occurrence_page, next_occurrence_cursor = self._history_page(
            raw_occurrences,
            limit=limit,
            cursor=occurrence_cursor,
            kind="occurrence",
            timestamp_field="due_at",
        )
        return {
            "environment": environment.value,
            "interval": {
                "startAt": period_start.isoformat(),
                "endAt": period_end.isoformat(),
            },
            "cashFlows": [
                self._cash_flow_payload(row) for row in cash_page
            ],
            "occurrences": [
                self._occurrence_payload(row) for row in occurrence_page
            ],
            "nextCashCursor": next_cash_cursor,
            "nextOccurrenceCursor": next_occurrence_cursor,
            "accounts": self._account_funding_summaries(raw_cash_flows, raw_occurrences),
            "performance": self._performance_payload(
                environment=environment,
                period_start=period_start,
                period_end=period_end,
                cash_flows=raw_cash_flows,
            ),
            "dataStatus": self._funding_data_status(environment),
            "directTransferReadiness": {
                "enabled": False,
                "ready": False,
                "message": "Direct transfers are disabled until nonzero limits and entitled Alpaca Broker secrets are configured.",
            },
        }

    @staticmethod
    def _history_page(
        rows: list[dict[str, Any]],
        *,
        limit: int,
        cursor: str | None,
        kind: str,
        timestamp_field: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        start_index = 0
        if cursor:
            try:
                padding = "=" * (-len(cursor) % 4)
                payload = json.loads(
                    base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
                )
                if payload.get("kind") != kind:
                    raise ValueError
                cursor_key = (
                    datetime.fromisoformat(str(payload["at"]).replace("Z", "+00:00")).astimezone(UTC),
                    str(payload["id"]),
                )
            except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid {kind} funding cursor") from exc
            for index, row in enumerate(rows):
                if (row[timestamp_field], row["id"]) < cursor_key:
                    start_index = index
                    break
            else:
                start_index = len(rows)
        page_limit = max(1, min(int(limit), FUNDING_MAX_API_LIMIT))
        page = rows[start_index : start_index + page_limit]
        if start_index + page_limit >= len(rows) or not page:
            return page, None
        last = page[-1]
        token = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "kind": kind,
                    "at": last[timestamp_field].astimezone(UTC).isoformat(),
                    "id": last["id"],
                },
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return page, token

    def _account_label(self, row: dict[str, Any]) -> str:
        venue = "Alpaca" if row["venue"] == Venue.ALPACA.value else "Polymarket US"
        provider = row.get("model_provider")
        if provider is None:
            providers = row.get("model_providers") or []
            provider = ", ".join(str(value).title() for value in providers)
        else:
            provider = str(provider).title()
        return f"{venue} {provider} account".strip()

    def _cash_flow_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "venue": row["venue"],
            "providers": row["model_providers"],
            "accountLabel": self._account_label(row),
            "direction": row["direction"],
            "amountUsd": str(row["amount_usd"]),
            "status": row["venue_status"],
            "activityType": row["activity_type"],
            "effectiveAt": row["effective_at"].isoformat(),
            "effectiveTimePrecision": row["effective_time_precision"],
            "observedAt": row["observed_at"].isoformat(),
        }

    def _occurrence_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "scheduleId": row["schedule_id"],
            "venue": row["venue"],
            "provider": row["model_provider"],
            "accountLabel": self._account_label(row),
            "cadence": row["cadence"],
            "executionMode": row["execution_mode"],
            "direction": row["direction"],
            "expectedAmountUsd": str(row["expected_amount_usd"]),
            "submittedAmountUsd": (
                None if row.get("submitted_amount_usd") is None else str(row["submitted_amount_usd"])
            ),
            "status": row["status"],
            "dueAt": row["due_at"].isoformat(),
            "matchDeadlineAt": row["match_deadline_at"].isoformat(),
            "alertState": (
                "recovered"
                if row.get("recovery_alerted_at")
                else "alerted"
                if row.get("alerted_at")
                else "none"
            ),
        }

    def _account_funding_summaries(
        self,
        cash_flows: list[dict[str, Any]],
        occurrences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        keys = {
            (row["venue"], row["account_ref"])
            for row in [*cash_flows, *occurrences]
        }
        summaries = []
        for venue, account_ref in sorted(keys):
            account_flows = [
                row
                for row in cash_flows
                if row["venue"] == venue
                and row["account_ref"] == account_ref
                and row["venue_status"] == CashFlowStatus.COMPLETED.value
            ]
            account_occurrences = [
                row
                for row in occurrences
                if row["venue"] == venue and row["account_ref"] == account_ref
            ]
            provider_values = sorted(
                {
                    str(provider)
                    for row in account_flows
                    for provider in row.get("model_providers", [])
                }
                | {str(row["model_provider"]) for row in account_occurrences}
            )
            summaries.append(
                {
                    "venue": venue,
                    "providers": provider_values,
                    "accountLabel": self._account_label(
                        {"venue": venue, "model_providers": provider_values}
                    ),
                    "completedDepositsUsd": str(
                        sum(
                            (
                                Decimal(str(row["amount_usd"]))
                                for row in account_flows
                                if row["direction"] == FundingDirection.DEPOSIT.value
                            ),
                            Decimal("0"),
                        )
                    ),
                    "completedWithdrawalsUsd": str(
                        sum(
                            (
                                Decimal(str(row["amount_usd"]))
                                for row in account_flows
                                if row["direction"] == FundingDirection.WITHDRAWAL.value
                            ),
                            Decimal("0"),
                        )
                    ),
                    "matchedOccurrences": sum(
                        row["status"] == FundingOccurrenceStatus.MATCHED.value
                        for row in account_occurrences
                    ),
                    "missingOccurrences": sum(
                        row["status"] == FundingOccurrenceStatus.MISSING.value
                        for row in account_occurrences
                    ),
                }
            )
        return summaries

    def _performance_payload(
        self,
        *,
        environment: Environment,
        period_start: datetime,
        period_end: datetime,
        cash_flows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        snapshots = [
            row
            for row in self.registry.state.rows(
                f"{SHARED_SCHEMA}.venue_portfolio_snapshots"
            )
            if row.get("environment") == environment.value
            and row.get("status") == "ready"
            and row.get("account_value_usd") is not None
            and isinstance(row.get("observed_at"), datetime)
            and row["observed_at"] <= period_end
        ]
        account_refs = {
            str(row["account_ref"])
            for row in snapshots
        } | {str(row["account_ref"]) for row in cash_flows}
        beginning = Decimal("0")
        ending = Decimal("0")
        eligible_accounts: set[str] = set()
        account_results: list[dict[str, Any]] = []
        for account_ref in account_refs:
            account_rows = [row for row in snapshots if row["account_ref"] == account_ref]
            beginning_rows = [row for row in account_rows if row["observed_at"] <= period_start]
            ending_rows = [row for row in account_rows if row["observed_at"] <= period_end]
            if not beginning_rows or not ending_rows:
                account_results.append(
                    {
                        "accountLabel": self._account_label(
                            next(
                                (row for row in cash_flows if row["account_ref"] == account_ref),
                                {"venue": "unknown", "model_providers": []},
                            )
                        ),
                        "status": "unavailable",
                        "unavailableReason": "Boundary portfolio snapshots are missing.",
                        "beginningSnapshotAt": None,
                        "endingSnapshotAt": None,
                    }
                )
                continue
            beginning_row = max(beginning_rows, key=lambda row: row["observed_at"])
            ending_row = max(ending_rows, key=lambda row: row["observed_at"])
            fresh = (
                (period_start - beginning_row["observed_at"]).total_seconds()
                <= FUNDING_BOUNDARY_FRESHNESS_SECONDS
                and (period_end - ending_row["observed_at"]).total_seconds()
                <= FUNDING_BOUNDARY_FRESHNESS_SECONDS
            )
            label_row = next(
                (row for row in cash_flows if row["account_ref"] == account_ref),
                beginning_row,
            )
            if not fresh:
                account_results.append(
                    {
                        "accountLabel": self._account_label(label_row),
                        "status": "unavailable",
                        "unavailableReason": "Boundary portfolio snapshots are stale.",
                        "beginningSnapshotAt": beginning_row["observed_at"].isoformat(),
                        "endingSnapshotAt": ending_row["observed_at"].isoformat(),
                    }
                )
                continue
            eligible_accounts.add(account_ref)
            beginning += Decimal(str(beginning_row["account_value_usd"]))
            ending += Decimal(str(ending_row["account_value_usd"]))
            account_results.append(
                {
                    "accountLabel": self._account_label(label_row),
                    "status": "ready",
                    "unavailableReason": None,
                    "beginningSnapshotAt": beginning_row["observed_at"].isoformat(),
                    "endingSnapshotAt": ending_row["observed_at"].isoformat(),
                }
            )
        completed = [
            (
                row["effective_at"],
                FundingDirection(row["direction"]),
                Decimal(str(row["amount_usd"])),
            )
            for row in cash_flows
            if row["venue_status"] == CashFlowStatus.COMPLETED.value
            and row["account_ref"] in eligible_accounts
        ]
        completed_deposits = sum(
            (amount for _, direction, amount in completed if direction == FundingDirection.DEPOSIT),
            Decimal("0"),
        )
        completed_withdrawals = sum(
            (
                amount
                for _, direction, amount in completed
                if direction == FundingDirection.WITHDRAWAL
            ),
            Decimal("0"),
        )
        result = adjusted_trading_performance(
            beginning_value=beginning,
            ending_value=ending,
            cash_flows=completed,
            period_start=period_start,
            period_end=period_end,
            boundaries_fresh=bool(eligible_accounts),
        )
        return {
            "beginningValueUsd": str(result.beginning_value_usd),
            "endingValueUsd": str(result.ending_value_usd),
            "completedDepositsUsd": str(_money(completed_deposits)),
            "completedWithdrawalsUsd": str(_money(completed_withdrawals)),
            "tradingPnlExcludingCashFlowsUsd": (
                None if result.adjusted_pnl_usd is None else str(result.adjusted_pnl_usd)
            ),
            "modifiedDietzReturn": (
                None
                if result.modified_dietz_return is None
                else str(result.modified_dietz_return)
            ),
            "unavailableReason": result.unavailable_reason,
            "accounts": account_results,
        }

    def _funding_data_status(self, environment: Environment) -> dict[str, Any]:
        states = self.registry.state.rows(
            FUNDING_SYNC_STATE_TABLE,
            filters={"environment": environment.value},
        )
        errors = sorted(
            {str(row["last_error_code"]) for row in states if row.get("last_error_code")}
        )
        partial = any(not row.get("backfill_complete") for row in states)
        return {
            "status": (
                "degraded"
                if errors
                else "partial"
                if partial
                else "ready"
                if states
                else "unavailable"
            ),
            "accountCount": len(states),
            "errors": errors,
        }

    def direct_transfer_readiness(
        self,
        *,
        environment: Environment,
        config: FundingConfig,
        kill_switch_active: bool,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        if kill_switch_active:
            blockers.append("Global kill switch is active.")
        if config.emergency_stop:
            blockers.append("Funding emergency stop is active.")
        if not config.direct_transfers_enabled:
            blockers.append("Direct transfers are disabled.")
        if config.max_transfer_usd <= 0:
            blockers.append("Per-transfer limit is zero.")
        if config.max_monthly_transfer_usd <= 0:
            blockers.append("Monthly transfer limit is zero.")
        direct_schedules = [
            schedule
            for schedule in config.schedules
            if schedule.enabled and schedule.execution_mode == FundingExecutionMode.DIRECT
        ]
        if config.direct_transfers_enabled and not direct_schedules:
            blockers.append("No enabled direct Alpaca schedule is configured.")
        adapter = getattr(self.direct_service, "adapter", None)
        for schedule in direct_schedules:
            credentials = adapter.credentials(schedule.model_provider) if adapter else {}
            required = (
                "ALPACA_BROKER_API_KEY",
                "ALPACA_BROKER_SECRET_KEY",
                "ALPACA_BROKER_ACCOUNT_ID",
                "ALPACA_BROKER_ACH_RELATIONSHIP_ID",
            )
            if not all(credentials.get(key, "").strip() for key in required):
                blockers.append(
                    f"{schedule.model_provider.value.title()} Broker credentials are unavailable."
                )
                continue
            snapshot = self._latest_account_snapshot(environment, schedule)
            if snapshot is None or snapshot["account_ref"] != funding_account_ref(
                Venue.ALPACA,
                credentials["ALPACA_BROKER_ACCOUNT_ID"],
            ):
                blockers.append(
                    f"{schedule.model_provider.value.title()} Broker account is not bound to the confirmed portfolio."
                )
        return {
            "enabled": config.direct_transfers_enabled,
            "ready": not blockers,
            "maxTransferUsd": str(config.max_transfer_usd),
            "maxMonthlyTransferUsd": str(config.max_monthly_transfer_usd),
            "blockers": blockers,
            "message": (
                "Direct Alpaca incoming ACH is ready."
                if not blockers
                else " ".join(blockers)
            ),
        }

    def run_tick(
        self,
        *,
        environment: Environment,
        config: FundingConfig,
        config_owner: str,
        config_version: str,
        kill_switch_active: bool,
        now: datetime | None = None,
        portfolio_freshness_seconds: int = 120,
    ) -> dict[str, Any]:
        """Materialize schedules and reconcile confirmed activity without overlap.

        Fixed schedules continue when the latest portfolio refresh is stale. Low-balance
        schedules require a fresh confirmed snapshot. Emergency controls block only
        direct writes, not read reconciliation.

        REQ: REQ-FND-005, REQ-FND-006, REQ-FND-007, REQ-FND-008,
        REQ-FND-009, REQ-FND-016, REQ-FND-018
        """

        tick_now = (now or datetime.now(UTC)).astimezone(UTC)
        lock_token = self.registry.state.try_session_lock(
            f"funding-tick:{environment.value}"
        )
        if lock_token is None:
            return {"status": "skipped", "reason": "funding_tick_already_running"}
        materialized = 0
        matched = 0
        missing = 0
        direct_evaluated = 0
        alerts_sent = 0
        try:
            for schedule in config.schedules:
                if not schedule.enabled:
                    continue
                snapshot = self._latest_account_snapshot(environment, schedule)
                if snapshot is None:
                    continue
                occurrence = None
                if schedule.cadence == FundingCadence.LOW_BALANCE:
                    observed_at = snapshot.get("observed_at")
                    if (
                        not isinstance(observed_at, datetime)
                        or snapshot.get("status") != "ready"
                        or (tick_now - observed_at).total_seconds() > portfolio_freshness_seconds
                    ):
                        continue
                    buying_power = snapshot.get("buying_power_usd")
                    if buying_power is None:
                        continue
                    gap = calculate_low_balance_gap(
                        schedule.target_balance_usd or Decimal("0"),
                        buying_power,
                    )
                    if gap <= 0 or self._low_balance_episode_exists(
                        environment=environment,
                        schedule=schedule,
                        latest_snapshot=snapshot,
                    ):
                        continue
                    episode_key = sha256(
                        f"{environment.value}|{schedule.id}|{snapshot['id']}".encode("utf-8")
                    ).hexdigest()
                    occurrence = self.repository.materialize_occurrence(
                        schedule=schedule,
                        environment=environment,
                        account_ref=snapshot["account_ref"],
                        config_owner=config_owner,
                        config_version=config_version,
                        due_at=tick_now,
                        match_deadline_at=self._match_deadline(tick_now, config),
                        expected_amount_usd=gap,
                        triggering_snapshot_id=snapshot["id"],
                        low_balance_episode_key=episode_key,
                    )
                else:
                    due_times = self._unmaterialized_fixed_due_times(
                        environment=environment,
                        schedule=schedule,
                        account_ref=snapshot["account_ref"],
                        now=tick_now,
                    )
                    for due_at in due_times:
                        occurrence = self.repository.materialize_occurrence(
                            schedule=schedule,
                            environment=environment,
                            account_ref=snapshot["account_ref"],
                            config_owner=config_owner,
                            config_version=config_version,
                            due_at=due_at,
                            match_deadline_at=self._match_deadline(due_at, config),
                        )
                        materialized += 1
                        if (
                            occurrence["execution_mode"]
                            == FundingExecutionMode.DIRECT.value
                            and self.direct_service is not None
                        ):
                            self.direct_service.submit_occurrence(
                                occurrence["id"],
                                config=config,
                                kill_switch_active=kill_switch_active,
                                now=tick_now,
                            )
                            direct_evaluated += 1
                    occurrence = None
                if occurrence is not None:
                    materialized += 1
                    if (
                        occurrence["execution_mode"] == FundingExecutionMode.DIRECT.value
                        and self.direct_service is not None
                    ):
                        self.direct_service.submit_occurrence(
                            occurrence["id"],
                            config=config,
                            kill_switch_active=kill_switch_active,
                            now=tick_now,
                        )
                        direct_evaluated += 1

            for occurrence in self.repository.list_occurrences(environment, limit=500):
                if (
                    occurrence["execution_mode"] == FundingExecutionMode.DIRECT.value
                    and occurrence.get("post_attempted_at") is not None
                    and occurrence["status"]
                    in {
                        FundingOccurrenceStatus.RESERVED.value,
                        FundingOccurrenceStatus.SUBMITTED.value,
                        FundingOccurrenceStatus.UNKNOWN.value,
                        FundingOccurrenceStatus.MISSING.value,
                    }
                    and self.direct_service is not None
                ):
                    occurrence = self.direct_service.reconcile_occurrence(
                        occurrence["id"],
                        now=tick_now,
                    )
                sync = self.repository.sync_state(
                    environment=environment,
                    venue=Venue(occurrence["venue"]),
                    account_ref=occurrence["account_ref"],
                )
                prior_status = occurrence["status"]
                updated = self.repository.reconcile_occurrence(
                    occurrence["id"],
                    coverage_through_at=(sync or {}).get("coverage_through_at"),
                    now=tick_now,
                    allow_missing=not (
                        occurrence["execution_mode"] == FundingExecutionMode.DIRECT.value
                        and occurrence["status"] == FundingOccurrenceStatus.UNKNOWN.value
                    ),
                )
                if updated["status"] == FundingOccurrenceStatus.MATCHED.value and prior_status != updated["status"]:
                    matched += 1
                if updated["status"] == FundingOccurrenceStatus.MISSING.value and prior_status != updated["status"]:
                    missing += 1
            alerts_sent = self.deliver_alerts(environment=environment, now=tick_now)
            return {
                "status": "completed",
                "materialized": materialized,
                "matched": matched,
                "missing": missing,
                "directEvaluated": direct_evaluated,
                "alertsSent": alerts_sent,
                **self._funding_heartbeat_payload(environment),
            }
        finally:
            self.registry.state.release_session_lock(lock_token)

    def _funding_heartbeat_payload(self, environment: Environment) -> dict[str, Any]:
        states = self.registry.state.rows(
            FUNDING_SYNC_STATE_TABLE,
            filters={"environment": environment.value},
        )
        coverage_values = [
            row["coverage_through_at"]
            for row in states
            if isinstance(row.get("coverage_through_at"), datetime)
        ]
        alert_counts = {
            status: 0 for status in ("pending", "sending", "failed", "sent")
        }
        for alert in self.repository.alerts(environment):
            delivery_status = str(alert.get("delivery_status") or "pending")
            if delivery_status in alert_counts:
                alert_counts[delivery_status] += 1
        return {
            "fundingAccountCount": len(states),
            "fundingCoverageThroughAt": (
                min(coverage_values).astimezone(UTC).isoformat()
                if coverage_values
                else None
            ),
            "fundingAlertCounts": alert_counts,
        }

    def _unmaterialized_fixed_due_times(
        self,
        *,
        environment: Environment,
        schedule: FundingSchedule,
        account_ref: str,
        now: datetime,
    ) -> list[datetime]:
        latest_due = self._most_recent_due(schedule, now)
        existing = [
            row
            for row in self.repository.list_occurrences(environment, limit=FUNDING_MAX_API_LIMIT)
            if row["schedule_id"] == schedule.id and row["account_ref"] == account_ref
        ]
        if not existing:
            return [latest_due] if latest_due <= now else []
        newest_existing = max(row["due_at"] for row in existing)
        if newest_existing >= latest_due:
            return []
        candidates: list[datetime] = []
        if schedule.cadence == FundingCadence.WEEKLY:
            candidate = latest_due
            for _ in range(260):
                if candidate <= newest_existing:
                    break
                candidates.append(candidate)
                candidate = schedule_due_at(
                    schedule,
                    candidate.astimezone(EASTERN).date() - timedelta(days=7),
                )
        else:
            local = now.astimezone(EASTERN).date().replace(day=1)
            for months_back in range(260):
                month_index = local.year * 12 + local.month - 1 - months_back
                year, zero_based_month = divmod(month_index, 12)
                candidate = schedule_due_at(
                    schedule,
                    date(year, zero_based_month + 1, 1),
                )
                if candidate <= newest_existing:
                    break
                if candidate <= latest_due:
                    candidates.append(candidate)
        return sorted(set(candidates))

    def deliver_alerts(self, *, environment: Environment, now: datetime) -> int:
        """Deliver due funding alerts with bounded retries and safe content."""

        if self.notification_adapter is None or not self.notification_recipients:
            return 0
        sent_count = 0
        for alert in self.repository.alerts(environment):
            if alert["delivery_status"] in {"sent", "sending"} or alert["attempt_count"] >= 5:
                continue
            next_attempt = alert.get("next_attempt_at")
            if isinstance(next_attempt, datetime) and next_attempt > now:
                continue
            occurrence = self.repository.occurrence(alert["occurrence_id"])
            if occurrence is None:
                continue
            with UnitOfWork(self.registry.state) as unit:
                self.registry.state.lock_transaction_key(f"funding-alert-delivery:{alert['id']}")
                current_rows = self.registry.state.rows(
                    FUNDING_ALERT_OUTBOX_TABLE,
                    ids={alert["id"]},
                )
                if not current_rows:
                    unit.commit()
                    continue
                current_alert = current_rows[0]
                if (
                    current_alert["delivery_status"] in {"sent", "sending"}
                    or int(current_alert["attempt_count"]) >= 5
                ):
                    unit.commit()
                    continue
                attempts = int(current_alert["attempt_count"]) + 1
                self.registry.state.update_by_id(
                    FUNDING_ALERT_OUTBOX_TABLE,
                    alert["id"],
                    {
                        "delivery_status": "sending",
                        "attempt_count": attempts,
                        "next_attempt_at": None,
                        "updated_at": now,
                    },
                )
                unit.commit()
            transition = alert["transition_type"]
            subject = (
                "Recurring funding deposit recovered"
                if transition == "recovery"
                else "Recurring funding deposit needs attention"
            )
            body = (
                f"Environment: {occurrence['environment']}\n"
                f"Venue: {occurrence['venue']}\n"
                f"Provider: {occurrence['model_provider']}\n"
                f"Schedule: {occurrence['schedule_id']}\n"
                f"Status: {occurrence['status']}\n"
                f"Due: {occurrence['due_at'].isoformat()}\n"
            )
            try:
                result = self.notification_adapter.send_alert(
                    EmailMessage(
                        recipients=self.notification_recipients,
                        subject=subject,
                        body=body,
                    )
                )
            except Exception as exc:
                retry_minutes = min(60, 2 ** max(0, attempts - 1))
                self.registry.state.update_by_id(
                    FUNDING_ALERT_OUTBOX_TABLE,
                    alert["id"],
                    {
                        "delivery_status": "failed",
                        "next_attempt_at": now + timedelta(minutes=retry_minutes),
                        "provider_message_id": None,
                        "last_error": f"{type(exc).__name__}: alert delivery failed"[:240],
                        "updated_at": now,
                    },
                )
                continue
            if result.sent:
                values = {
                    "delivery_status": "sent",
                    "attempt_count": attempts,
                    "next_attempt_at": None,
                    "provider_message_id": result.message_id,
                    "last_error": None,
                    "updated_at": now,
                }
                sent_count += 1
            else:
                retry_minutes = min(60, 2 ** max(0, attempts - 1))
                values = {
                    "delivery_status": "failed",
                    "attempt_count": attempts,
                    "next_attempt_at": now + timedelta(minutes=retry_minutes),
                    "provider_message_id": None,
                    "last_error": (result.error_summary or "SES delivery failed")[:240],
                    "updated_at": now,
                }
            self.registry.state.update_by_id(FUNDING_ALERT_OUTBOX_TABLE, alert["id"], values)
        return sent_count

    def _latest_account_snapshot(
        self,
        environment: Environment,
        schedule: FundingSchedule,
    ) -> dict[str, Any] | None:
        rows = self.registry.state.rows(
            f"{SHARED_SCHEMA}.venue_portfolio_snapshots",
            filters={
                "environment": environment.value,
                "venue": schedule.venue.value,
                "model_provider": schedule.model_provider.value,
                "status": "ready",
            },
        )
        if not rows:
            return None
        return max(rows, key=lambda row: (row.get("observed_at") or datetime.min.replace(tzinfo=UTC), row["id"]))

    def _low_balance_episode_exists(
        self,
        *,
        environment: Environment,
        schedule: FundingSchedule,
        latest_snapshot: dict[str, Any],
    ) -> bool:
        snapshots = self.registry.state.rows(
            f"{SHARED_SCHEMA}.venue_portfolio_snapshots",
            filters={
                "environment": environment.value,
                "venue": schedule.venue.value,
                "model_provider": schedule.model_provider.value,
                "account_ref": latest_snapshot["account_ref"],
                "status": "ready",
            },
        )
        target = Decimal(str(schedule.target_balance_usd))
        rearmed_at = max(
            (
                row["observed_at"]
                for row in snapshots
                if row.get("buying_power_usd") is not None
                and Decimal(str(row["buying_power_usd"])) >= target
            ),
            default=None,
        )
        occurrences = [
            row
            for row in self.repository.list_occurrences(environment, limit=500)
            if row["schedule_id"] == schedule.id
            and row["account_ref"] == latest_snapshot["account_ref"]
            and row.get("low_balance_episode_key")
        ]
        if rearmed_at is not None:
            occurrences = [row for row in occurrences if row["due_at"] > rearmed_at]
        return bool(occurrences)

    def _most_recent_due(self, schedule: FundingSchedule, now: datetime) -> datetime:
        local_date = now.astimezone(EASTERN).date()
        due = schedule_due_at(schedule, local_date)
        if due <= now:
            return due
        if schedule.cadence == FundingCadence.WEEKLY:
            return schedule_due_at(schedule, local_date - timedelta(days=7))
        first = local_date.replace(day=1)
        prior_month_end = first - timedelta(days=1)
        return schedule_due_at(schedule, prior_month_end.replace(day=1))

    def _match_deadline(self, due_at: datetime, config: FundingConfig) -> datetime:
        deadline = add_business_days(due_at, config.missing_after_business_days)
        assert isinstance(deadline, datetime)
        return deadline


__all__ = [
    "AdjustedTradingPerformance",
    "FundingRepository",
    "FundingService",
    "add_business_days",
    "adjust_to_business_day",
    "adjusted_trading_performance",
    "calculate_low_balance_gap",
    "funding_account_ref",
    "normalize_alpaca_funding_activity",
    "normalize_polymarket_funding_activity",
    "schedule_due_at",
    "us_federal_holidays",
]
