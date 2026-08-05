"""Regression contracts for manual SigNoz alert triage."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[4]
    / ".github"
    / "workflows"
    / "signoz-codex-alert.yml"
)


def test_obs_030_alert_triage_remains_manual_only() -> None:
    """OBS-030: alert triage must not resume automatic Codex runs."""

    workflow = WORKFLOW_PATH.read_text()

    assert "workflow_dispatch:" in workflow
    assert "issues:" not in workflow.split("permissions:", 1)[0]
    assert "issue_number:" in workflow
    assert "operation:" in workflow


def test_obs_030_close_resolved_requires_latest_resolved_notification() -> None:
    """OBS-030: a stale resolved label must not close a firing alert."""

    workflow = WORKFLOW_PATH.read_text()

    assert "latest_signoz_status: ${{ steps.issue.outputs.latest_signoz_status }}" in workflow
    assert "github.rest.issues.listComments" in workflow
    assert "latestStatus !== 'resolved'" in workflow
    assert "latest_signoz_status == 'resolved'" in workflow
    assert "Latest SigNoz status is not resolved" in workflow
