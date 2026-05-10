"""Traceability and release readiness verification.

REQ: REQ-DEP-005, REQ-OBS-001, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005,
REQ-OBS-006
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.bootstrap import (
    PROJECT_ROOT,
    aws_infrastructure_check,
    ci_workflow_check,
    deployment_resource_separation_check,
    safe_defaults,
)


REQ_ID_PATTERN = re.compile(r"REQ-[A-Z]+-\d{3}")
TEST_ID_PATTERN = re.compile(r"TST-(REQ-[A-Z]+-\d{3})-\d{2}")
REQUIREMENT_TABLE_PATTERN = re.compile(r"^\|\s*(REQ-[A-Z]+-\d{3})\s*\|", re.MULTILINE)

TEST_SOURCE_GLOB = "backend/tests/spec/test_*.py"
IMPLEMENTATION_GLOBS = (
    "backend/app/**/*.py",
    "frontend/app/**/*",
    "frontend/lib/**/*",
    "frontend/scripts/**/*",
    "frontend/README.md",
    "infra/**/*",
    "docs/**/*.md",
    ".github/workflows/*.yml",
)
APPROVED_DESIGN_PATHS = (
    "design-hld.md",
    "design-lld.md",
)


@dataclass(frozen=True)
class TraceabilityScanResult:
    """Coverage result for requirement-to-test and requirement-to-trace checks.

    REQ: REQ-DEP-005, REQ-OBS-005, REQ-OBS-006
    """

    requirement_ids: tuple[str, ...]
    tested_requirement_ids: tuple[str, ...]
    traced_requirement_ids: tuple[str, ...]
    missing_tests: tuple[str, ...]
    missing_implementation_or_design: tuple[str, ...]
    pending_tests: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return whether every requirement has coverage and no pending specs.

        REQ: REQ-DEP-005, REQ-OBS-006
        """

        return not (
            self.missing_tests
            or self.missing_implementation_or_design
            or self.pending_tests
        )

    @property
    def requirement_count(self) -> int:
        """Return the number of requirements included in this scan.

        REQ: REQ-OBS-005
        """

        return len(self.requirement_ids)


@dataclass(frozen=True)
class ReleaseReadinessCheck:
    """One release readiness check area.

    REQ: REQ-OBS-006
    """

    name: str
    status: str
    reason: str


@dataclass(frozen=True)
class ReleaseReadinessSummary:
    """Release readiness state for operational review.

    REQ: REQ-OBS-005, REQ-OBS-006
    """

    checks: tuple[ReleaseReadinessCheck, ...]

    @property
    def ok(self) -> bool:
        """Return whether release review has no failing check.

        REQ: REQ-OBS-006
        """

        return all(check.status in {"pass", "deferred"} for check in self.checks)


def extract_requirement_ids(text: str) -> tuple[str, ...]:
    """Return unique requirement IDs in first-seen order.

    REQ: REQ-OBS-005
    """

    return _unique(REQ_ID_PATTERN.findall(text))


def requirement_ids_from_requirements(root: Path = PROJECT_ROOT) -> tuple[str, ...]:
    """Return requirements declared in the product requirements table.

    REQ: REQ-OBS-005
    """

    requirements_path = root / "requirements.md"
    if not requirements_path.is_file():
        return ()
    return _unique(REQUIREMENT_TABLE_PATTERN.findall(requirements_path.read_text()))


def scan_traceability(
    root: Path = PROJECT_ROOT,
    *,
    requirement_ids: tuple[str, ...] | None = None,
) -> TraceabilityScanResult:
    """Verify requirement coverage across tests and implementation traces.

    REQ: REQ-DEP-005, REQ-OBS-005, REQ-OBS-006
    """

    declared_requirements = requirement_ids or requirement_ids_from_requirements(root)
    tested_requirement_ids = _tested_requirement_ids(root)
    traced_requirement_ids = _traced_requirement_ids(root)
    pending_tests = _pending_spec_tests(root)

    missing_tests = tuple(
        requirement_id
        for requirement_id in declared_requirements
        if requirement_id not in tested_requirement_ids
    )
    missing_traces = tuple(
        requirement_id
        for requirement_id in declared_requirements
        if requirement_id not in traced_requirement_ids
    )

    return TraceabilityScanResult(
        requirement_ids=tuple(declared_requirements),
        tested_requirement_ids=tested_requirement_ids,
        traced_requirement_ids=traced_requirement_ids,
        missing_tests=missing_tests,
        missing_implementation_or_design=missing_traces,
        pending_tests=pending_tests,
    )


def release_readiness_summary(root: Path = PROJECT_ROOT) -> ReleaseReadinessSummary:
    """Return audit, health, deployment, and live safety readiness checks.

    REQ: REQ-OBS-005, REQ-OBS-006
    """

    traceability = scan_traceability(root)
    deployment_ok = (
        ci_workflow_check(root).ok
        and aws_infrastructure_check(root).ok
        and deployment_resource_separation_check(root).ok
    )

    checks = (
        _readiness_check(
            name="audit",
            passed=_requirements_have_tests_and_traces(
                traceability,
                ("REQ-OBS-003", "REQ-OBS-004"),
            ),
            pass_reason="Audit requirements have tests and implementation or design traces.",
            fail_reason="Audit requirements are missing test or trace coverage.",
        ),
        _readiness_check(
            name="health",
            passed=_requirements_have_tests_and_traces(
                traceability,
                ("REQ-OBS-005", "REQ-OBS-006"),
            ),
            pass_reason="Health and dashboard observability requirements have coverage.",
            fail_reason="Health readiness requirements are missing coverage.",
        ),
        _readiness_check(
            name="deployment",
            passed=deployment_ok,
            pass_reason="CI, AWS infrastructure, and environment separation checks pass.",
            fail_reason="Deployment validation has at least one failing check.",
        ),
        _live_trading_safety_check(),
    )
    return ReleaseReadinessSummary(checks=checks)


def _tested_requirement_ids(root: Path) -> tuple[str, ...]:
    requirement_ids: list[str] = []
    for path in sorted(root.glob(TEST_SOURCE_GLOB)):
        requirement_ids.extend(TEST_ID_PATTERN.findall(path.read_text()))
    return _unique(requirement_ids)


def _traced_requirement_ids(root: Path) -> tuple[str, ...]:
    requirement_ids: list[str] = []
    for pattern in IMPLEMENTATION_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                requirement_ids.extend(extract_requirement_ids(path.read_text()))
    for relative_path in APPROVED_DESIGN_PATHS:
        path = root / relative_path
        if path.is_file():
            requirement_ids.extend(extract_requirement_ids(path.read_text()))
    return _unique(requirement_ids)


def _pending_spec_tests(root: Path) -> tuple[str, ...]:
    pending: list[str] = []
    for path in sorted(root.glob("backend/tests/spec/test_*.py")):
        text = path.read_text()
        if "pending(" in text:
            pending.append(str(path.relative_to(root)))
    return tuple(pending)


def _requirements_have_tests_and_traces(
    traceability: TraceabilityScanResult,
    requirement_ids: tuple[str, ...],
) -> bool:
    return all(
        requirement_id not in traceability.missing_tests
        and requirement_id not in traceability.missing_implementation_or_design
        for requirement_id in requirement_ids
    )


def _readiness_check(
    *,
    name: str,
    passed: bool,
    pass_reason: str,
    fail_reason: str,
) -> ReleaseReadinessCheck:
    if passed:
        return ReleaseReadinessCheck(name=name, status="pass", reason=pass_reason)
    return ReleaseReadinessCheck(name=name, status="fail", reason=fail_reason)


def _live_trading_safety_check() -> ReleaseReadinessCheck:
    defaults = safe_defaults()
    if defaults.live_enabled:
        return ReleaseReadinessCheck(
            name="live_trading_safety",
            status="fail",
            reason="Safe defaults must not enable live trading.",
        )
    return ReleaseReadinessCheck(
        name="live_trading_safety",
        status="deferred",
        reason=(
            "Live trading enablement is deferred until production credentials, "
            "account approvals, and operator signoff are configured."
        ),
    )


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)
