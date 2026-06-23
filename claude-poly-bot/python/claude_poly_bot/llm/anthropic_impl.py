"""AnthropicStrategist — Claude-backed Strategist implementation.

Wires the Anthropic SDK (>=0.40) into the Strategist port. Renders prompts
via PromptRegistry, sends with prompt caching on the system block, requests
structured JSON output, optionally enables the server-side web_search tool,
parses the response into a CheckResult, and persists the call via
DecisionRepo.

Traces: REQ-LLM-001..010, REQ-BRN-005 (web search per check), REQ-BRN-006
(structured JSON), REQ-BRN-008 (malformed JSON retry), REQ-BRN-010 (prompt
caching), REQ-BRN-014 (rate-limit retry), REQ-BRN-015 (sustained-error
halt).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from claude_poly_bot.domain.clock import Clock
from claude_poly_bot.domain.exceptions import (
    LLMSustainedErrorsError,
    MalformedResponseError,
)
from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    Market,
    PolymarketMarket,
    Probability,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.protocols import StrategistContext
from claude_poly_bot.llm.prompts import PromptRegistry

logger = logging.getLogger(__name__)

# REQ: REQ-BRN-006 - structured JSON output schema.
CHECK_RESULT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["BUY", "SELL", "SKIP"]},
        "confidence": {"type": "number"},
        "p_win": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "p_win", "rationale"],
    "additionalProperties": False,
}

# REQ: REQ-BRN-005 - web search tool spec (Anthropic server-side, GA).
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
}

# Pricing (USD per token). Source: Anthropic published prices as of 2026-04.
_OPUS_INPUT = Decimal("5.0") / Decimal("1000000")
_OPUS_OUTPUT = Decimal("25.0") / Decimal("1000000")
_SONNET_INPUT = Decimal("3.0") / Decimal("1000000")
_SONNET_OUTPUT = Decimal("15.0") / Decimal("1000000")
_HAIKU_INPUT = Decimal("1.0") / Decimal("1000000")
_HAIKU_OUTPUT = Decimal("5.0") / Decimal("1000000")


class _MessagesClient(Protocol):
    """The subset of anthropic.AsyncAnthropic.messages we depend on."""

    async def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClient(Protocol):
    messages: _MessagesClient


@dataclass
class _ModelPricing:
    input_per_token: Decimal
    output_per_token: Decimal


class _DecisionRecorder(Protocol):
    """Subset of DecisionRepo this adapter calls. Decoupled so the strategist
    can be used in tests without DB wiring.
    """

    async def record(self, result: CheckResult) -> Any: ...


class AnthropicStrategist:
    """Claude-backed strategist. Use one instance per bot per process so the
    consecutive-error counter accumulates correctly (LLD §4.2.1).
    """

    bot: Bot

    def __init__(
        self,
        *,
        client: _AnthropicClient,
        prompts: PromptRegistry,
        clock: Clock,
        decision_repo: _DecisionRecorder | None = None,
        bot: Bot = Bot.CLAUDE,
        default_model: str = "claude-opus-4-7",
        max_retries_malformed: int = 2,
        consecutive_error_threshold: int = 5,
        max_tokens: int = 4096,
    ) -> None:
        self.bot = bot
        self._client = client
        self._prompts = prompts
        self._clock = clock
        self._decision_repo = decision_repo
        self._default_model = default_model
        self._max_retries_malformed = max_retries_malformed
        self._consecutive_error_threshold = consecutive_error_threshold
        self._max_tokens = max_tokens
        self._consecutive_errors = 0
        self._error_lock = asyncio.Lock()

    async def evaluate(
        self,
        check_type: CheckType,
        venue: VenueName,
        market: Market,
        context: StrategistContext,
        *,
        sub_agent: SubAgent | None = None,
        web_search: bool = False,
        model_id: str | None = None,
    ) -> CheckResult:
        # REQ: REQ-BRN-015 - if already halted, refuse.
        if self._consecutive_errors >= self._consecutive_error_threshold:
            raise LLMSustainedErrorsError(
                f"halt active: {self._consecutive_errors} consecutive failures"
            )

        effective_model = model_id or self._default_model
        correlation_id = uuid4()

        system_prompt, user_prompt = self._render(check_type, venue, market, context, sub_agent)

        # REQ: REQ-BRN-008 - up to 2 retries on malformed JSON.
        last_error: str | None = None
        attempt_messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(self._max_retries_malformed + 1):
            started = self._clock.now()
            try:
                response = await self._call_anthropic(
                    model=effective_model,
                    system_prompt=system_prompt,
                    messages=attempt_messages,
                    web_search=web_search,
                )
            except LLMSustainedErrorsError:
                raise
            except Exception as e:
                # REQ: REQ-LLM-008 / REQ-BRN-015 - bump counter and return SKIP.
                await self._bump_error()
                logger.warning(
                    "anthropic_strategist_call_failed",
                    extra={
                        "venue": venue.value,
                        "check_type": check_type.value,
                        "sub_agent": sub_agent.value if sub_agent else None,
                        "model_id": effective_model,
                        "error": str(e),
                    },
                )
                return await self._record_and_return(
                    self._error_result(
                        bot=self.bot,
                        venue=venue,
                        market=market,
                        check_type=check_type,
                        sub_agent=sub_agent,
                        model_id=effective_model,
                        error=f"{type(e).__name__}: {e}",
                        correlation_id=correlation_id,
                    )
                )

            elapsed_ms = int((self._clock.now() - started).total_seconds() * 1000)

            try:
                parsed = _parse_response(response)
            except MalformedResponseError as e:
                last_error = str(e)
                logger.info(
                    "anthropic_strategist_malformed",
                    extra={
                        "attempt": attempt,
                        "venue": venue.value,
                        "check_type": check_type.value,
                        "error": last_error,
                    },
                )
                # Append the bad reply and the parser error, then retry.
                assistant_text = _first_text_block(response) or ""
                attempt_messages = [
                    *attempt_messages,
                    {"role": "assistant", "content": assistant_text},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response did not match the required JSON schema: "
                            f"{last_error}. Re-emit the answer as a single JSON object inside a "
                            f"```json fence, matching the schema exactly."
                        ),
                    },
                ]
                continue

            await self._reset_errors()
            usage = getattr(response, "usage", None)
            web_used = _used_web_search(response)
            result = CheckResult(
                bot=self.bot,
                venue=venue,
                market_id=market.external_id,
                check_type=check_type,
                sub_agent=sub_agent,
                verdict=parsed.verdict,
                confidence=parsed.confidence,
                p_win=parsed.p_win,
                rationale=parsed.rationale,
                model_id=effective_model,
                tokens_in=_get_int(usage, "input_tokens"),
                tokens_out=_get_int(usage, "output_tokens"),
                tokens_cached=(
                    _get_int(usage, "cache_read_input_tokens")
                    + _get_int(usage, "cache_creation_input_tokens")
                ),
                cost_usd=_estimate_cost_usd(effective_model, usage),
                latency_ms=elapsed_ms,
                web_search_used=web_used,
                correlation_id=correlation_id,
                raw_response=parsed.raw,
            )
            return await self._record_and_return(result)

        # All retries exhausted on malformed JSON — return SKIP.
        await self._bump_error()
        return await self._record_and_return(
            self._error_result(
                bot=self.bot,
                venue=venue,
                market=market,
                check_type=check_type,
                sub_agent=sub_agent,
                model_id=effective_model,
                error=f"malformed_response_after_retries: {last_error}",
                correlation_id=correlation_id,
            )
        )

    async def consecutive_error_count(self) -> int:
        return self._consecutive_errors

    # ---- internals ----

    def _render(
        self,
        check_type: CheckType,
        venue: VenueName,
        market: Market,
        context: StrategistContext,
        sub_agent: SubAgent | None,
    ) -> tuple[str, str]:
        market_view = _market_view(market)
        book_view = _book_view(context)
        scan_view = context.scan_score.fields.model_dump(mode="json")
        render_ctx: dict[str, object] = {
            "market": market_view,
            "book": book_view,
            "scan_score": scan_view,
            "target_wallets_hits": context.target_wallets_hits,
            "unusual_volume": context.unusual_volume,
            "recent_news": [s.model_dump(mode="json") for s in context.recent_news],
            "historical_analogs": context.historical_analogs,
            "check_results": [
                {
                    "check_type": r.check_type.value,
                    "verdict": r.verdict.value,
                    "p_win": str(r.p_win),
                    "confidence": str(r.confidence),
                    "rationale": r.rationale,
                }
                for r in context.prior_check_results
            ],
        }
        return self._prompts.render(venue, check_type, sub_agent, render_ctx)

    async def _call_anthropic(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        web_search: bool,
    ) -> Any:
        # REQ: REQ-BRN-010 / REQ-LLM-005 - prompt caching on system block.
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": messages,
            "temperature": 0.0,
            # REQ: REQ-BRN-006 - constrain output to JSON schema.
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": CHECK_RESULT_JSON_SCHEMA,
                },
            },
            # Default Opus-4.7 thinking is off; explicit for clarity.
            "thinking": {"type": "disabled"},
        }
        if web_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]
        return await self._client.messages.create(**kwargs)

    async def _bump_error(self) -> None:
        async with self._error_lock:
            self._consecutive_errors += 1

    async def _reset_errors(self) -> None:
        async with self._error_lock:
            self._consecutive_errors = 0

    async def _record_and_return(self, result: CheckResult) -> CheckResult:
        if self._decision_repo is not None:
            try:
                await self._decision_repo.record(result)
            except Exception as e:  # repo failures should not poison the call
                logger.warning(
                    "anthropic_strategist_record_failed",
                    extra={"error": str(e), "correlation_id": str(result.correlation_id)},
                )
        return result

    @staticmethod
    def _error_result(
        *,
        bot: Bot,
        venue: VenueName,
        market: Market,
        check_type: CheckType,
        sub_agent: SubAgent | None,
        model_id: str,
        error: str,
        correlation_id: Any,
    ) -> CheckResult:
        return CheckResult(
            bot=bot,
            venue=venue,
            market_id=market.external_id,
            check_type=check_type,
            sub_agent=sub_agent,
            verdict=Verdict.SKIP,
            confidence=Decimal("0"),
            p_win=Decimal("0.5"),
            rationale=f"error: {error[:300]}",
            model_id=model_id,
            correlation_id=correlation_id,
            error=error[:500],
        )


# ---------------------------------------------------------------------------
# Free helpers (pure, testable in isolation)
# ---------------------------------------------------------------------------


@dataclass
class _Parsed:
    verdict: Verdict
    confidence: Probability
    p_win: Probability
    rationale: str
    raw: dict[str, Any]


def _parse_response(response: Any) -> _Parsed:
    """Extract and validate the JSON `CheckResult` payload from the response.

    With `output_config.format=json_schema`, the response's first text block
    contains schema-conformant JSON. Defensive: also tolerate a ```json
    fence wrapping the payload (older Claude behavior).
    """
    text = _first_text_block(response)
    if not text:
        raise MalformedResponseError("no text block in response")
    payload = _extract_json(text)
    try:
        verdict = Verdict(payload["verdict"])
    except (KeyError, ValueError) as e:
        raise MalformedResponseError(f"bad verdict: {e}") from e
    try:
        confidence = Decimal(str(payload["confidence"]))
        p_win = Decimal(str(payload["p_win"]))
    except (KeyError, ValueError, ArithmeticError) as e:
        raise MalformedResponseError(f"bad numeric field: {e}") from e
    if not (Decimal("0") <= confidence <= Decimal("1")):
        raise MalformedResponseError(f"confidence out of [0,1]: {confidence}")
    if not (Decimal("0") <= p_win <= Decimal("1")):
        raise MalformedResponseError(f"p_win out of [0,1]: {p_win}")
    rationale = payload.get("rationale", "")
    if not isinstance(rationale, str):
        raise MalformedResponseError(f"rationale not a string: {type(rationale).__name__}")
    return _Parsed(
        verdict=verdict,
        confidence=confidence,
        p_win=p_win,
        rationale=rationale.strip(),
        raw=payload,
    )


def _first_text_block(response: Any) -> str | None:
    """Return concatenated text from all 'text' blocks in `response.content`."""
    content = getattr(response, "content", None)
    if not content:
        return None
    chunks: list[str] = []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    if not chunks:
        return None
    return "\n".join(chunks)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of `text` — bare JSON or wrapped in ```json fences."""
    stripped = text.strip()
    # Strip a leading ```json fence if present.
    if stripped.startswith("```"):
        # Find the first newline after the fence (skip language tag) and the
        # last closing fence.
        first_nl = stripped.find("\n")
        if first_nl == -1:
            raise MalformedResponseError("malformed fenced block")
        body = stripped[first_nl + 1 :]
        close = body.rfind("```")
        if close == -1:
            raise MalformedResponseError("missing closing fence")
        stripped = body[:close].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise MalformedResponseError(f"invalid json: {e}") from e
    if not isinstance(parsed, dict):
        raise MalformedResponseError(f"expected JSON object, got {type(parsed).__name__}")
    return parsed


def _used_web_search(response: Any) -> bool:
    content = getattr(response, "content", None) or []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type in ("server_tool_use", "web_search_tool_result"):
            return True
    return False


def _get_int(usage: Any, attr: str) -> int:
    if usage is None:
        return 0
    val = getattr(usage, attr, 0)
    return int(val or 0)


def _pricing(model_id: str) -> _ModelPricing:
    if model_id.startswith("claude-opus"):
        return _ModelPricing(_OPUS_INPUT, _OPUS_OUTPUT)
    if model_id.startswith("claude-sonnet"):
        return _ModelPricing(_SONNET_INPUT, _SONNET_OUTPUT)
    if model_id.startswith("claude-haiku"):
        return _ModelPricing(_HAIKU_INPUT, _HAIKU_OUTPUT)
    return _ModelPricing(_OPUS_INPUT, _OPUS_OUTPUT)


def _estimate_cost_usd(model_id: str, usage: Any) -> Decimal:
    """Per Anthropic published prices; cached reads at 0.1x, writes at 1.25x."""
    if usage is None:
        return Decimal("0")
    p = _pricing(model_id)
    tokens_in = Decimal(_get_int(usage, "input_tokens"))
    tokens_out = Decimal(_get_int(usage, "output_tokens"))
    cached_read = Decimal(_get_int(usage, "cache_read_input_tokens"))
    cached_write = Decimal(_get_int(usage, "cache_creation_input_tokens"))
    cost = (
        tokens_in * p.input_per_token
        + tokens_out * p.output_per_token
        + cached_read * p.input_per_token * Decimal("0.1")
        + cached_write * p.input_per_token * Decimal("1.25")
    )
    # Quantize to 8 decimal places to match the Money field.
    return cost.quantize(Decimal("0.00000001"))


def _market_view(market: Market) -> dict[str, Any]:
    """Pre-render market fields for Jinja2 — strings only, no Decimals/UUIDs."""
    if isinstance(market, PolymarketMarket):
        return {
            "question": market.question,
            "resolution_rules": market.resolution_rules,
            "resolution_time": market.resolution_time.isoformat(),
            "outcomes": list(market.outcomes),
            "name": market.name,
        }
    return {
        "question": market.name,
        "resolution_rules": "",
        "resolution_time": "",
        "outcomes": [],
        "name": market.name,
    }


def _book_view(context: StrategistContext) -> dict[str, Any]:
    if context.book is None:
        return {"midpoint": "n/a", "bids": [], "asks": []}
    return {
        "midpoint": str(context.book.midpoint),
        "bids": [[str(p), int(sz)] for p, sz in context.book.bids[:3]],
        "asks": [[str(p), int(sz)] for p, sz in context.book.asks[:3]],
    }


# Surface the callable shape for stricter test mocks if needed.
_CallableClient = Callable[..., Awaitable[Any]]
__all__ = [
    "CHECK_RESULT_JSON_SCHEMA",
    "WEB_SEARCH_TOOL",
    "AnthropicStrategist",
]
