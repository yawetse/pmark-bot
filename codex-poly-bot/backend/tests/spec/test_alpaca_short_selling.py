"""Specification tests for production-safe Alpaca short selling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json

import httpx
import pytest

from app.db import RepositoryRegistry
from app.domain import Environment, ExitTriggerType
from app.services.config_service import (
    ConfigPatchOperation,
    ConfigService,
    ConfigValidationError,
    default_config_payload,
)
from app.services.execution_service import (
    AlpacaExecutionRequest,
    FakeAlpacaVenueSubmitter,
    execute_alpaca_order,
)
from app.services.lifecycle_service import (
    DEFAULT_EXIT_CONFIG,
    _alpaca_realized_loss_for_day,
    _current_stock_position_opened_at,
    _stock_exit_triggers,
)
from app.venues.alpaca import AlpacaLiveOrderAdapter, AlpacaOrderSubmitError


def _eligible_account(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ACTIVE",
        "equity": "2500.00",
        "buying_power": "1000.00",
        "shorting_enabled": True,
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
    }
    payload.update(overrides)
    return payload


def _eligible_asset(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "SPY",
        "class": "us_equity",
        "status": "active",
        "tradable": True,
        "shortable": True,
        "borrow_status": "easy_to_borrow",
    }
    payload.update(overrides)
    return payload


def test_req_alp_019_default_and_patch_validation() -> None:
    assert default_config_payload()["alpaca"]["allow_shorting"] is False

    service = ConfigService(RepositoryRegistry())
    assert service._validated_patch_value(  # noqa: SLF001 - specification boundary
        ConfigPatchOperation("replace", "alpaca.allow_shorting", True)
    ) is True
    with pytest.raises(ConfigValidationError):
        service._validated_patch_value(  # noqa: SLF001 - specification boundary
            ConfigPatchOperation("replace", "alpaca.allow_shorting", "yes")
        )


def test_req_alp_020_021_022_sell_to_open_uses_current_eligible_state() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=_eligible_account())
        if request.url.path == "/v2/assets/SPY":
            return httpx.Response(200, json=_eligible_asset())
        return httpx.Response(200, json={"id": "short-order-1"})

    adapter = AlpacaLiveOrderAdapter(
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://alpaca.test",
        transport=httpx.MockTransport(handler),
    )

    order_id = adapter.submit_order(
        account_mode="paper",
        symbol="SPY",
        quantity=Decimal("2"),
        side="sell",
        position_intent="sell_to_open",
        estimated_unit_price=Decimal("100"),
    )

    assert order_id == "short-order-1"
    assert [(method, path) for method, path, _ in calls] == [
        ("GET", "/v2/account"),
        ("GET", "/v2/assets/SPY"),
        ("POST", "/v2/orders"),
    ]
    assert calls[-1][2] == {
        "symbol": "SPY",
        "side": "sell",
        "position_intent": "sell_to_open",
        "type": "market",
        "time_in_force": "day",
        "qty": "2",
    }


@pytest.mark.parametrize(
    ("account_override", "reason"),
    [
        ({"status": "INACTIVE"}, "account not active"),
        ({"equity": "1999.99"}, "equity below 2000"),
        ({"shorting_enabled": False}, "shorting not enabled"),
        ({"account_blocked": True}, "account blocked"),
        ({"trading_blocked": True}, "trading blocked"),
        ({"trade_suspended_by_user": True}, "trading suspended by user"),
        ({"buying_power": "205.99"}, "insufficient short buying power"),
    ],
)
def test_req_alp_020_ineligible_account_never_posts_order(
    account_override: dict[str, object],
    reason: str,
) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(200, json=_eligible_account(**account_override))

    adapter = AlpacaLiveOrderAdapter(
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://alpaca.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AlpacaOrderSubmitError, match=reason):
        adapter.submit_order(
            account_mode="paper",
            symbol="SPY",
            quantity=Decimal("2"),
            side="sell",
            position_intent="sell_to_open",
            estimated_unit_price=Decimal("100"),
        )
    assert "POST" not in methods


@pytest.mark.parametrize(
    "asset_override",
    [
        {"class": "crypto"},
        {"status": "inactive"},
        {"tradable": False},
        {"shortable": False},
        {"borrow_status": "hard_to_borrow"},
        {"borrow_status": None},
    ],
)
def test_req_alp_021_ineligible_asset_never_posts_order(
    asset_override: dict[str, object],
) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=_eligible_account())
        return httpx.Response(200, json=_eligible_asset(**asset_override))

    adapter = AlpacaLiveOrderAdapter(
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://alpaca.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AlpacaOrderSubmitError, match="asset not eligible for short sale"):
        adapter.submit_order(
            account_mode="paper",
            symbol="SPY",
            quantity=Decimal("1"),
            side="sell",
            position_intent="sell_to_open",
            estimated_unit_price=Decimal("100"),
        )
    assert "POST" not in methods


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1"), Decimal("1.5")])
def test_req_alp_022_short_entry_requires_positive_whole_shares(quantity: Decimal) -> None:
    adapter = AlpacaLiveOrderAdapter(
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://alpaca.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    with pytest.raises(AlpacaOrderSubmitError, match="whole-share quantity"):
        adapter.submit_order(
            account_mode="paper",
            symbol="SPY",
            quantity=quantity,
            side="sell",
            position_intent="sell_to_open",
            estimated_unit_price=Decimal("100"),
        )


def test_req_alp_025_exact_fractional_cover_bypasses_entry_eligibility() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "cover-order-1"})

    adapter = AlpacaLiveOrderAdapter(
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://alpaca.test",
        transport=httpx.MockTransport(handler),
    )

    adapter.submit_order(
        account_mode="paper",
        symbol="SPY",
        quantity=Decimal("1.25"),
        side="buy",
        position_intent="buy_to_close",
    )

    assert calls == [
        {
            "symbol": "SPY",
            "side": "buy",
            "position_intent": "buy_to_close",
            "type": "market",
            "time_in_force": "day",
            "qty": "1.25",
        }
    ]


def test_req_alp_022_execution_preserves_short_side_quantity_and_intent() -> None:
    submitter = FakeAlpacaVenueSubmitter()

    result = execute_alpaca_order(
        AlpacaExecutionRequest(
            global_execution_mode="live",
            account_mode="paper",
            risk_approved=True,
            symbol="SPY",
            quantity=Decimal("2"),
            side="sell",
            position_intent="sell_to_open",
            estimated_unit_price=Decimal("100"),
        ),
        submitter=submitter,
    )

    assert result.status == "submitted"
    assert submitter.submitted_orders[0]["side"] == "sell"
    assert submitter.submitted_orders[0]["quantity"] == "2"
    assert submitter.submitted_orders[0]["position_intent"] == "sell_to_open"


def test_req_alp_023_short_profit_loss_trailing_and_fill_ledger_are_direction_aware() -> None:
    now = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
    position = {
        "position_id": "short-spy",
        "position_side": "short",
        "quantity": Decimal("1"),
        "signed_quantity": Decimal("-1"),
        "entry_price": Decimal("100"),
        "current_price": Decimal("95"),
        "high_watermark_price": Decimal("90"),
        "opened_at": now - timedelta(hours=1),
        "source": {},
    }

    triggers = _stock_exit_triggers(
        position=position,
        config=DEFAULT_EXIT_CONFIG["alpaca"],
        now=now,
    )
    assert {trigger.trigger_type for trigger in triggers} == {
        ExitTriggerType.PROFIT_TARGET,
        ExitTriggerType.TRAILING_STOP,
    }

    fills = [
        {
            "account_id": "acct-1",
            "symbol": "SPY",
            "side": "sell",
            "quantity": Decimal("2"),
            "price": Decimal("100"),
            "filled_at": now - timedelta(hours=2),
        },
        {
            "account_id": "acct-1",
            "symbol": "SPY",
            "side": "buy",
            "quantity": Decimal("1"),
            "price": Decimal("110"),
            "filled_at": now,
        },
    ]
    assert _alpaca_realized_loss_for_day(fills, now) == Decimal("10")
    assert _current_stock_position_opened_at(fills) == now - timedelta(hours=2)
