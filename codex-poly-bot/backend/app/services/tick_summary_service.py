"""AI-assisted summaries for recent pipeline ticks.

REQ: REQ-OBS-005, REQ-UI-008
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider
from app.services.llm_service import (
    HttpxProviderTransport,
    LlmUsageEvent,
    RepositoryLlmUsageRecorder,
    TokenPricing,
    token_pricing_from_env,
)


DEFAULT_TICK_SUMMARY_MODEL = "gpt-5-nano"
DEFAULT_TICK_SUMMARY_FALLBACK_MODEL = "gpt-4.1-nano"
DEFAULT_TICK_SUMMARY_WINDOW_MINUTES = 10
DEFAULT_TICK_SUMMARY_CACHE_SECONDS = 60
DEFAULT_TICK_SUMMARY_PROMPT_VERSION = "tick-summary-v1"
DEFAULT_TICK_SUMMARY_MAX_OUTPUT_TOKENS = 4096
DEFAULT_GPT_5_NANO_INPUT_COST_PER_MILLION = Decimal("0.05")
DEFAULT_GPT_5_NANO_OUTPUT_COST_PER_MILLION = Decimal("0.40")
DEFAULT_GPT_4_1_NANO_INPUT_COST_PER_MILLION = Decimal("0.10")
DEFAULT_GPT_4_1_NANO_OUTPUT_COST_PER_MILLION = Decimal("0.40")
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[3] / "docs" / "tick-summary-system-prompt.md"
LOGGER = logging.getLogger(__name__)
DEFAULT_TICK_SUMMARY_SYSTEM_PROMPT = """# Tick Summary System Prompt

You are summarizing Codex Poly Bot tick history for an operator dashboard.

## System FAQ

### What is a tick?

A tick is one manual or scheduled pipeline run. Each tick has an actor, trigger, timestamps, a final status, and five ordered steps.

### What are the five steps?

1. Data fetch: pulls market data from enabled venues such as Polymarket and Alpaca.
2. Scanner: applies deterministic filters to priced candidates and records accepted or rejected candidates.
3. Reasoning / brain: scores accepted candidates with configured model providers and records thesis, confidence, probability, and cost.
4. Execution: turns approved strategy consensus outputs into order intents, then submits or simulates orders based on live gates.
5. Exit: checks open positions for profit targets, stale theses, or volume spikes and records exit intents.

### What should the summary explain?

Explain what changed in the last window, which steps ran, where the pipeline stopped, what decisions were made, and whether the end result was useful or blocked.

### What should the summary avoid?

Do not invent trades, fills, profits, model scores, or provider calls. Do not claim live orders were submitted unless the step output says so. Do not expose secrets, API keys, wallet private keys, or raw authorization material.

### Output style

Use concise operator language. Prefer bullets. Call out blockers, rate limits, missing credentials, skipped steps, and unusual costs. If there were no meaningful events, say that directly.
"""

TICK_SUMMARY_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary_markdown": {"type": "string"},
        "key_events": {
            "type": "array",
            "items": {"type": "string"},
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary_markdown", "key_events", "warnings"],
}


@dataclass(frozen=True)
class TickSummaryRequest:
    environment: Environment
    runs: list[dict[str, Any]]
    window_minutes: int = DEFAULT_TICK_SUMMARY_WINDOW_MINUTES
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class TickSummaryResult:
    status: str
    model: str
    prompt_version: str
    summary_markdown: str
    key_events: list[str]
    warnings: list[str]
    usage: dict[str, Any]
    input_hash: str
    error_code: str | None = None
    message: str = ""


class TickSummaryService:
    """Build a low-cost OpenAI summary from recent secret-safe tick records."""

    def __init__(
        self,
        *,
        registry: RepositoryRegistry,
        environ: Mapping[str, str],
        transport: HttpxProviderTransport | None = None,
    ) -> None:
        self.registry = registry
        self.environ = environ
        self.transport = transport or HttpxProviderTransport(timeout_seconds=20.0)

    def summarize(self, request: TickSummaryRequest) -> TickSummaryResult:
        model = _summary_model_candidates(self.environ)[0]
        prompt_version = str(
            self.environ.get("OPENAI_TICK_SUMMARY_PROMPT_VERSION")
            or DEFAULT_TICK_SUMMARY_PROMPT_VERSION
        )
        summary_input = _summary_input(request)
        input_hash = _input_hash(summary_input)
        if not request.runs:
            return TickSummaryResult(
                status="empty",
                model=model,
                prompt_version=prompt_version,
                summary_markdown=(
                    f"No ticks ran in the last {request.window_minutes} minutes."
                ),
                key_events=[],
                warnings=[],
                usage=_empty_usage(),
                input_hash=input_hash,
                message="No recent tick history was available to summarize.",
            )
        if not _summary_enabled(self.environ):
            return _local_unavailable_summary(
                request=request,
                model=model,
                prompt_version=prompt_version,
                input_hash=input_hash,
            )

        failures: list[tuple[str, Exception]] = []
        for candidate_model in _summary_model_candidates(self.environ):
            try:
                body = self.transport.post_json(
                    url=f"{_openai_base_url(self.environ)}/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.environ.get('OPENAI_API_KEY')}",
                        "Content-Type": "application/json",
                    },
                    payload=_openai_summary_payload(
                        model=candidate_model,
                        summary_input=summary_input,
                        environ=self.environ,
                    ),
                )
                parsed = json.loads(_openai_response_text(body))
                usage = _usage_payload(
                    body=body,
                    model=candidate_model,
                    environment=request.environment,
                    registry=self.registry,
                    latest_run_id=_latest_run_id(request.runs),
                    window_minutes=request.window_minutes,
                    pricing=_tick_summary_pricing(candidate_model, self.environ),
                )
                warnings = []
                if failures:
                    failed_models = ", ".join(model for model, _ in failures)
                    warnings.append(
                        f"Primary tick summary model failed ({failed_models}); used {candidate_model}."
                    )
                return TickSummaryResult(
                    status="summarized",
                    model=candidate_model,
                    prompt_version=prompt_version,
                    summary_markdown=str(parsed.get("summary_markdown") or "").strip(),
                    key_events=[str(item) for item in parsed.get("key_events", [])],
                    warnings=warnings + [str(item) for item in parsed.get("warnings", [])],
                    usage=usage,
                    input_hash=input_hash,
                    message="AI summary generated from recent tick history.",
                )
            except Exception as exc:
                LOGGER.warning(
                    "tick_summary_model_failed %s",
                    json.dumps(
                        {
                            "event": "tick_summary_model_failed",
                            "model": candidate_model,
                            "error_type": exc.__class__.__name__,
                            "message": _safe_error_message(exc),
                            "input_hash": input_hash,
                        },
                        sort_keys=True,
                    ),
                )
                failures.append((candidate_model, exc))

        failed_model, failure = failures[-1]
        error_code = failure.__class__.__name__
        message = _safe_error_message(failure)
        return TickSummaryResult(
            status="error",
            model=failed_model,
            prompt_version=prompt_version,
            summary_markdown=_local_summary_markdown(request),
            key_events=_local_key_events(request),
            warnings=[
                f"OpenAI tick summary failed ({error_code}: {message}); showing local tick facts instead."
            ],
            usage=_empty_usage(),
            input_hash=input_hash,
            error_code=error_code,
            message=message,
        )


def _openai_summary_payload(
    *,
    model: str,
    summary_input: dict[str, Any],
    environ: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(summary_input, sort_keys=True),
            },
        ],
        "max_output_tokens": _int_env(
            environ,
            "OPENAI_TICK_SUMMARY_MAX_OUTPUT_TOKENS",
            DEFAULT_TICK_SUMMARY_MAX_OUTPUT_TOKENS,
        ),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "codex_poly_tick_summary",
                "schema": TICK_SUMMARY_JSON_SCHEMA,
                "strict": True,
            }
        },
    }


def _summary_model_candidates(environ: Mapping[str, str]) -> tuple[str, ...]:
    primary = str(environ.get("OPENAI_TICK_SUMMARY_MODEL") or DEFAULT_TICK_SUMMARY_MODEL).strip()
    fallback_values = [
        str(environ.get("OPENAI_TICK_SUMMARY_FALLBACK_MODEL") or DEFAULT_TICK_SUMMARY_FALLBACK_MODEL)
    ]
    fallback_values.extend(
        str(environ.get("OPENAI_TICK_SUMMARY_FALLBACK_MODELS") or "").split(",")
    )
    models: list[str] = []
    for raw_model in [primary, *fallback_values]:
        candidate = raw_model.strip()
        if candidate and candidate not in models:
            models.append(candidate)
    return tuple(models or [DEFAULT_TICK_SUMMARY_MODEL])


def _safe_error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if not message:
        return "provider request failed"
    return message[:300]


def _summary_enabled(environ: Mapping[str, str]) -> bool:
    explicit = str(environ.get("OPENAI_TICK_SUMMARY_ENABLED", "")).strip().lower()
    if explicit in {"0", "false", "no", "off"}:
        return False
    return bool(str(environ.get("OPENAI_API_KEY") or "").strip())


def _summary_input(request: TickSummaryRequest) -> dict[str, Any]:
    return {
        "environment": request.environment.value,
        "window_minutes": request.window_minutes,
        "generated_at": request.generated_at.isoformat(),
        "run_count": len(request.runs),
        "ticks": [_compact_run(run) for run in request.runs[-20:]],
    }


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    metadata = run.get("metadata", {}) if isinstance(run.get("metadata"), dict) else {}
    return _trim_payload(
        {
            "id": run.get("id"),
            "trigger": run.get("trigger"),
            "actor": metadata.get("actor"),
            "requested_mode": metadata.get("requestedMode"),
            "status": run.get("status"),
            "started_at": run.get("startedAt"),
            "completed_at": run.get("completedAt"),
            "end_result": metadata.get("endResult"),
            "steps": [
                {
                    "name": step.get("label"),
                    "key": step.get("key"),
                    "status": step.get("status"),
                    "message": step.get("message"),
                    "inputs": _summary_payload_slice(step.get("inputs")),
                    "outputs": _summary_payload_slice(step.get("outputs")),
                    "decisions": _summary_payload_slice(step.get("decisions")),
                    "metrics": step.get("metrics"),
                }
                for step in run.get("steps", [])
                if isinstance(step, dict)
            ],
        }
    )


def _summary_payload_slice(value: Any) -> Any:
    return _trim_payload(value, max_text=360, max_items=8)


def _trim_payload(value: Any, *, max_text: int = 600, max_items: int = 12) -> Any:
    if isinstance(value, str):
        return value if len(value) <= max_text else value[:max_text] + "..."
    if isinstance(value, list):
        return [_trim_payload(item, max_text=max_text, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {
            str(key): _trim_payload(item, max_text=max_text, max_items=max_items)
            for key, item in value.items()
        }
    return value


def _input_hash(summary_input: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(summary_input, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _local_unavailable_summary(
    *,
    request: TickSummaryRequest,
    model: str,
    prompt_version: str,
    input_hash: str,
) -> TickSummaryResult:
    return TickSummaryResult(
        status="unavailable",
        model=model,
        prompt_version=prompt_version,
        summary_markdown=_local_summary_markdown(request),
        key_events=_local_key_events(request),
        warnings=["OpenAI tick summary is not configured; set OPENAI_API_KEY to enable it."],
        usage=_empty_usage(),
        input_hash=input_hash,
        error_code="openai_not_configured",
        message="OpenAI API key is not configured for tick summaries.",
    )


def _local_summary_markdown(request: TickSummaryRequest) -> str:
    latest = request.runs[-1] if request.runs else {}
    status = latest.get("status", "unknown")
    return (
        f"- {len(request.runs)} tick(s) ran in the last {request.window_minutes} minutes.\n"
        f"- Latest tick status: {status}.\n"
        "- AI summary was not generated, so this is a local factual fallback."
    )


def _local_key_events(request: TickSummaryRequest) -> list[str]:
    events: list[str] = []
    for run in request.runs[-5:]:
        metadata = run.get("metadata", {}) if isinstance(run.get("metadata"), dict) else {}
        events.append(
            f"{run.get('trigger', 'unknown')} tick by {metadata.get('actor', 'unknown')} ended {run.get('status', 'unknown')}"
        )
    return events


def _empty_usage() -> dict[str, Any]:
    return {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "costUsd": "0",
        "costSource": "none",
        "responseId": None,
    }


def _usage_payload(
    *,
    body: dict[str, Any],
    model: str,
    environment: Environment,
    registry: RepositoryRegistry,
    latest_run_id: str | None,
    window_minutes: int,
    pricing: TokenPricing | None,
) -> dict[str, Any]:
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return _empty_usage()
    prompt_tokens = _usage_int(usage, "input_tokens", "prompt_tokens")
    completion_tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    if prompt_tokens == 0 and completion_tokens == 0:
        return _empty_usage()
    if pricing is None:
        cost = Decimal("0")
        cost_source = "unpriced"
    else:
        cost = pricing.cost_for(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        cost_source = "provider tokens x tick summary rate"
    response_id = body.get("id") if isinstance(body.get("id"), str) else None
    event = LlmUsageEvent(
        provider=ModelProvider.OPENAI,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        cost_source=cost_source,
        response_id=response_id,
        pipeline_run_id=latest_run_id,
        pipeline_step="tick_summary",
        usage_source="provider_response",
        raw_payload={
            "usage": dict(usage),
            "summary_window_minutes": window_minutes,
        },
    )
    RepositoryLlmUsageRecorder(registry=registry, environment=environment).record_usage(event)
    return {
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": prompt_tokens + completion_tokens,
        "costUsd": str(cost),
        "costSource": cost_source,
        "responseId": response_id,
    }


def _tick_summary_pricing(model: str, environ: Mapping[str, str]) -> TokenPricing | None:
    configured = token_pricing_from_env(ModelProvider.OPENAI, environ)
    if configured is not None:
        return configured
    if model == DEFAULT_TICK_SUMMARY_MODEL:
        return TokenPricing(
            input_cost_per_million_tokens=DEFAULT_GPT_5_NANO_INPUT_COST_PER_MILLION,
            output_cost_per_million_tokens=DEFAULT_GPT_5_NANO_OUTPUT_COST_PER_MILLION,
        )
    if model == DEFAULT_TICK_SUMMARY_FALLBACK_MODEL:
        return TokenPricing(
            input_cost_per_million_tokens=DEFAULT_GPT_4_1_NANO_INPUT_COST_PER_MILLION,
            output_cost_per_million_tokens=DEFAULT_GPT_4_1_NANO_OUTPUT_COST_PER_MILLION,
        )
    return None


def _openai_response_text(body: dict[str, Any]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in body.get("output", ()):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", ()):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not include output text")


def _system_prompt() -> str:
    try:
        prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        prompt = ""
    return prompt or DEFAULT_TICK_SUMMARY_SYSTEM_PROMPT


def _openai_base_url(environ: Mapping[str, str]) -> str:
    return str(environ.get("OPENAI_BASE_URL") or "https://api.openai.com").rstrip("/")


def _latest_run_id(runs: list[dict[str, Any]]) -> str | None:
    if not runs:
        return None
    latest = runs[-1]
    return str(latest.get("id")) if latest.get("id") else None


def _usage_int(usage: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        return max(0, parsed)
    return 0


def _int_env(environ: Mapping[str, str], name: str, default: int) -> int:
    try:
        return max(1, int(str(environ.get(name) or default)))
    except (TypeError, ValueError):
        return default
