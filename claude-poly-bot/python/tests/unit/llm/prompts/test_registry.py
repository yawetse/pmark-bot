"""Unit tests for the PromptRegistry.

Verifies template loading, splitting, rendering, and (venue, check_type,
sub_agent) dispatch.

Traces: REQ-LLM-010, REQ-BRN-001, REQ-BRN-010.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from claude_poly_bot.domain.models import (
    Book,
    CheckType,
    PolymarketMarket,
    PolymarketScoreFields,
    ScanScore,
    SubAgent,
    VenueName,
)
from claude_poly_bot.llm.prompts import (
    PromptNotFoundError,
    PromptRegistry,
    PromptShapeError,
    default_prompts_dir,
)
from claude_poly_bot.llm.prompts.registry import _classify_stem, _split_blocks


def _scan_score() -> ScanScore:
    return ScanScore(
        market_id="0xabc",
        venue=VenueName.POLYMARKET,
        fields=PolymarketScoreFields(
            gap=Decimal("0.08"),
            depth=Decimal("12000"),
            hours_to_resolution=Decimal("240"),
        ),
        accepted=True,
    )


def _book() -> Book:
    return Book(
        venue=VenueName.POLYMARKET,
        market_id="0xabc",
        bids=[(Decimal("0.4"), 200)],
        asks=[(Decimal("0.42"), 300)],
        midpoint=Decimal("0.41"),
        timestamp=__import__("datetime").datetime(
            2026, 5, 10, 12, 0, tzinfo=__import__("datetime").UTC
        ),
    )


def _render_context() -> dict[str, object]:
    return {
        "market": {
            "question": "Will it rain in NYC by 2026-06-01?",
            "resolution_rules": "Yes if measurable rain occurs at JFK between now and 2026-06-01.",
            "resolution_time": "2026-06-01T00:00:00Z",
            "outcomes": ["YES", "NO"],
            "name": "rain-nyc",
        },
        "book": {"midpoint": "0.41", "bids": [["0.40", 200]], "asks": [["0.42", 300]]},
        "scan_score": {
            "venue": "polymarket",
            "gap": "0.08",
            "depth": "12000",
            "hours_to_resolution": "240",
        },
        "target_wallets_hits": 4,
        "unusual_volume": None,
        "recent_news": [],
        "historical_analogs": [],
        "check_results": [
            {
                "check_type": "base_rate",
                "verdict": "BUY",
                "p_win": "0.62",
                "confidence": "0.8",
                "rationale": "base rate supports YES",
            }
        ],
    }


def test_default_prompts_dir_includes_polymarket_files() -> None:
    pdir = default_prompts_dir()
    assert (pdir / "polymarket" / "base_rate.md").exists()
    assert (pdir / "polymarket" / "news.md").exists()
    assert (pdir / "polymarket" / "whale.md").exists()
    assert (pdir / "polymarket" / "disposition.md").exists()
    assert (pdir / "polymarket" / "arbitrage.md").exists()
    assert (pdir / "polymarket" / "convergence.md").exists()
    assert (pdir / "polymarket" / "whale_copy.md").exists()
    assert (pdir / "shared" / "response_schema.md").exists()


def test_render_polymarket_base_rate_emits_question_and_schema() -> None:
    registry = PromptRegistry(default_prompts_dir())
    system, user = registry.render(
        VenueName.POLYMARKET, CheckType.BASE_RATE, None, _render_context()
    )
    assert "base-rate" in system.lower()
    assert "Response format" in system or "JSON" in system
    assert "Will it rain in NYC by 2026-06-01?" in user


def test_render_polymarket_whale_includes_target_wallet_hits() -> None:
    registry = PromptRegistry(default_prompts_dir())
    _system, user = registry.render(VenueName.POLYMARKET, CheckType.WHALE, None, _render_context())
    assert "Target wallets currently holding" in user
    assert "4" in user


def test_render_sub_agent_uses_subagent_template_with_check_results() -> None:
    """Sub-agent prompts render with `check_results` populated."""
    registry = PromptRegistry(default_prompts_dir())
    system, user = registry.render(
        VenueName.POLYMARKET,
        CheckType.BASE_RATE,  # slot for sub-agent dispatch
        SubAgent.ARBITRAGE,
        _render_context(),
    )
    assert "arbitrage" in system.lower()
    assert "base_rate" in user  # check_results were rendered
    assert "BUY" in user


def test_render_missing_template_raises_prompt_not_found(tmp_path: Path) -> None:
    registry = PromptRegistry(tmp_path)
    with pytest.raises(PromptNotFoundError):
        registry.render(VenueName.POLYMARKET, CheckType.BASE_RATE, None, _render_context())


def test_split_blocks_rejects_missing_markers(tmp_path: Path) -> None:
    fake = tmp_path / "polymarket"
    fake.mkdir()
    bad = fake / "base_rate.md"
    bad.write_text("no markers here", encoding="utf-8")
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "response_schema.md").write_text("schema", encoding="utf-8")
    registry = PromptRegistry(tmp_path)
    with pytest.raises(PromptShapeError):
        registry.render(VenueName.POLYMARKET, CheckType.BASE_RATE, None, {})


def test_split_blocks_requires_system_before_user(tmp_path: Path) -> None:
    text = "<!-- @user -->\nU\n<!-- @system -->\nS\n"
    with pytest.raises(PromptShapeError):
        _split_blocks(text, tmp_path / "bad.md")


def test_classify_stem() -> None:
    assert _classify_stem("base_rate") == (CheckType.BASE_RATE, None)
    assert _classify_stem("arbitrage") == (None, SubAgent.ARBITRAGE)
    assert _classify_stem("unknown") == (None, None)


def test_list_available_enumerates_polymarket_dir() -> None:
    registry = PromptRegistry(default_prompts_dir())
    available = registry.list_available()
    venues = {v for v, _, _ in available}
    assert VenueName.POLYMARKET in venues
    polymarket = {(c, s) for v, c, s in available if v == VenueName.POLYMARKET}
    # The 4 checks (paired with their own CheckType slot)
    assert (CheckType.BASE_RATE, None) in polymarket
    assert (CheckType.NEWS, None) in polymarket
    assert (CheckType.WHALE, None) in polymarket
    assert (CheckType.DISPOSITION, None) in polymarket
    # The 3 Polymarket sub-agents (paired with BASE_RATE slot per registry convention)
    assert (CheckType.BASE_RATE, SubAgent.ARBITRAGE) in polymarket
    assert (CheckType.BASE_RATE, SubAgent.CONVERGENCE) in polymarket
    assert (CheckType.BASE_RATE, SubAgent.WHALE_COPY) in polymarket


def test_caches_compiled_templates_across_calls() -> None:
    """Second render does not re-read disk."""
    registry = PromptRegistry(default_prompts_dir())
    ctx = _render_context()
    s1, u1 = registry.render(VenueName.POLYMARKET, CheckType.BASE_RATE, None, ctx)
    s2, u2 = registry.render(VenueName.POLYMARKET, CheckType.BASE_RATE, None, ctx)
    assert s1 == s2
    assert u1 == u2


# Silence unused-import warnings — these are kept for future expansion of the
# context shape inside the test file.
_ = (PolymarketMarket, _scan_score, _book)
