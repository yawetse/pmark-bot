"""Spec-level contracts for the dashboard information architecture redesign."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def _read(relative_path: str) -> str:
    return (FRONTEND_ROOT / relative_path).read_text()


def test_req_ui_016_01_primary_navigation_and_responsive_contract() -> None:
    """TST-REQ-UI-016-01: Validates REQ-UI-016.

    TST-REQ-UI-024-01: Validates REQ-UI-024.

    Given: the authenticated dashboard shell
    When: its primary routes and responsive rules are inspected
    Then: five labeled routes remain visible without an overflow destination
    """
    navigation = _read("components/dashboard/dashboard-nav.tsx")
    styles = _read("app/globals.css")

    for label, route in (
        ("Overview", "/dashboard"),
        ("Activity", "/dashboard/activity"),
        ("Performance", "/dashboard/performance"),
        ("Settings", "/dashboard/config"),
        ("Help", "/dashboard/help"),
    ):
        assert label in navigation
        assert route in navigation
    assert "More" not in navigation
    assert "repeat(5, minmax(0, 1fr))" in styles
    assert "@media (max-width: 960px)" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles


def test_req_ui_017_01_overview_state_and_safe_recommendation_contract() -> None:
    """TST-REQ-UI-017-01: Validates REQ-UI-017.

    TST-REQ-UI-018-01: Validates REQ-UI-018.
    TST-REQ-UI-019-01: Validates REQ-UI-019.
    TST-REQ-UI-025-01: Validates REQ-UI-025.
    TST-REQ-UI-026-01: Validates REQ-UI-026.

    Given: persisted and realtime dashboard state
    When: Overview derives its primary state and offers a config change
    Then: live matching, blockers, consolidated degradation, exact paths, confirmation, and undo are present
    """
    state_model = _read("lib/dashboard-overview-state.ts")
    overview = _read("components/dashboard/overview-dashboard.tsx")

    for token in (
        'kind: "live"',
        'kind: "attention"',
        'kind: "clear"',
        "pipelineRunId",
        "latestCompletedPipeline",
        "recommendationPath",
    ):
        assert token in state_model
    for token in (
        "How things are running",
        "Recent result",
        "Explore more",
        "Confirm change",
        "Undo",
        "expected_version",
        "configSnapshotAfterSave",
    ):
        assert token in overview
    assert "state selector" not in overview


def test_req_ui_020_01_activity_uses_one_completed_run_contract() -> None:
    """TST-REQ-UI-020-01: Validates REQ-UI-020.

    Given: a persisted pipeline history
    When: Activity builds the latest funnel
    Then: counts come from one compact completed-run summary without loading step JSON
    """
    model = _read("lib/dashboard-activity-view-model.ts")
    view = _read("components/dashboard/activity-view.tsx")
    page = _read("app/dashboard/activity/page.tsx")

    for token in (
        "latestCompletedActivityRun",
        '"candidateCount"',
        '"scannerAcceptedCount"',
        '"reasoningScoredCount"',
        '"strategyApprovedCount"',
        '"orderRefusedCount"',
        "latestTradeOutcome",
        'statusLabel: "Unavailable"',
    ):
        assert token in model
    assert "setLoadErrors([])" in view
    assert "activity-stage-status" in view
    assert "Why no trade:" in view
    assert "operations/summary?include_runs=true" in page
    assert "current?.pipelineRuns ?? []" in view


def test_req_ui_020_02_operations_preserves_detailed_realtime_stages() -> None:
    page = _read("app/dashboard/operations/page.tsx")
    view = _read("components/dashboard/operations-view.tsx")

    assert "operations/summary?include_details=true&include_history=true" in page
    assert "preserveDetailedRealtimeStage" in view
    assert 'incoming.status === "deferred"' in view


def test_req_ui_021_01_performance_uses_confirmed_portfolio_contract() -> None:
    """TST-REQ-UI-021-01: Validates REQ-UI-021.

    Given: venue-confirmed portfolio state
    When: Performance builds headline and by-market results
    Then: confirmed fills own trade totals and missing closed outcomes do not create a win rate
    """
    model = _read("lib/dashboard-performance-view-model.ts")
    view = _read("components/dashboard/performance-view.tsx")

    assert "portfolio?.overall.filledTrades" in model
    assert "venue.filledTrades" in model
    assert "winRate: null" in model
    assert "Needs confirmed closed outcomes" in model
    assert "setPortfolioError(undefined)" in view


def test_req_ui_022_01_settings_fail_closed_and_help_stays_static() -> None:
    """TST-REQ-UI-022-01: Validates REQ-UI-022.

    TST-REQ-UI-023-01: Validates REQ-UI-023.

    Given: common Settings and static Help pages
    When: configuration is unavailable or operating help is opened
    Then: writes fail closed, advanced controls stay available, and the five help steps remain ordered
    """
    settings = _read("components/dashboard/config-controls.tsx")
    help_view = _read("components/dashboard/help-about-view.tsx")

    for token in (
        "No settings can be changed until a versioned snapshot is available",
        "Advanced settings and risk controls",
        "configRecipientKey(snapshot)",
        'expected_version: currentVersion === "bootstrap" ? null : currentVersion',
    ):
        assert token in settings
    positions = [
        help_view.index(step)
        for step in (
            "Collect prices",
            "Find candidates",
            "Score",
            "Simulate or submit",
            "Monitor exits",
        )
    ]
    assert positions == sorted(positions)
    assert "Back to Overview" in help_view
