"""Shared helpers for red-phase specification tests."""

from __future__ import annotations

import pytest


def pending(test_id: str, requirement_id: str) -> None:
    """Fail a spec test until the requirement is implemented."""
    pytest.fail(f"Not implemented - {requirement_id} ({test_id})")
