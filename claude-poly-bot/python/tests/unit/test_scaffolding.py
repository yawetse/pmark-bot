"""M0 scaffolding smoke tests. Verify the test harness itself is wired up."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


def test_package_importable() -> None:
    import claude_poly_bot

    assert claude_poly_bot.__version__ == "0.1.0"


def test_factories_module_importable() -> None:
    from tests import factories

    uuid_a = factories.fresh_uuid()
    uuid_b = factories.fresh_uuid()
    assert uuid_a != uuid_b

    now = factories.utc_now()
    assert now.tzinfo is not None


def test_fake_clock_advance(fake_clock) -> None:  # type: ignore[no-untyped-def]
    """FakeClock from conftest advances correctly and stays in UTC."""
    start = fake_clock.now()
    fake_clock.advance(timedelta(hours=1))
    assert fake_clock.now() - start == timedelta(hours=1)
    assert fake_clock.now().tzinfo == UTC


def test_fake_clock_rejects_naive_datetime() -> None:
    from tests.conftest import _FakeClock

    with pytest.raises(ValueError, match="timezone-aware"):
        _FakeClock(datetime(2026, 4, 26, 12, 0, 0))  # naive
