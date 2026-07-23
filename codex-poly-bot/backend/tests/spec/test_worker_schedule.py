"""Scheduler configuration tests."""

from app.main import _configured_worker_interval, _worker_sleep_delay
from app.services.config_service import default_config_payload, trading_profile_patches


def test_active_stock_day_trader_is_safe_bootstrap_profile() -> None:
    payload = default_config_payload()

    assert payload["trading_profile"] == "active_stock_day_trader"
    assert payload["default_selected_venue"] == "alpaca"
    assert payload["venues"]["alpaca"]["enabled"] is True
    assert payload["live_enabled"] is False
    assert payload["alpaca"]["account_mode"] == "paper"
    assert payload["trading_loop_interval_seconds"] == 60
    assert payload["scanner"]["alpaca"]["min_quote_liquidity"] == "0.5"
    assert payload["scanner"]["alpaca"]["max_spread"] == "1.00"
    assert payload["reasoning"]["max_prompts_per_provider_per_run"] == 4
    assert payload["reasoning"]["alpaca"]["min_confidence"] == "0.54"
    assert payload["reasoning"]["alpaca"]["min_edge"] == "0.015"
    assert payload["exit"]["alpaca"]["profit_target_pct"] == "0.02"
    assert payload["exit"]["alpaca"]["stop_loss_pct"] == "0.01"
    assert payload["exit"]["alpaca"]["close_before_market_close_minutes"] == 15
    assert payload["llm"]["openai"]["settings"]["budget_window_hours"] == 24


def test_active_stock_profile_preserves_live_gate_and_account_mode() -> None:
    patches = trading_profile_patches("active_stock_day_trader")
    values = {patch.path: patch.value for patch in patches}

    assert values["trading_profile"] == "active_stock_day_trader"
    assert values["default_selected_venue"] == "alpaca"
    assert values["exit.alpaca.close_before_market_close_minutes"] == 15
    assert values["scanner.alpaca.strategies.unusual_volume.min_ratio"] == "1.25"
    assert "live_enabled" not in values
    assert "alpaca.account_mode" not in values


def test_trading_loop_uses_saved_interval() -> None:
    assert _configured_worker_interval(
        {"trading_loop_interval_seconds": 15},
        fallback=60,
    ) == 15


def test_trading_loop_rejects_interval_below_safe_minimum() -> None:
    assert _configured_worker_interval(
        {"trading_loop_interval_seconds": 1},
        fallback=60,
    ) == 5


def test_trading_loop_interval_is_measured_start_to_start() -> None:
    assert _worker_sleep_delay(60, 17.5) == 42.5
    assert _worker_sleep_delay(60, 75) == 0
