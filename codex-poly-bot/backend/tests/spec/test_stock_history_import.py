"""Spec tests for Alpaca stock history import foundations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services import (
    AlpacaBrokerHistoryBackfiller,
    AlpacaStockHistoryImporter,
)


def test_req_alp_017_05_stock_history_importer_reconstructs_realized_unrealized_pnl() -> None:
    """TST-REQ-ALP-017-05: Validates REQ-ALP-017 and REQ-DB-003

    Given: historical Alpaca fills and a broker position snapshot
    When: stock P&L is reconstructed
    Then: realized and unrealized P&L are stored per account and symbol
    """
    registry = RepositoryRegistry()
    importer = AlpacaStockHistoryImporter(registry)
    buy_at = datetime(2026, 6, 24, 14, 0, tzinfo=UTC)
    sell_at = datetime(2026, 6, 24, 15, 0, tzinfo=UTC)
    observed = datetime(2026, 6, 24, 20, 0, tzinfo=UTC)

    importer.record_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        payload={
            "id": "fill-buy",
            "order_id": "order-buy",
            "symbol": "SPY",
            "side": "buy",
            "qty": "10",
            "price": "100",
            "transaction_time": buy_at.isoformat(),
        },
    )
    importer.record_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        payload={
            "id": "fill-sell",
            "order_id": "order-sell",
            "symbol": "SPY",
            "side": "sell",
            "qty": "4",
            "price": "110",
            "transaction_time": sell_at.isoformat(),
        },
    )
    importer.record_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
            payload={
                "symbol": "SPY",
                "side": "long",
                "qty": "6",
            "avg_entry_price": "100",
            "cost_basis": "600",
            "market_value": "630",
            "current_price": "105",
            "unrealized_pl": "30",
        },
        observed_at=observed,
    )

    snapshots = importer.rebuild_position_pnl(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-1",
        calculated_at=observed,
    )

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["symbol"] == "SPY"
    assert snapshot["open_quantity"] == Decimal("6")
    assert snapshot["realized_pnl_usd"] == Decimal("40")
    assert snapshot["unrealized_pnl_usd"] == Decimal("30")
    assert snapshot["total_pnl_usd"] == Decimal("70")
    assert len(snapshot["fill_ids"]) == 2


def test_req_alp_023_stock_history_preserves_short_quantity_and_pnl() -> None:
    registry = RepositoryRegistry()
    importer = AlpacaStockHistoryImporter(registry)
    opened = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)
    covered = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)

    importer.record_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-short",
        payload={
            "id": "fill-short",
            "symbol": "F",
            "side": "sell",
            "qty": "2",
            "price": "100",
            "transaction_time": opened.isoformat(),
        },
    )
    importer.record_fill(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-short",
        payload={
            "id": "fill-cover",
            "symbol": "F",
            "side": "buy",
            "qty": "1",
            "price": "90",
            "transaction_time": covered.isoformat(),
        },
    )
    position = importer.record_position(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-short",
        payload={
            "symbol": "F",
            "side": "short",
            "qty": "1",
            "avg_entry_price": "100",
            "cost_basis": "-100",
            "market_value": "-95",
            "current_price": "95",
            "unrealized_pl": "5",
        },
        observed_at=covered,
    )

    snapshots = importer.rebuild_position_pnl(
        environment=Environment.DEVELOPMENT,
        account_mode="paper",
        account_id="acct-short",
        calculated_at=covered,
    )

    assert position["quantity"] == Decimal("-1")
    assert snapshots[0]["open_quantity"] == Decimal("-1")
    assert snapshots[0]["realized_pnl_usd"] == Decimal("10")
    assert snapshots[0]["unrealized_pnl_usd"] == Decimal("5")


def test_req_dat_008_06_alpaca_broker_history_backfill_persists_provider_rows() -> None:
    """TST-REQ-DAT-008-06: Validates REQ-DAT-008, REQ-ALP-003, and REQ-ALP-017

    Given: Alpaca account, orders, fills, positions, and stock bars endpoints return data
    When: the broker history backfiller runs
    Then: broker history, bars, P&L, and checkpoints are persisted
    """
    registry = RepositoryRegistry()
    observed = datetime(2026, 6, 25, 16, 0, tzinfo=UTC)
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={
                    "id": "acct-1",
                    "status": "ACTIVE",
                    "buying_power": "10000",
                    "cash": "9000",
                    "portfolio_value": "10120",
                    "equity": "10120",
                },
            )
        if request.url.path == "/v2/orders":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "order-1",
                        "client_order_id": "client-1",
                        "symbol": "SPY",
                        "side": "buy",
                        "type": "market",
                        "status": "filled",
                        "qty": "2",
                        "filled_qty": "2",
                        "filled_avg_price": "500",
                        "submitted_at": "2026-06-24T14:00:00Z",
                        "filled_at": "2026-06-24T14:00:01Z",
                    }
                ],
            )
        if request.url.path == "/v2/account/activities/FILL":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "fill-1",
                        "order_id": "order-1",
                        "symbol": "SPY",
                        "side": "buy",
                        "qty": "2",
                        "price": "500",
                        "transaction_time": "2026-06-24T14:00:01Z",
                    }
                ],
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[
                        {
                            "symbol": "SPY",
                            "side": "long",
                            "qty": "2",
                        "avg_entry_price": "500",
                        "cost_basis": "1000",
                        "market_value": "1010",
                        "current_price": "505",
                        "unrealized_pl": "10",
                    }
                ],
            )
        if request.url.path == "/v2/stocks/bars":
            assert request.url.params["symbols"] == "SPY,QQQ"
            assert request.url.params["timeframe"] == "1Day"
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "SPY": [
                            {
                                "t": "2026-06-24T20:00:00Z",
                                "o": "500",
                                "h": "506",
                                "l": "499",
                                "c": "505",
                                "v": "1000000",
                                "n": 1234,
                                "vw": "503",
                            }
                        ],
                        "QQQ": [
                            {
                                "t": "2026-06-24T20:00:00Z",
                                "o": "380",
                                "h": "384",
                                "l": "379",
                                "c": "383",
                                "v": "800000",
                                "n": 987,
                                "vw": "382",
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404)

    backfiller = AlpacaBrokerHistoryBackfiller(
        registry,
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://paper-api.alpaca.test",
        data_base_url="https://data.alpaca.test/v2",
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill(
        environment=Environment.DEVELOPMENT,
        config_payload={"alpaca": {"symbol_universe": ["SPY", "QQQ"]}},
        start_at=datetime(2026, 6, 24, 0, 0, tzinfo=UTC),
        end_at=observed,
        max_symbols=2,
        imported_at=observed,
    )

    assert requested_paths == [
        "/v2/account",
        "/v2/orders",
        "/v2/account/activities/FILL",
        "/v2/positions",
        "/v2/stocks/bars",
    ]
    assert summary.status == "stored"
    assert summary.account_id == "acct-1"
    assert summary.order_count == 1
    assert summary.fill_count == 1
    assert summary.position_count == 1
    assert summary.bar_count == 2
    assert summary.pnl_count == 1
    shared = registry.shared()
    assert len(shared.alpaca_historical_orders(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_historical_fills(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_historical_positions(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.alpaca_broker_account_snapshots(environment=Environment.DEVELOPMENT)) == 1
    assert len(shared.stock_bars(environment=Environment.DEVELOPMENT)) == 2
    assert shared.alpaca_symbol_pnl_snapshots(environment=Environment.DEVELOPMENT)[0][
        "unrealized_pnl_usd"
    ] == Decimal("10")
    checkpoint_sources = {
        row["source"]
        for row in shared.historical_import_checkpoints(environment=Environment.DEVELOPMENT)
    }
    assert checkpoint_sources == {"alpaca_broker_history:paper", "alpaca_stock_bars:paper:1Day"}


def test_req_dat_008_07_alpaca_broker_history_rate_limit_records_checkpoint() -> None:
    """TST-REQ-DAT-008-07: Validates REQ-DAT-008

    Given: Alpaca rate limits a broker history endpoint
    When: the backfiller runs
    Then: status is rate_limited and the last cursor is preserved
    """
    registry = RepositoryRegistry()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "rate limited"})

    backfiller = AlpacaBrokerHistoryBackfiller(
        registry,
        account_mode="paper",
        environ={"ALPACA_KEY_ID": "key", "ALPACA_SECRET_KEY": "secret"},
        trading_base_url="https://paper-api.alpaca.test",
        data_base_url="https://data.alpaca.test/v2",
        transport=httpx.MockTransport(handler),
    )
    start = datetime(2026, 6, 24, tzinfo=UTC)

    summary = backfiller.backfill(
        environment=Environment.DEVELOPMENT,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        start_at=start,
    )

    checkpoints = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )
    assert summary.status == "rate_limited"
    assert summary.error_code == "provider_rate_limited"
    assert checkpoints[0]["source"] == "alpaca_broker_history:paper"
    assert checkpoints[0]["status"] == "rate_limited"
    assert checkpoints[0]["cursor_value"] == start.isoformat()
