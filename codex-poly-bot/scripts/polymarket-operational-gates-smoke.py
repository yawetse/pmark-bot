#!/usr/bin/env python3
"""Run non-order Polymarket operational gate checks.

This command proves the live-gated entry path, exit path, kill switch, and trade
notification wiring without calling a real venue and without sending real email.
It uses fake SDK and SES adapters, so it is safe to run before a funded live test.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.aws import InMemorySesEmailAdapter  # noqa: E402
from app.domain import OrderType, Venue  # noqa: E402
from app.services.notification_service import (  # noqa: E402
    NotificationDeliveryLedger,
    NotificationSettings,
    TradePlacedAlert,
    send_trade_placed_alert,
)
from app.services.risk_engine import LiveOrderGateInput, evaluate_live_order_gates  # noqa: E402
from app.venues.polymarket import (  # noqa: E402
    POLYMARKET_US_API_BASE_URL,
    PolymarketApiCredentials,
    PolymarketClientBoundary,
    PolymarketLiveOrderAdapter,
    PolymarketLiveOrderRequest,
    PolymarketVenueConfig,
)


class RecordingOrders:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.preview_calls: list[dict[str, Any]] = []
        self.close_position_calls: list[dict[str, Any]] = []

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(params)
        return {"id": "pm-contract-entry-1"}

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        self.preview_calls.append(params)
        return {"id": "pm-contract-preview-1"}

    def close_position(self, params: dict[str, Any]) -> dict[str, Any]:
        self.close_position_calls.append(params)
        return {"id": "pm-contract-exit-1"}


class RecordingClient:
    def __init__(self) -> None:
        self.orders = RecordingOrders()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notional", default="1.00")
    parser.add_argument("--market-slug", default="contract-proof-market")
    parser.add_argument("--recipient", default="operator@example.invalid")
    args = parser.parse_args()

    try:
        notional = parse_notional(args.notional)
    except ValueError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 2

    sdk = RecordingClient()
    adapter = PolymarketLiveOrderAdapter(
        config=PolymarketVenueConfig(
            venue=Venue.POLYMARKET_US,
            enabled=True,
            live_enabled=True,
            client_boundary=PolymarketClientBoundary.OFFICIAL_SDK,
            base_url=POLYMARKET_US_API_BASE_URL,
            credential_ref="/codex-poly-bot/production/polymarket/secret-key",
        ),
        credentials=PolymarketApiCredentials(key_id="redacted-key-id", secret_key="redacted-secret"),
        client_factory=lambda: sdk,
    )

    live_gate = evaluate_live_order_gates(
        LiveOrderGateInput(
            live_enabled=True,
            venue_enabled=True,
            credentials_present=True,
            venue_config_supported=True,
            market_data_fresh=True,
            scoring_succeeded=True,
            risk_approved=True,
            account_mode_valid=True,
            kill_switch_active=False,
        )
    )
    entry_result = adapter.submit_order(
        PolymarketLiveOrderRequest(
            market_slug=args.market_slug,
            intent="ORDER_INTENT_BUY_LONG",
            order_type=OrderType.MARKET,
            cash_order_qty=notional,
            current_price="0.50",
            slippage_tolerance_bips=200,
        )
    )
    exit_result = adapter.close_position(
        market_slug=args.market_slug,
        current_price="0.50",
        slippage_tolerance_bips=200,
    )
    kill_switch_gate = evaluate_live_order_gates(
        LiveOrderGateInput(
            live_enabled=True,
            venue_enabled=True,
            credentials_present=True,
            venue_config_supported=True,
            market_data_fresh=True,
            scoring_succeeded=True,
            risk_approved=True,
            account_mode_valid=True,
            kill_switch_active=True,
        )
    )

    ses = InMemorySesEmailAdapter()
    ledger = NotificationDeliveryLedger()
    notification = send_trade_placed_alert(
        settings=NotificationSettings.from_config({"recipients": {"operator": args.recipient}}),
        trade=TradePlacedAlert(
            venue=Venue.POLYMARKET_US.value,
            side="buy",
            instrument_id=f"polymarket_us:{args.market_slug}",
            order_type=OrderType.MARKET.value,
            notional_usd=str(notional),
            venue_order_id=entry_result.payload.get("venue_order_id"),
            idempotency_key="contract-proof-entry-key",
            reason="non-order operational gate proof",
        ),
        now=datetime.now(UTC),
        ses_adapter=ses,
        delivery_ledger=ledger,
    )

    output = {
        "ok": bool(
            live_gate.approved
            and entry_result.ok
            and exit_result.ok
            and not kill_switch_gate.approved
            and kill_switch_gate.refusal_reason == "KILL_SWITCH_ACTIVE"
            and notification.sent
        ),
        "real_venue_calls_attempted": False,
        "real_email_attempted": False,
        "entry_path": {
            "ok": entry_result.ok,
            "operation": entry_result.payload.get("operation"),
            "official_sdk_method": "orders.create",
            "create_call_count": len(sdk.orders.create_calls),
            "preview_call_count": len(sdk.orders.preview_calls),
            "market_slug": entry_result.payload.get("market_slug"),
            "order_type": entry_result.payload.get("order_type"),
            "venue": entry_result.payload.get("venue"),
        },
        "exit_path": {
            "ok": exit_result.ok,
            "operation": exit_result.payload.get("operation"),
            "official_sdk_method": "orders.close_position",
            "close_position_call_count": len(sdk.orders.close_position_calls),
            "market_slug": exit_result.payload.get("market_slug"),
            "venue": exit_result.payload.get("venue"),
        },
        "kill_switch": {
            "approved_when_inactive": live_gate.approved,
            "approved_when_active": kill_switch_gate.approved,
            "refusal_reason": kill_switch_gate.refusal_reason,
        },
        "notification": {
            "sent": notification.sent,
            "notification_type": notification.notification_type,
            "delivery_records": len(ledger.records),
            "ses_attempts": len(ses.attempts),
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["ok"] else 1


def parse_notional(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("--notional must be a decimal") from exc
    if parsed <= 0 or parsed > Decimal("5.00"):
        raise ValueError("--notional must be greater than 0 and no more than 5.00")
    return parsed.quantize(Decimal("0.01"))


if __name__ == "__main__":
    raise SystemExit(main())
