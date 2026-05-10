"""Spec tests for final traceability and release readiness verification."""

from __future__ import annotations

from app.bootstrap import PROJECT_ROOT
from app.services import (
    release_readiness_summary,
    scan_traceability,
)


def test_req_obs_005_02_traceability_verification_covers_every_requirement() -> None:
    """TST-REQ-OBS-005-02: Validates REQ-OBS-005

    Given: requirements, spec tests, implementation files, and design docs
    When: traceability verification runs
    Then: every requirement has at least one test and one implementation or approved design trace
    """
    result = scan_traceability(PROJECT_ROOT)

    assert result.ok
    assert result.requirement_count > 0
    assert not result.missing_tests
    assert not result.missing_implementation_or_design


def test_req_obs_006_02_traceability_verification_fails_for_uncovered_requirement() -> None:
    """TST-REQ-OBS-006-02: Validates REQ-OBS-006

    Given: one requirement has no matching test or implementation trace
    When: readiness verification receives the uncovered requirement
    Then: the result fails and identifies the missing coverage
    """
    result = scan_traceability(
        PROJECT_ROOT,
        requirement_ids=("REQ-OBS-999",),
    )

    assert not result.ok
    assert result.missing_tests == ("REQ-OBS-999",)
    assert result.missing_implementation_or_design == ("REQ-OBS-999",)


def test_req_dep_005_03_no_pending_spec_tests_remain() -> None:
    """TST-REQ-DEP-005-03: Validates REQ-DEP-005

    Given: the spec suite is ready for release review
    When: traceability verification scans spec tests
    Then: no pending red-phase placeholders remain outside the helper definition
    """
    result = scan_traceability(PROJECT_ROOT)

    assert result.pending_tests == ()


def test_req_obs_006_03_release_readiness_checks_are_passed_or_deferred() -> None:
    """TST-REQ-OBS-006-03: Validates REQ-OBS-006

    Given: audit, health, deployment, and live-trading safety checks
    When: release readiness is reviewed
    Then: each area is passing or explicitly deferred with a reason
    """
    summary = release_readiness_summary(PROJECT_ROOT)

    assert summary.ok
    assert {check.name for check in summary.checks} == {
        "audit",
        "health",
        "deployment",
        "live_trading_safety",
    }
    assert all(check.status in {"pass", "deferred"} for check in summary.checks)
    assert all(check.reason for check in summary.checks if check.status == "deferred")
