"""Spec tests for AI tick summary generation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services.tick_summary_service import TickSummaryRequest, TickSummaryService


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


def test_req_obs_005_tick_summary_retries_with_low_cost_fallback_model() -> None:
    """TST-REQ-OBS-005-09: Validates REQ-OBS-005

    Given: the configured OpenAI tick summary model fails
    When: a fallback model is configured
    Then: the summary retries with the fallback and records provider usage
    """

    registry = RepositoryRegistry()
    transport = RecordingSummaryTransport()
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
    assert result.warnings == ["Primary tick summary model failed (unavailable-model); used gpt-4.1-nano."]
    assert [call["payload"]["model"] for call in transport.calls] == [
        "unavailable-model",
        "gpt-4.1-nano",
    ]
    usage_rows = registry.state.rows("shared.ai_usage_events")
    assert len(usage_rows) == 1
    assert usage_rows[0]["model"] == "gpt-4.1-nano"
    assert Decimal(str(usage_rows[0]["cost_usd"])) == Decimal("0.0000180")

