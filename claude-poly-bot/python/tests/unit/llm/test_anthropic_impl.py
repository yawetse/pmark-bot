"""Unit tests for AnthropicStrategist.

Covers prompt-cache wiring, JSON parsing, malformed-JSON retry, sustained-
error halt, cost estimation, and web-search tool toggling.

Traces: REQ-LLM-001..010, REQ-BRN-005, REQ-BRN-006, REQ-BRN-008,
REQ-BRN-010, REQ-BRN-015.
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
    CheckResult,
    CheckType,
    Geo,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.protocols import Strategist, StrategistContext
from claude_poly_bot.llm.anthropic_impl import (
    CHECK_RESULT_JSON_SCHEMA,
    WEB_SEARCH_TOOL,
    AnthropicStrategist,
    _estimate_cost_usd,
    _extract_json,
    _parse_response,
)
from claude_poly_bot.llm.prompts import PromptRegistry, default_prompts_dir

# ---------------------------------------------------------------------------
# Fake Anthropic client + response shapes
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeServerToolBlock:
    type: str = "server_tool_use"


@dataclass
class _FakeResponse:
    content: list[Any]
    usage: _FakeUsage
    stop_reason: str = "end_turn"


@dataclass
class _FakeMessages:
    scripted: list[_FakeResponse | Exception] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        next_response = self.scripted.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


@dataclass
class _FakeClient:
    messages: _FakeMessages


# ---------------------------------------------------------------------------
# Test data fixtures
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


def _ok_response(rationale: str = "rationale") -> _FakeResponse:
    payload = (
        "```json\n"
        '{"verdict": "BUY", "confidence": 0.85, "p_win": 0.62, '
        f'"rationale": "{rationale}"}}\n'
        "```"
    )
    return _FakeResponse(
        content=[_FakeTextBlock(text=payload)],
        usage=_FakeUsage(input_tokens=1200, output_tokens=120, cache_creation_input_tokens=800),
    )


def _build(
    messages: _FakeMessages, *, threshold: int = 5
) -> tuple[AnthropicStrategist, _FakeClient]:
    client = _FakeClient(messages=messages)
    strategist = AnthropicStrategist(
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
    strategist, _ = _build(_FakeMessages(scripted=[]))
    assert isinstance(strategist, Strategist)
    assert strategist.bot == Bot.CLAUDE


# ---------------------------------------------------------------------------
# Happy-path: prompt caching + JSON output config + parsed CheckResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_emits_prompt_cache_marker_and_json_schema() -> None:
    strategist, client = _build(_FakeMessages(scripted=[_ok_response()]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )

    assert len(client.messages.calls) == 1
    call = client.messages.calls[0]

    # REQ-BRN-010: prompt cache on system block.
    assert isinstance(call["system"], list)
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "base-rate analyst" in call["system"][0]["text"].lower()

    # REQ-BRN-006: JSON schema in output_config.format.
    assert call["output_config"]["format"]["schema"] == CHECK_RESULT_JSON_SCHEMA
    assert call["output_config"]["format"]["type"] == "json_schema"

    # Default-disabled web search.
    assert "tools" not in call

    # Parsed result populated.
    assert result.verdict == Verdict.BUY
    assert result.confidence == Decimal("0.85")
    assert result.p_win == Decimal("0.62")
    assert result.model_id == "claude-opus-4-7"
    assert result.tokens_in == 1200
    assert result.tokens_out == 120
    assert result.tokens_cached == 800  # cache_creation + cache_read
    assert result.cost_usd > Decimal("0")


@pytest.mark.asyncio
async def test_web_search_true_includes_tool_in_request() -> None:
    strategist, client = _build(_FakeMessages(scripted=[_ok_response()]))
    await strategist.evaluate(
        CheckType.NEWS,
        VenueName.POLYMARKET,
        _market(),
        _context(),
        web_search=True,
    )
    call = client.messages.calls[0]
    assert call["tools"] == [WEB_SEARCH_TOOL]


@pytest.mark.asyncio
async def test_web_search_used_flag_detected_from_response() -> None:
    response = _FakeResponse(
        content=[
            _FakeServerToolBlock(),
            _FakeTextBlock(
                text='```json\n{"verdict":"SKIP","confidence":0.1,"p_win":0.5,'
                '"rationale":"no edge"}\n```'
            ),
        ],
        usage=_FakeUsage(input_tokens=500, output_tokens=80),
    )
    strategist, _ = _build(_FakeMessages(scripted=[response]))
    result = await strategist.evaluate(
        CheckType.NEWS, VenueName.POLYMARKET, _market(), _context(), web_search=True
    )
    assert result.web_search_used is True


@pytest.mark.asyncio
async def test_sub_agent_evaluate_renders_with_check_results() -> None:
    """Sub-agent prompts get prior check results in the render context."""
    prior = [
        CheckResult(
            bot=Bot.CLAUDE,
            venue=VenueName.POLYMARKET,
            market_id="0xabc",
            check_type=CheckType.BASE_RATE,
            verdict=Verdict.BUY,
            confidence=Decimal("0.8"),
            p_win=Decimal("0.62"),
            rationale="base rate strong",
            model_id="claude-opus-4-7",
            correlation_id=__import__("uuid").uuid4(),
        )
    ]
    context = _context().model_copy(update={"prior_check_results": prior})
    strategist, client = _build(_FakeMessages(scripted=[_ok_response()]))
    await strategist.evaluate(
        CheckType.BASE_RATE,
        VenueName.POLYMARKET,
        _market(),
        context,
        sub_agent=SubAgent.ARBITRAGE,
    )
    user_text = client.messages.calls[0]["messages"][0]["content"]
    assert "base_rate" in user_text
    assert "base rate strong" in user_text


# ---------------------------------------------------------------------------
# REQ-BRN-008: malformed JSON retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_retries_then_succeeds() -> None:
    bad = _FakeResponse(
        content=[_FakeTextBlock(text="not json at all")],
        usage=_FakeUsage(input_tokens=100, output_tokens=10),
    )
    strategist, client = _build(_FakeMessages(scripted=[bad, _ok_response()]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )
    assert result.verdict == Verdict.BUY
    # Two API calls: first bad, second good.
    assert len(client.messages.calls) == 2
    # Retry message carries the assistant reply + a corrective user prompt.
    retry_messages = client.messages.calls[1]["messages"]
    assert len(retry_messages) == 3
    assert retry_messages[1]["role"] == "assistant"
    assert "did not match" in retry_messages[2]["content"]


@pytest.mark.asyncio
async def test_malformed_json_exhausts_retries_returns_skip_with_error() -> None:
    bad = _FakeResponse(
        content=[_FakeTextBlock(text="still not json")],
        usage=_FakeUsage(input_tokens=50, output_tokens=10),
    )
    strategist, client = _build(_FakeMessages(scripted=[bad, bad, bad]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )
    assert result.verdict == Verdict.SKIP
    assert result.error is not None
    assert "malformed_response_after_retries" in result.error
    assert len(client.messages.calls) == 3  # 1 initial + 2 retries
    # Counter bumped exactly once for the failed call.
    assert await strategist.consecutive_error_count() == 1


@pytest.mark.asyncio
async def test_verdict_out_of_enum_triggers_retry() -> None:
    bad = _FakeResponse(
        content=[
            _FakeTextBlock(
                text='```json\n{"verdict":"MAYBE","confidence":0.5,"p_win":0.5,'
                '"rationale":"???"}\n```'
            )
        ],
        usage=_FakeUsage(input_tokens=80, output_tokens=20),
    )
    strategist, client = _build(_FakeMessages(scripted=[bad, _ok_response()]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )
    assert result.verdict == Verdict.BUY
    assert len(client.messages.calls) == 2


# ---------------------------------------------------------------------------
# REQ-BRN-015: sustained-error halt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_error_returns_skip_and_bumps_counter() -> None:
    strategist, _ = _build(_FakeMessages(scripted=[RuntimeError("boom")]))
    result = await strategist.evaluate(
        CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
    )
    assert result.verdict == Verdict.SKIP
    assert result.error is not None and "RuntimeError" in result.error
    assert await strategist.consecutive_error_count() == 1


@pytest.mark.asyncio
async def test_five_consecutive_errors_then_halt_raises() -> None:
    errs: list[_FakeResponse | Exception] = [RuntimeError("e") for _ in range(5)]
    strategist, _ = _build(_FakeMessages(scripted=errs), threshold=5)
    for _ in range(5):
        result = await strategist.evaluate(
            CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context()
        )
        assert result.verdict == Verdict.SKIP
    assert await strategist.consecutive_error_count() == 5
    # Sixth call refuses to even hit the API.
    with pytest.raises(LLMSustainedErrorsError):
        await strategist.evaluate(CheckType.BASE_RATE, VenueName.POLYMARKET, _market(), _context())


@pytest.mark.asyncio
async def test_success_resets_consecutive_error_counter() -> None:
    strategist, _ = _build(
        _FakeMessages(scripted=[RuntimeError("e"), RuntimeError("e"), _ok_response()])
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


def test_parse_response_rejects_p_win_out_of_range() -> None:
    response = _FakeResponse(
        content=[
            _FakeTextBlock(
                text='```json\n{"verdict":"BUY","confidence":0.8,"p_win":1.5,"rationale":"x"}\n```'
            )
        ],
        usage=_FakeUsage(),
    )
    with pytest.raises(Exception, match="p_win out of"):
        _parse_response(response)


def test_estimate_cost_usd_for_opus_4_7() -> None:
    usage = _FakeUsage(
        input_tokens=1000,
        output_tokens=500,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=4000,
    )
    cost = _estimate_cost_usd("claude-opus-4-7", usage)
    # Hand-computed: 1000*5e-6 + 500*25e-6 + 4000*5e-6*0.1 + 200*5e-6*1.25
    # = 0.005 + 0.0125 + 0.002 + 0.00125 = 0.02075
    assert cost == Decimal("0.02075000")


def test_estimate_cost_usd_handles_zero_usage() -> None:
    assert _estimate_cost_usd("claude-opus-4-7", None) == Decimal("0")
    assert _estimate_cost_usd("claude-opus-4-7", _FakeUsage()) == Decimal("0E-8")
