"""FakeStrategist — scripted Strategist for tests and local DRY_RUN demos.

Tests queue scripted CheckResult shapes per (check_type, sub_agent, venue,
market_id) and `evaluate` pops in FIFO order. Designed for deterministic
integration tests of the thesis loop.

Traces: REQ-LLM-009.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from claude_poly_bot.domain.clock import Clock
from claude_poly_bot.domain.models import (
    Bot,
    CheckResult,
    CheckType,
    Market,
    Probability,
    SubAgent,
    VenueName,
    Verdict,
)
from claude_poly_bot.domain.protocols import StrategistContext


@dataclass
class _Scripted:
    verdict: Verdict
    confidence: Probability
    p_win: Probability
    rationale: str
    delay_ms: int = 0
    raise_error: BaseException | None = None


_Key = tuple[CheckType, VenueName, SubAgent | None, str | None]


class FakeStrategist:
    """In-memory strategist. Tests `queue_response(...)` before calling
    `evaluate(...)`. `evaluate` consumes the queue in FIFO order matching
    the most specific key first (with `market_id`), then the wildcard key.
    """

    bot: Bot

    def __init__(self, bot: Bot, *, clock: Clock, model_id: str = "fake-model") -> None:
        self.bot = bot
        self._clock = clock
        self._model_id = model_id
        self._queues: dict[_Key, deque[_Scripted]] = {}
        self._consecutive_errors = 0

    # REQ: REQ-LLM-009 - scripted response queueing for tests.
    def queue_response(
        self,
        check_type: CheckType,
        venue: VenueName,
        verdict: Verdict,
        confidence: Probability,
        p_win: Probability,
        *,
        rationale: str = "fake",
        sub_agent: SubAgent | None = None,
        market_id: str | None = None,
        delay_ms: int = 0,
        raise_error: BaseException | None = None,
    ) -> None:
        key: _Key = (check_type, venue, sub_agent, market_id)
        self._queues.setdefault(key, deque()).append(
            _Scripted(
                verdict=verdict,
                confidence=confidence,
                p_win=p_win,
                rationale=rationale,
                delay_ms=delay_ms,
                raise_error=raise_error,
            )
        )

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
        del context, web_search  # unused; preserved for protocol parity
        scripted = self._pop(check_type, venue, sub_agent, market.external_id)

        if scripted is None:
            # No script — return a default SKIP so tests that forget to
            # queue don't crash, but the wrong path is observable via the
            # rationale and SKIP verdict.
            return CheckResult(
                bot=self.bot,
                venue=venue,
                market_id=market.external_id,
                check_type=check_type,
                sub_agent=sub_agent,
                verdict=Verdict.SKIP,
                confidence=Decimal("0"),
                p_win=Decimal("0.5"),
                rationale="fake_no_script",
                model_id=model_id or self._model_id,
                correlation_id=uuid4(),
            )

        if scripted.delay_ms > 0:
            await asyncio.sleep(scripted.delay_ms / 1000)

        if scripted.raise_error is not None:
            self._consecutive_errors += 1
            raise scripted.raise_error

        self._consecutive_errors = 0
        return CheckResult(
            bot=self.bot,
            venue=venue,
            market_id=market.external_id,
            check_type=check_type,
            sub_agent=sub_agent,
            verdict=scripted.verdict,
            confidence=scripted.confidence,
            p_win=scripted.p_win,
            rationale=scripted.rationale,
            model_id=model_id or self._model_id,
            correlation_id=uuid4(),
        )

    async def consecutive_error_count(self) -> int:
        return self._consecutive_errors

    # ---- internals ----

    def _pop(
        self,
        check_type: CheckType,
        venue: VenueName,
        sub_agent: SubAgent | None,
        market_id: str,
    ) -> _Scripted | None:
        specific: _Key = (check_type, venue, sub_agent, market_id)
        wildcard: _Key = (check_type, venue, sub_agent, None)
        for key in (specific, wildcard):
            q = self._queues.get(key)
            if q:
                return q.popleft()
        return None
