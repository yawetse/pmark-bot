"""Clock port (HLD DD-021).

All time-sensitive code in the bot takes a `Clock` instance rather than calling
`datetime.now()` directly. This makes UTC-boundary logic, EOD-flatten timing,
and stale-thesis aging deterministically testable via `FakeClock`.

Traces: HLD DD-021, R19, REQ-RISK-001, REQ-EXIT-004, REQ-EXIT-006, REQ-EXIT-014.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN_ET = time(9, 30)
_MARKET_CLOSE_ET = time(16, 0)
_FLATTEN_THRESHOLD_ET = time(15, 55)


@runtime_checkable
class Clock(Protocol):
    """Time provider port. Concrete adapters wrap real wall-clock or fake."""

    def now(self) -> datetime:
        """Returns the current time as a timezone-aware UTC datetime."""
        ...

    def et_now(self) -> datetime:
        """Returns the current time in America/New_York for market-hours logic."""
        ...


# REQ: HLD DD-021 - default clock adapter
class RealClock:
    """Production clock backed by the wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def et_now(self) -> datetime:
        return datetime.now(_ET)


# REQ: HLD DD-021 - test clock for time-travel
class FakeClock:
    """Test clock. Construct with a timezone-aware datetime; advance/set freely."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._now

    def et_now(self) -> datetime:
        return self._now.astimezone(_ET)

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self._now = at.astimezone(UTC)


# ---------------------------------------------------------------------------
# Helpers — pure, no Clock dependency. Take a datetime, return a datetime/bool.
# ---------------------------------------------------------------------------


def utc_day_start(t: datetime) -> datetime:
    """Floor a UTC datetime to 00:00:00 of the same UTC date.

    Idempotent: passing 00:00:00 returns the same instant.
    Raises ValueError on naive datetime.
    """
    if t.tzinfo is None:
        raise ValueError("utc_day_start requires a timezone-aware datetime")
    t_utc = t.astimezone(UTC)
    return datetime.combine(t_utc.date(), time(0, 0, 0), tzinfo=UTC)


def next_utc_day(t: datetime) -> datetime:
    """Return the start of the next UTC day after `t` (always strictly later)."""
    if t.tzinfo is None:
        raise ValueError("next_utc_day requires a timezone-aware datetime")
    t_utc = t.astimezone(UTC)
    return utc_day_start(t_utc) + timedelta(days=1)


def is_us_equity_market_open(et_now: datetime, *, holidays: set[date] | None = None) -> bool:
    """True if `et_now` is during a regular US equity session.

    Half-open interval [09:30, 16:00) on a weekday that is not in `holidays`.
    """
    if et_now.tzinfo is None:
        raise ValueError("is_us_equity_market_open requires a timezone-aware datetime")
    et = et_now.astimezone(_ET)
    if et.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if holidays is not None and et.date() in holidays:
        return False
    t = et.time()
    return _MARKET_OPEN_ET <= t < _MARKET_CLOSE_ET


def eod_flatten_threshold(et_now: datetime, *, holidays: set[date] | None = None) -> bool:
    """True if `et_now` is past the 15:55 ET flatten threshold on a trading day.

    REQ-EXIT-014: positions must be flat by close on Alpaca; the exit loop checks
    this predicate each tick.
    """
    if et_now.tzinfo is None:
        raise ValueError("eod_flatten_threshold requires a timezone-aware datetime")
    et = et_now.astimezone(_ET)
    if et.weekday() >= 5:
        return False
    if holidays is not None and et.date() in holidays:
        return False
    t = et.time()
    return _FLATTEN_THRESHOLD_ET <= t < _MARKET_CLOSE_ET
