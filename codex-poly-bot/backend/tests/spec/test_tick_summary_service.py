"""Spec tests for AI tick summary generation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services.tick_summary_service import (
    DEFAULT_TICK_SUMMARY_MAX_OUTPUT_TOKENS,
    DEFAULT_TICK_SUMMARY_TIMEOUT_SECONDS,
    TickSummaryRequest,
    TickSummaryService,
)


class RecordingSummaryTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "headers": headers, "payload": payload})
        if len(self.calls) == 1:
            raise RuntimeError("model not available")
        return {
            "id": "resp-summary-1",
            "output_text": json.dumps(
                {
                    "summary_markdown": "- one scheduled tick ran\n- no orders submitted",
                    "key_events": ["scheduled tick ended partial"],
                    "warnings": [],
                }
            ),
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }


def test_req_obs_005_tick_summary_retries_with_low_cost_fallback_model(monkeypatch) -> None:
    """TST-REQ-OBS-005-09: Validates REQ-OBS-005

    Given: the configured OpenAI tick summary model fails
    When: a fallback model is configured
    Then: the summary retries with the fallback and records provider usage plus a handled APM event
    """

    registry = RepositoryRegistry()
    transport = RecordingSummaryTransport()
    spans: list[dict[str, Any]] = []
    recorded_failures: list[dict[str, Any]] = []
    recorded_events: list[dict[str, Any]] = []

    @contextmanager
    def recording_span(name: str, *, attributes: dict[str, Any] | None = None):
        span = {"name": name, "attributes": dict(attributes or {})}
        spans.append(span)
        yield span

    def record_failure(
        span: dict[str, Any] | None,
        exc: Exception,
        *,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        recorded_failures.append(
            {
                "span": span,
                "event_name": event_name,
                "error_type": exc.__class__.__name__,
                "attributes": dict(attributes or {}),
            }
        )

    def record_event(
        span: dict[str, Any] | None,
        *,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        recorded_events.append(
            {
                "span": span,
                "event_name": event_name,
                "attributes": dict(attributes or {}),
            }
        )

    def set_attributes(span: dict[str, Any] | None, attributes: dict[str, Any] | None) -> None:
        if span is not None:
            span["attributes"].update(attributes or {})

    monkeypatch.setattr(
        "app.services.tick_summary_service.start_observability_span",
        recording_span,
    )
    monkeypatch.setattr(
        "app.services.tick_summary_service.record_span_failure",
        record_failure,
    )
    monkeypatch.setattr(
        "app.services.tick_summary_service.record_span_event",
        record_event,
    )
    monkeypatch.setattr(
        "app.services.tick_summary_service.set_span_attributes",
        set_attributes,
    )
    service = TickSummaryService(
        registry=registry,
        environ={
            "OPENAI_API_KEY": "test-key",
            "OPENAI_TICK_SUMMARY_MODEL": "unavailable-model",
            "OPENAI_TICK_SUMMARY_FALLBACK_MODEL": "gpt-4.1-nano",
        },
        transport=transport,
    )

    result = service.summarize(
        TickSummaryRequest(
            environment=Environment.DEVELOPMENT,
            generated_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            runs=[
                {
                    "id": "run-1",
                    "trigger": "scheduled",
                    "status": "partial",
                    "metadata": {"actor": "scheduler"},
                    "steps": [],
                }
            ],
        )
    )

    assert result.status == "summarized"
    assert result.model == "gpt-4.1-nano"
    assert result.warnings == [
        "Primary tick summary model failed (unavailable-model: model not available); used gpt-4.1-nano."
    ]
    assert [call["payload"]["model"] for call in transport.calls] == [
        "unavailable-model",
        "gpt-4.1-nano",
    ]
    usage_rows = registry.state.rows("shared.ai_usage_events")
    assert len(usage_rows) == 1
    assert usage_rows[0]["model"] == "gpt-4.1-nano"
    assert Decimal(str(usage_rows[0]["cost_usd"])) == Decimal("0.0000180")
    assert [span["name"] for span in spans] == [
        "tick_summary.model_attempt",
        "tick_summary.model_attempt",
    ]
    assert spans[0]["attributes"]["model"] == "unavailable-model"
    assert spans[0]["attributes"]["attempt_number"] == 1
    assert spans[1]["attributes"]["model"] == "gpt-4.1-nano"
    assert spans[1]["attributes"]["status"] == "success"
    assert recorded_failures == []
    assert recorded_events == [
        {
            "span": spans[0],
            "event_name": "tick_summary_model_retrying",
            "attributes": {
                "model": "unavailable-model",
                "attempt_number": 1,
                "environment": "development",
                "prompt_version": "tick-summary-v1",
                "error_type": "RuntimeError",
                "message": "model not available",
                "input_hash": result.input_hash,
                "latest_run_id": "run-1",
                "window_minutes": 10,
                "status": "handled_failure",
            },
        }
    ]


def test_req_obs_005_tick_summary_marks_final_model_failure_as_trace_error(monkeypatch) -> None:
    """TST-REQ-OBS-005-12: Validates REQ-OBS-005

    Given: every configured tick-summary model fails
    When: no fallback can produce a summary
    Then: the final failure is still marked as a trace error
    """

    class FailingSummaryTransport:
        def post_json(
            self,
            *,
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            raise RuntimeError(f"{payload['model']} unavailable")

    spans: list[dict[str, Any]] = []
    recorded_failures: list[dict[str, Any]] = []
    recorded_events: list[dict[str, Any]] = []

    @contextmanager
    def recording_span(name: str, *, attributes: dict[str, Any] | None = None):
        span = {"name": name, "attributes": dict(attributes or {})}
        spans.append(span)
        yield span

    def record_failure(
        span: dict[str, Any] | None,
        exc: Exception,
        *,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        recorded_failures.append(
            {
                "span": span,
                "event_name": event_name,
                "error_type": exc.__class__.__name__,
                "attributes": dict(attributes or {}),
            }
        )

    def record_event(
        span: dict[str, Any] | None,
        *,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        recorded_events.append(
            {
                "span": span,
                "event_name": event_name,
                "attributes": dict(attributes or {}),
            }
        )

    monkeypatch.setattr(
        "app.services.tick_summary_service.start_observability_span",
        recording_span,
    )
    monkeypatch.setattr(
        "app.services.tick_summary_service.record_span_failure",
        record_failure,
    )
    monkeypatch.setattr(
        "app.services.tick_summary_service.record_span_event",
        record_event,
    )
    service = TickSummaryService(
        registry=RepositoryRegistry(),
        environ={
            "OPENAI_API_KEY": "test-key",
            "OPENAI_TICK_SUMMARY_MODEL": "primary-model",
            "OPENAI_TICK_SUMMARY_FALLBACK_MODEL": "fallback-model",
        },
        transport=FailingSummaryTransport(),
    )

    result = service.summarize(
        TickSummaryRequest(
            environment=Environment.PRODUCTION,
            generated_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            runs=[
                {
                    "id": "run-2",
                    "trigger": "scheduled",
                    "status": "partial",
                    "metadata": {"actor": "scheduler"},
                    "steps": [],
                }
            ],
        )
    )

    assert result.status == "error"
    assert result.model == "fallback-model"
    assert [event["event_name"] for event in recorded_events] == [
        "tick_summary_model_retrying"
    ]
    assert recorded_events[0]["attributes"]["status"] == "handled_failure"
    assert recorded_failures == [
        {
            "span": spans[1],
            "event_name": "tick_summary_model_failed",
            "error_type": "RuntimeError",
            "attributes": {
                "model": "fallback-model",
                "attempt_number": 2,
                "environment": "production",
                "prompt_version": "tick-summary-v1",
                "error_type": "RuntimeError",
                "message": "fallback-model unavailable",
                "input_hash": result.input_hash,
                "latest_run_id": "run-2",
                "window_minutes": 10,
            },
        }
    ]


def test_req_obs_005_tick_summary_uses_larger_output_cap_and_compact_payload() -> None:
    """TST-REQ-OBS-005-10: Validates REQ-OBS-005

    Given: many recent runs contain large step payloads
    When: the tick summary request is sent to OpenAI
    Then: the payload is compacted and the default output cap is large enough for GPT-5 nano
    """

    registry = RepositoryRegistry()
    transport = RecordingSummaryTransport()
    service = TickSummaryService(
        registry=registry,
        environ={
            "OPENAI_API_KEY": "test-key",
            "OPENAI_TICK_SUMMARY_MODEL": "gpt-4.1-nano",
        },
        transport=transport,
    )
    runs = [
        {
            "id": f"run-{index}",
            "trigger": "scheduled",
            "status": "partial",
            "metadata": {"actor": "scheduler"},
            "steps": [
                {
                    "label": "Data Fetch",
                    "key": "data_fetch",
                    "status": "partial",
                    "message": "provider call completed",
                    "outputs": [{"candidate": candidate, "body": "x" * 1000} for candidate in range(30)],
                    "decisions": [{"reason": "rejected", "details": "y" * 1000}],
                    "metrics": {"candidateCount": 420},
                }
            ],
        }
        for index in range(30)
    ]

    service.summarize(
        TickSummaryRequest(
            environment=Environment.DEVELOPMENT,
            generated_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            runs=runs,
        )
    )

    payload = transport.calls[0]["payload"]
    user_payload = json.loads(payload["input"][1]["content"])

    assert payload["max_output_tokens"] == DEFAULT_TICK_SUMMARY_MAX_OUTPUT_TOKENS == 4096
    assert "Recommendations section" in payload["input"][0]["content"]
    assert len(user_payload["ticks"]) == 20
    assert len(user_payload["ticks"][0]["steps"][0]["outputs"]) == 8
    assert user_payload["ticks"][0]["steps"][0]["outputs"][0]["body"].endswith("...")


def test_req_obs_005_tick_summary_timeout_is_configurable() -> None:
    """TST-REQ-OBS-005-11: Validates REQ-OBS-005

    Given: GPT-5 nano tick summaries may take longer than one short provider read window
    When: the operator configures a tick-summary timeout
    Then: the OpenAI transport uses that timeout without requiring code changes
    """

    configured = TickSummaryService(
        registry=RepositoryRegistry(),
        environ={"OPENAI_TICK_SUMMARY_TIMEOUT_SECONDS": "75.5"},
    )
    defaulted = TickSummaryService(
        registry=RepositoryRegistry(),
        environ={"OPENAI_TICK_SUMMARY_TIMEOUT_SECONDS": "not-a-number"},
    )

    assert configured.transport.timeout_seconds == 75.5
    assert defaulted.transport.timeout_seconds == DEFAULT_TICK_SUMMARY_TIMEOUT_SECONDS == 60.0
