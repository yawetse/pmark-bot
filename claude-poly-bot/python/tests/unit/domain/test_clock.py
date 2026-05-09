"""Unit tests for domain.clock.

Traces: TST-DOMAIN-CLOCK-*, REQ-RISK-001, REQ-EXIT-014, HLD DD-021.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from claude_poly_bot.domain.clock import (
    Clock,
    FakeClock,
    RealClock,
    eod_flatten_threshold,
    is_us_equity_market_open,
    next_utc_day,
    utc_day_start,
)

_ET = ZoneInfo("America/New_York")


def test_real_clock_implements_protocol() -> None:
    rc = RealClock()
    assert isinstance(rc, Clock)
    now = rc.now()
    assert now.tzinfo is not None


def test_fake_clock_implements_protocol() -> None:
    fc = FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))
    assert isinstance(fc, Clock)


def test_fake_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 4, 26, 12, 0))  # naive


def test_fake_clock_advance() -> None:
    fc = FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))
    fc.advance(timedelta(hours=2))
    assert fc.now() == datetime(2026, 4, 26, 14, 0, tzinfo=UTC)


def test_fake_clock_set_normalizes_to_utc() -> None:
    fc = FakeClock(datetime(2026, 4, 26, 12, 0, tzinfo=UTC))
    fc.set(datetime(2026, 4, 26, 8, 0, tzinfo=_ET))  # 8 AM ET = 12:00 UTC
    assert fc.now() == datetime(2026, 4, 26, 12, 0, tzinfo=UTC)


def test_fake_clock_et_now_returns_eastern() -> None:
    fc = FakeClock(datetime(2026, 4, 26, 16, 0, tzinfo=UTC))  # noon ET
    et = fc.et_now()
    assert et.tzinfo == _ET
    assert et.hour == 12


def test_utc_day_start_idempotent() -> None:
    """Boundary: 00:00:00 UTC returns itself."""
    t = datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)
    assert utc_day_start(t) == t


def test_utc_day_start_floors() -> None:
    t = datetime(2026, 4, 26, 13, 45, 30, tzinfo=UTC)
    assert utc_day_start(t) == datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)


def test_utc_day_start_rejects_naive() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_day_start(datetime(2026, 4, 26))


def test_utc_day_start_handles_non_utc_input() -> None:
    """Non-UTC tz is normalized first."""
    et_morning = datetime(2026, 4, 26, 8, 0, tzinfo=_ET)  # 12:00 UTC
    assert utc_day_start(et_morning) == datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)


def test_next_utc_day_strictly_later() -> None:
    t = datetime(2026, 4, 26, 0, 0, 0, tzinfo=UTC)
    assert next_utc_day(t) == datetime(2026, 4, 27, 0, 0, 0, tzinfo=UTC)


def test_next_utc_day_handles_midday() -> None:
    t = datetime(2026, 4, 26, 23, 59, 59, tzinfo=UTC)
    assert next_utc_day(t) == datetime(2026, 4, 27, 0, 0, 0, tzinfo=UTC)


def test_market_open_at_open_inclusive() -> None:
    """09:30 ET is open."""
    t = datetime(2026, 4, 27, 9, 30, tzinfo=_ET)  # Mon
    assert is_us_equity_market_open(t)


def test_market_open_at_close_exclusive() -> None:
    """16:00 ET is NOT open (half-open interval)."""
    t = datetime(2026, 4, 27, 16, 0, tzinfo=_ET)
    assert not is_us_equity_market_open(t)


def test_market_open_just_before_open() -> None:
    """09:29:59 ET is closed."""
    t = datetime(2026, 4, 27, 9, 29, 59, tzinfo=_ET)
    assert not is_us_equity_market_open(t)


def test_market_open_weekend_closed() -> None:
    saturday = datetime(2026, 4, 25, 12, 0, tzinfo=_ET)
    sunday = datetime(2026, 4, 26, 12, 0, tzinfo=_ET)
    assert not is_us_equity_market_open(saturday)
    assert not is_us_equity_market_open(sunday)


def test_market_open_holiday_closed() -> None:
    holiday = datetime(2026, 7, 3, 12, 0, tzinfo=_ET)  # Friday before July 4
    holidays = {date(2026, 7, 3)}
    assert not is_us_equity_market_open(holiday, holidays=holidays)


def test_eod_flatten_threshold_just_before() -> None:
    """15:54:59 ET is BEFORE the flatten threshold."""
    t = datetime(2026, 4, 27, 15, 54, 59, tzinfo=_ET)
    assert not eod_flatten_threshold(t)


def test_eod_flatten_threshold_at() -> None:
    """15:55:00 ET fires the flatten."""
    t = datetime(2026, 4, 27, 15, 55, 0, tzinfo=_ET)
    assert eod_flatten_threshold(t)


def test_eod_flatten_threshold_after_close_false() -> None:
    """16:00 ET is past close — flatten predicate returns False (window has passed)."""
    t = datetime(2026, 4, 27, 16, 0, 0, tzinfo=_ET)
    assert not eod_flatten_threshold(t)


def test_eod_flatten_threshold_weekend_false() -> None:
    saturday = datetime(2026, 4, 25, 15, 55, tzinfo=_ET)
    assert not eod_flatten_threshold(saturday)
