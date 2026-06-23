"""Unit tests for OpenAIStrategist.

Covers Responses API request shape, structured JSON output, malformed-JSON
retry, sustained-error halt, provider parity, cost estimation, and web-search
tool toggling.

Traces: REQ-LLM-001..010, REQ-BRN-005, REQ-BRN-006, REQ-BRN-008,
REQ-BRN-014, REQ-BRN-015.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from claude_poly_bot.domain.clock import FakeClock
from claude_poly_bot.domain.exceptions import LLMSustainedErrorsError
from claude_poly_bot.domain.models import (
    Book,
    Bot,
    CheckType,
    Geo,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.protocols import Strategist, StrategistContext
from claude_poly_bot.llm import OpenAIStrategist as ExportedOpenAIStrategist
from claude_poly_bot.llm.anthropic_impl import (
    CHECK_RESULT_JSON_SCHEMA,
    AnthropicStrategist,
)
from claude_poly_bot.llm.anthropic_impl import (
    WEB_SEARCH_TOOL as ANTHROPIC_WEB_SEARCH_TOOL,
)
from claude_poly_bot.llm.openai_impl import (
    CHECK_RESULT_TEXT_FORMAT,
    OPENAI_WEB_SEARCH_TOOL,
    OpenAIStrategist,
    _estimate_cost_usd,
    _extract_json,
    _parse_response,
)
from claude_poly_bot.llm.prompts import PromptRegistry, default_prompts_dir

# ---------------------------------------------------------------------------
# Fake OpenAI client + response shapes
# ---------------------------------------------------------------------------


@dataclass
class _FakeInputTokenDetails:
    cached_tokens: int = 0


@dataclass
class _FakeOpenAIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    input_tokens_details: _FakeInputTokenDetails = field(
        default_factory=_FakeInputTokenDetails
    )


@dataclass
class _FakeOutputText:
    text: str
    type: str = "output_text"


@dataclass
class _FakeMessage:
    content: list[Any]
    type: str = "message"


@dataclass
class _FakeWebSearchCall:
    type: str = "web_search_call"


@dataclass
class _FakeOpenAIResponse:
    output: list[Any]
    usage: _FakeOpenAIUsage
    output_text: str | None = None


@dataclass
class _FakeResponses:
    scripted: list[_FakeOpenAIResponse | Exception] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        next_response = self.scripted.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


@dataclass
class _FakeOpenAIClient:
    responses: _FakeResponses


# ---------------------------------------------------------------------------
# Fake Anthropic client for parity assertions
# ---------------------------------------------------------------------------


@dataclass
class _FakeAnthropicUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _FakeAnthropicTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeAnthropicResponse:
    content: list[Any]
    usage: _FakeAnthropicUsage


@dataclass
class _FakeAnthropicMessages:
    scripted: list[_FakeAnthropicResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.scripted.pop(0)


@dataclass
class _FakeAnthropicClient:
    messages: _FakeAnthropicMessages


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def _market() -> PolymarketMarket:
    return PolymarketMarket(
        external_id="0xabc",
        name="rain-nyc",
        geo=Geo.US,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        question="Will it rain in NYC by 2026-06-01?",
        resolution_rules="Yes if measurable rain at JFK",
        resolution_time=datetime(2026, 6, 1, tzinfo=UTC),
        outcomes=["YES", "NO"],
        token_ids={"YES": "0x1", "NO": "0x2"},
    )


def _context() -> StrategistContext:
    return StrategistContext(
        book=Book(
            venue=VenueName.POLYMARKET,
            market_id="0xabc",
            bids=[(Decimal("0.4"), 100)],
            asks=[(Decimal("0.42"), 100)],
            midpoint=Decimal("0.41"),
            timestamp=datetime(2026, 5, 10, tzinfo=UTC),
        ),
        scan_score=ScanScore(
            market_id="0xabc",
            venue=VenueName.POLYMARKET,
            fields=PolymarketScoreFields(
                gap=Decimal("0.08"),
                depth=Decimal("12000"),
                hours_to_resolution=Decimal("240"),
            ),
            accepted=True,
        ),
        target_wallets_hits=4,
    )


def _payload(rationale: str = "rationale") -> str:
    return (
        "```json\n"
        '{"verdict": "BUY", "confidence": 0.85, "p_win": 0.62, '
        f'"rationale": "{rationale}"}}\n'
        "```"
    )


def _ok_response(rationale: str = "rationale") -> _FakeOpenAIResponse:
    return _FakeOpenAIResponse(
        output=[_FakeMessage(content=[_FakeOutputText(text=_payload(rationale))])],
        usage=_FakeOpenAIUsage(
            input_tokens=1200,
            output_tokens=120,
            input_tokens_details=_FakeInputTokenDetails(cached_tokens=200),
        ),
    )


def _anthropic_ok_response() -> _FakeAnthropicResponse:
    return _FakeAnthropicResponse(
        content=[_FakeAnthropicTextBlock(text=_payload())],
        usage=_FakeAnthropicUsage(input_tokens=1200, output_tokens=120),
    )


def _build(
    responses: _FakeResponses, *, threshold: int = 5
) -> tuple[OpenAIStrategist, _FakeOpenAIClient]:
    client = _FakeOpenAIClient(responses=responses)
    strategist = OpenAIStrategist(
        client=client,  # type: ignore[arg-type]
        prompts=PromptRegistry(default_prompts_dir()),
        clock=FakeClock(datetime(2026, 5, 10, tzinfo=UTC)),
        consecutive_error_threshold=threshold,
    )
    return strategist, client


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


def test_satisfies_strategist_protocol() -> None:
    strategist, _ = _build(_FakeResponses(scripted=[]))
    assert isinstance(strategist, Strategist)
    assert strategist.bot == Bot.OPENAI
    assert ExportedOpenAIStrategist is OpenAIStrategist


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_emits_responses_structured_output_request() -> None:
    strategist, client = _build(_FakeResponses(scripted=[_ok_response()]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )

    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]

    assert call["model"] == "gpt-5"
    assert "base-rate analyst" in call["instructions"].lower()
    assert "Will it rain in NYC by 2026-06-01?" in call["input"][0]["content"]
    assert call["temperature"] == 0.0
    assert call["store"] is False

    assert call["text"] == CHECK_RESULT_TEXT_FORMAT
    assert call["text"]["format"]["schema"] == CHECK_RESULT_JSON_SCHEMA
    assert call["text"]["format"]["strict"] is True
    assert "tools" not in call

    assert result.verdict == Verdict.BUY
    assert result.confidence == Decimal("0.85")
    assert result.p_win == Decimal("0.62")
    assert result.model_id == "gpt-5"
    assert result.tokens_in == 1200
    assert result.tokens_out == 120
    assert result.tokens_cached == 200
    assert result.cost_usd > Decimal("0")


@pytest.mark.asyncio
async def test_web_search_true_includes_tool_in_request() -> None:
    strategist, client = _build(_FakeResponses(scripted=[_ok_response()]))
    await strategist.evaluate(
        CheckType.NEWS,
        VenueName.POLYMARKET,
        _market(),
        _context(),
        web_search=True,
    )
    call = client.responses.calls[0]
    assert call["tools"] == [OPENAI_WEB_SEARCH_TOOL]
    assert call["tool_choice"] == "auto"
    assert call["include"] == ["web_search_call.action.sources"]


@pytest.mark.asyncio
async def test_web_search_used_flag_detected_from_response() -> None:
    response = _FakeOpenAIResponse(
        output=[
            _FakeWebSearchCall(),
            _FakeMessage(
                content=[
                    _FakeOutputText(
                        text='```json\n{"verdict":"SKIP","confidence":0.1,'
                        '"p_win":0.5,"rationale":"no edge"}\n```'
                    )
                ]
            ),
        ],
        usage=_FakeOpenAIUsage(input_tokens=500, output_tokens=80),
    )
    strategist, _ = _build(_FakeResponses(scripted=[response]))
    result = await strategist.evaluate(
        CheckType.NEWS, VenueName.POLYMARKET, _market(), _context(), web_search=True
    )
    assert result.web_search_used is True


@pytest.mark.asyncio
async def test_provider_parity_uses_same_prompts_temperature_and_schema() -> None:
    clock = FakeClock(datetime(2026, 5, 10, tzinfo=UTC))
    prompts = PromptRegistry(default_prompts_dir())

    anthropic_messages = _FakeAnthropicMessages(scripted=[_anthropic_ok_response()])
    anthropic = AnthropicStrategist(
        client=_FakeAnthropicClient(messages=anthropic_messages),  # type: ignore[arg-type]
        prompts=prompts,
        clock=clock,
    )

    openai_responses = _FakeResponses(scripted=[_ok_response()])
    openai = OpenAIStrategist(
        client=_FakeOpenAIClient(responses=openai_responses),  # type: ignore[arg-type]
        prompts=prompts,
        clock=clock,
    )

    await anthropic.evaluate(
        CheckType.NEWS, VenueName.POLYMARKET, _market(), _context(), web_search=True
    )
    await openai.evaluate(
        CheckType.NEWS, VenueName.POLYMARKET, _market(), _context(), web_search=True
    )

    anthropic_call = anthropic_messages.calls[0]
    openai_call = openai_responses.calls[0]

    assert anthropic_call["system"][0]["text"] == openai_call["instructions"]
    assert anthropic_call["messages"][0]["content"] == openai_call["input"][0]["content"]
    assert anthropic_call["temperature"] == openai_call["temperature"] == 0.0
    assert anthropic_call["output_config"]["format"]["schema"] == CHECK_RESULT_JSON_SCHEMA
    assert openai_call["text"]["format"]["schema"] == CHECK_RESULT_JSON_SCHEMA
    assert anthropic_call["tools"] == [ANTHROPIC_WEB_SEARCH_TOOL]
    assert openai_call["tools"] == [OPENAI_WEB_SEARCH_TOOL]


# ---------------------------------------------------------------------------
# Malformed JSON retry and sustained-error halt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_retries_then_succeeds() -> None:
    bad = _FakeOpenAIResponse(
        output=[_FakeMessage(content=[_FakeOutputText(text="not json at all")])],
        usage=_FakeOpenAIUsage(input_tokens=100, output_tokens=10),
    )
    strategist, client = _build(_FakeResponses(scripted=[bad, _ok_response()]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )

    assert result.verdict == Verdict.BUY
    assert len(client.responses.calls) == 2
    retry_input = client.responses.calls[1]["input"]
    assert len(retry_input) == 3
    assert retry_input[1]["role"] == "assistant"
    assert "did not match" in retry_input[2]["content"]


@pytest.mark.asyncio
async def test_malformed_json_exhausts_retries_returns_skip_with_error() -> None:
    bad = _FakeOpenAIResponse(
        output=[_FakeMessage(content=[_FakeOutputText(text="still not json")])],
        usage=_FakeOpenAIUsage(input_tokens=50, output_tokens=10),
    )
    strategist, client = _build(_FakeResponses(scripted=[bad, bad, bad]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )

    assert result.verdict == Verdict.SKIP
    assert result.error is not None
    assert "malformed_response_after_retries" in result.error
    assert len(client.responses.calls) == 3
    assert await strategist.consecutive_error_count() == 1


@pytest.mark.asyncio
async def test_api_error_returns_skip_and_bumps_counter() -> None:
    strategist, _ = _build(_FakeResponses(scripted=[RuntimeError("boom")]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )

    assert result.verdict == Verdict.SKIP
    assert result.error is not None and "RuntimeError" in result.error
    assert await strategist.consecutive_error_count() == 1


@pytest.mark.asyncio
async def test_five_consecutive_errors_then_halt_raises() -> None:
    strategist, _ = _build(_FakeResponses(scripted=[RuntimeError("e") for _ in range(5)]))
    for _ in range(5):
        result = await strategist.evaluate(
            CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
        )
        assert result.verdict == Verdict.SKIP

    with pytest.raises(LLMSustainedErrorsError):
        await strategist.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())


@pytest.mark.asyncio
async def test_success_resets_consecutive_error_counter() -> None:
    strategist, _ = _build(
        _FakeResponses(scripted=[RuntimeError("e"), RuntimeError("e"), _ok_response()])
    )
    await strategist.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    await strategist.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert await strategist.consecutive_error_count() == 2
    await strategist.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())
    assert await strategist.consecutive_error_count() == 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_extract_json_bare_object() -> None:
    payload = _extract_json('{"verdict":"BUY","confidence":0.5,"p_win":0.5,"rationale":"x"}')
    assert payload["verdict"] == "BUY"


def test_extract_json_fenced_block() -> None:
    payload = _extract_json(
        '```json\n{"verdict":"BUY","confidence":0.5,"p_win":0.5,"rationale":"x"}\n```'
    )
    assert payload["verdict"] == "BUY"


def test_parse_response_rejects_confidence_out_of_range() -> None:
    response = _FakeOpenAIResponse(
        output=[
            _FakeMessage(
                content=[
                    _FakeOutputText(
                        text='```json\n{"verdict":"BUY","confidence":1.2,'
                        '"p_win":0.5,"rationale":"x"}\n```'
                    )
                ]
            )
        ],
        usage=_FakeOpenAIUsage(),
    )
    with pytest.raises(Exception, match="confidence out of"):
        _parse_response(response)


def test_estimate_cost_usd_for_gpt_5_5() -> None:
    usage = _FakeOpenAIUsage(
        input_tokens=1000,
        output_tokens=500,
        input_tokens_details=_FakeInputTokenDetails(cached_tokens=100),
    )
    cost = _estimate_cost_usd("gpt-5.5", usage)
    # 900*5e-6 + 100*0.5e-6 + 500*30e-6 = 0.01955
    assert cost == Decimal("0.01955000")


def test_estimate_cost_usd_handles_zero_usage() -> None:
    assert _estimate_cost_usd("gpt-5", None) == Decimal("0")
    assert _estimate_cost_usd("gpt-5", _FakeOpenAIUsage()) == Decimal("0E-8")
