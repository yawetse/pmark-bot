"""OpenAIStrategist -- GPT-backed Strategist implementation.

Uses the OpenAI Responses API through a narrow, testable client protocol.
The adapter renders the same prompt templates as AnthropicStrategist, requests
structured JSON output, optionally enables OpenAI web search, parses the
response into CheckResult, and persists the call through the decision repo.

Traces: REQ-LLM-001..010, REQ-BRN-005, REQ-BRN-006, REQ-BRN-008,
REQ-BRN-014, REQ-BRN-015.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
from claude_poly_bot.llm.anthropic_impl import CHECK_RESULT_JSON_SCHEMA
from claude_poly_bot.llm.prompts import PromptRegistry

logger = logging.getLogger(__name__)

# REQ: REQ-BRN-005 - OpenAI built-in web search tool.
OPENAI_WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search",
    "search_context_size": "medium",
}

CHECK_RESULT_TEXT_FORMAT: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "CheckResult",
        "schema": CHECK_RESULT_JSON_SCHEMA,
        "strict": True,
    }
}

# Prices are USD/token for standard processing. GPT-5.5 and GPT-5.4 rates are
# from OpenAI's API pricing page as of 2026-06-20. The plain gpt-5 default keeps
# the original project baseline rate.
_GPT5_INPUT = Decimal("1.25") / Decimal("1000000")
_GPT5_CACHED_INPUT = Decimal("0.125") / Decimal("1000000")
_GPT5_OUTPUT = Decimal("10.0") / Decimal("1000000")
_GPT54_INPUT = Decimal("2.5") / Decimal("1000000")
_GPT54_CACHED_INPUT = Decimal("0.25") / Decimal("1000000")
_GPT54_OUTPUT = Decimal("15.0") / Decimal("1000000")
_GPT54_MINI_INPUT = Decimal("0.75") / Decimal("1000000")
_GPT54_MINI_CACHED_INPUT = Decimal("0.075") / Decimal("1000000")
_GPT54_MINI_OUTPUT = Decimal("4.5") / Decimal("1000000")
_GPT55_INPUT = Decimal("5.0") / Decimal("1000000")
_GPT55_CACHED_INPUT = Decimal("0.5") / Decimal("1000000")
_GPT55_OUTPUT = Decimal("30.0") / Decimal("1000000")


class _ResponsesClient(Protocol):
    """The subset of openai.AsyncOpenAI.responses this adapter depends on."""

    async def create(self, **kwargs: Any) -> Any: ...


class _OpenAIClient(Protocol):
    responses: _ResponsesClient


class _DecisionRecorder(Protocol):
    """Subset of DecisionRepo used by the strategist."""

    async def record(self, result: CheckResult) -> Any: ...


@dataclass(frozen=True)
class _ModelPricing:
    input_per_token: Decimal
    cached_input_per_token: Decimal
    output_per_token: Decimal


class OpenAIStrategist:
    """OpenAI-backed strategist. Keep one instance per bot process so the
    consecutive-error counter reflects the bot's current provider health.
    """

    bot: Bot

    def __init__(
        self,
        *,
        client: _OpenAIClient,
        prompts: PromptRegistry,
        clock: Clock,
        decision_repo: _DecisionRecorder | None = None,
        bot: Bot = Bot.OPENAI,
        default_model: str = "gpt-5",
        max_retries_malformed: int = 2,
        consecutive_error_threshold: int = 5,
        max_output_tokens: int = 4096,
    ) -> None:
        self.bot = bot
        self._client = client
        self._prompts = prompts
        self._clock = clock
        self._decision_repo = decision_repo
        self._default_model = default_model
        self._max_retries_malformed = max_retries_malformed
        self._consecutive_error_threshold = consecutive_error_threshold
        self._max_output_tokens = max_output_tokens
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
        if self._consecutive_errors >= self._consecutive_error_threshold:
            raise LLMSustainedErrorsError(
                f"halt active: {self._consecutive_errors} consecutive failures"
            )

        effective_model = model_id or self._default_model
        correlation_id = uuid4()
        system_prompt, user_prompt = self._render(check_type, venue, market, context, sub_agent)

        last_error: str | None = None
        input_messages: list[dict[str, str]] = [
            {"role": "user", "content": user_prompt},
        ]

        for attempt in range(self._max_retries_malformed + 1):
            started = self._clock.now()
            try:
                response = await self._call_openai(
                    model=effective_model,
                    system_prompt=system_prompt,
                    input_messages=input_messages,
                    web_search=web_search,
                )
            except LLMSustainedErrorsError:
                raise
            except Exception as e:
                await self._bump_error()
                logger.warning(
                    "openai_strategist_call_failed",
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
                    "openai_strategist_malformed",
                    extra={
                        "attempt": attempt,
                        "venue": venue.value,
                        "check_type": check_type.value,
                        "error": last_error,
                    },
                )
                assistant_text = _first_output_text(response) or ""
                input_messages = [
                    *input_messages,
                    {"role": "assistant", "content": assistant_text},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response did not match the required JSON schema: "
                            f"{last_error}. Re-emit the answer as a single JSON object inside "
                            f"a ```json fence, matching the schema exactly."
                        ),
                    },
                ]
                continue

            await self._reset_errors()
            usage = getattr(response, "usage", None)
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
                tokens_cached=_cached_input_tokens(usage),
                cost_usd=_estimate_cost_usd(effective_model, usage),
                latency_ms=elapsed_ms,
                web_search_used=_used_web_search(response),
                correlation_id=correlation_id,
                raw_response=parsed.raw,
            )
            return await self._record_and_return(result)

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

    def _render(
        self,
        check_type: CheckType,
        venue: VenueName,
        market: Market,
        context: StrategistContext,
        sub_agent: SubAgent | None,
    ) -> tuple[str, str]:
        render_ctx: dict[str, object] = {
            "market": _market_view(market),
            "book": _book_view(context),
            "scan_score": context.scan_score.fields.model_dump(mode="json"),
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

    async def _call_openai(
        self,
        *,
        model: str,
        system_prompt: str,
        input_messages: list[dict[str, str]],
        web_search: bool,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": system_prompt,
            "input": input_messages,
            "max_output_tokens": self._max_output_tokens,
            "text": CHECK_RESULT_TEXT_FORMAT,
            "temperature": 0.0,
            "store": False,
        }
        if web_search:
            kwargs["tools"] = [OPENAI_WEB_SEARCH_TOOL]
            kwargs["tool_choice"] = "auto"
            kwargs["include"] = ["web_search_call.action.sources"]
        return await self._client.responses.create(**kwargs)

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
            except Exception as e:
                logger.warning(
                    "openai_strategist_record_failed",
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


@dataclass
class _Parsed:
    verdict: Verdict
    confidence: Probability
    p_win: Probability
    rationale: str
    raw: dict[str, Any]


def _parse_response(response: Any) -> _Parsed:
    text = _first_output_text(response)
    if not text:
        raise MalformedResponseError("no output_text in response")
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


def _first_output_text(response: Any) -> str | None:
    output_text = _get_value(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output = _get_value(response, "output") or []
    chunks: list[str] = []
    for item in output:
        item_type = _get_value(item, "type")
        if item_type == "message":
            for part in _get_value(item, "content") or []:
                part_type = _get_value(part, "type")
                if part_type in ("output_text", "text"):
                    text = _get_value(part, "text")
                    if isinstance(text, str):
                        chunks.append(text)
        elif item_type in ("output_text", "text"):
            text = _get_value(item, "text")
            if isinstance(text, str):
                chunks.append(text)
    if not chunks:
        return None
    return "\n".join(chunks)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
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
    output = _get_value(response, "output") or []
    for item in output:
        if _get_value(item, "type") == "web_search_call":
            return True
    return False


def _get_value(obj: Any, attr: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr)
    return getattr(obj, attr, None)


def _get_int(obj: Any, attr: str) -> int:
    val = _get_value(obj, attr)
    return int(val or 0)


def _cached_input_tokens(usage: Any) -> int:
    details = _get_value(usage, "input_tokens_details")
    return _get_int(details, "cached_tokens")


def _pricing(model_id: str) -> _ModelPricing:
    if model_id.startswith("gpt-5.5"):
        return _ModelPricing(_GPT55_INPUT, _GPT55_CACHED_INPUT, _GPT55_OUTPUT)
    if model_id.startswith("gpt-5.4-mini"):
        return _ModelPricing(_GPT54_MINI_INPUT, _GPT54_MINI_CACHED_INPUT, _GPT54_MINI_OUTPUT)
    if model_id.startswith("gpt-5.4"):
        return _ModelPricing(_GPT54_INPUT, _GPT54_CACHED_INPUT, _GPT54_OUTPUT)
    return _ModelPricing(_GPT5_INPUT, _GPT5_CACHED_INPUT, _GPT5_OUTPUT)


def _estimate_cost_usd(model_id: str, usage: Any) -> Decimal:
    if usage is None:
        return Decimal("0")
    p = _pricing(model_id)
    tokens_in = Decimal(_get_int(usage, "input_tokens"))
    cached = Decimal(_cached_input_tokens(usage))
    billable_input = max(tokens_in - cached, Decimal("0"))
    tokens_out = Decimal(_get_int(usage, "output_tokens"))
    cost = (
        billable_input * p.input_per_token
        + cached * p.cached_input_per_token
        + tokens_out * p.output_per_token
    )
    return cost.quantize(Decimal("0.00000001"))


def _market_view(market: Market) -> dict[str, Any]:
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


__all__ = [
    "CHECK_RESULT_TEXT_FORMAT",
    "OPENAI_WEB_SEARCH_TOOL",
    "OpenAIStrategist",
]
