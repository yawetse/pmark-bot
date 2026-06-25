"""Spec tests for Polymarket historical trade import foundations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services import (
    POLYMARKET_CTF_EXCHANGE_V2,
    POLYMARKET_GAMMA_MARKET_SOURCE,
    POLYMARKET_POLYGON_ORDER_FILLED_SOURCE,
    PolymarketGammaMarketBackfiller,
    PolymarketHistoryImporter,
    PolymarketPolygonOrderFilledBackfiller,
    decode_order_filled_v2_log,
)


ORDER_FILLED_TOPIC = "0x" + "11" * 32
ORDER_HASH_TOPIC = "0x" + "22" * 32
MAKER_ADDRESS = "0xabcDEF0000000000000000000000000000000001"
TAKER_ADDRESS = "0xabcDEF0000000000000000000000000000000002"


def test_req_dat_009_01_polymarket_history_importer_persists_fixture_step_zero_data() -> None:
    """TST-REQ-DAT-009-01: Validates REQ-DAT-009

    Given: fixture Gamma market metadata, decoded chain fill data, and processed trades
    When: the clean-room importer persists the Step 0 data
    Then: downstream scanner and whale-copy steps have normalized historical records
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    observed = datetime(2026, 6, 25, 12, 30, tzinfo=UTC)

    market = importer.record_market_metadata(
        environment=Environment.DEVELOPMENT,
        fetched_at=observed,
        payload={
            "id": "market-1",
            "conditionId": "0xcondition",
            "slug": "btc-above-100k",
            "question": "Will BTC close above 100k?",
            "active": False,
            "closed": True,
            "category": "crypto",
            "endDate": "2026-06-30T00:00:00Z",
            "tokens": [{"token_id": "yes-token", "outcome": "YES"}],
            "tags": [{"label": "Crypto"}],
        },
    )
    fill = importer.record_decoded_fill_event(
        environment=Environment.DEVELOPMENT,
        block_timestamp=observed,
        event={
            "address": POLYMARKET_CTF_EXCHANGE_V2,
            "blockNumber": 100,
            "blockHash": "0xblock",
            "logIndex": 2,
            "transactionHash": "0xtx",
            "args": {
                "maker": "0xabcDEF0000000000000000000000000000000001",
                "taker": "0xabcDEF0000000000000000000000000000000002",
                "assetId": "yes-token",
                "conditionId": "0xcondition",
            },
        },
    )
    trade = importer.record_processed_trade(
        environment=Environment.DEVELOPMENT,
        raw_event_id=fill["id"],
        market_record_id=market["id"],
        trade={
            "market_id": "market-1",
            "condition_id": "0xcondition",
            "asset_id": "yes-token",
            "wallet_address": "0xabcDEF0000000000000000000000000000000001",
            "side": "BUY",
            "price": "0.42",
            "size": "10",
            "outcome": "YES",
            "role": "maker",
            "transaction_hash": "0xtx",
            "block_number": 100,
            "traded_at": observed.isoformat(),
        },
    )

    assert market["market_id"] == "market-1"
    assert fill["exchange_contract"] == POLYMARKET_CTF_EXCHANGE_V2
    assert trade["wallet_address"] == "0xabcdef0000000000000000000000000000000001"
    assert trade["notional_usd"] == Decimal("4.20")
    assert len(registry.state.rows("shared.polymarket_gamma_markets")) == 1
    assert len(registry.state.rows("shared.polymarket_chain_fill_events")) == 1
    assert len(registry.state.rows("shared.polymarket_trades")) == 1


def test_req_dat_009_02_polymarket_target_wallet_snapshot_uses_pmbot_thresholds() -> None:
    """TST-REQ-DAT-009-02: Validates REQ-DAT-009 and REQ-STR-002

    Given: wallet performance rows above and below the pmbot thresholds
    When: the importer builds a target wallet snapshot
    Then: only wallets with enough trades and win rate are ranked by realized P&L
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    shared = registry.shared()
    observed = datetime(2026, 6, 25, 12, 45, tzinfo=UTC)

    shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address="0x1111111111111111111111111111111111111111",
        trade_count=130,
        win_rate=Decimal("0.72"),
        total_realized_pnl_usd=Decimal("500"),
        source="fixture",
        calculated_at=observed,
    )
    shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address="0x2222222222222222222222222222222222222222",
        trade_count=210,
        win_rate=Decimal("0.81"),
        total_realized_pnl_usd=Decimal("900"),
        source="fixture",
        calculated_at=observed,
    )
    shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address="0x3333333333333333333333333333333333333333",
        trade_count=40,
        win_rate=Decimal("0.95"),
        total_realized_pnl_usd=Decimal("1200"),
        source="fixture",
        calculated_at=observed,
    )

    snapshot = importer.build_target_wallet_snapshot(environment=Environment.DEVELOPMENT)

    assert snapshot["min_trade_count"] == 100
    assert snapshot["min_win_rate"] == Decimal("0.70")
    assert snapshot["wallet_count"] == 2
    assert [wallet["walletAddress"] for wallet in snapshot["wallets"]] == [
        "0x2222222222222222222222222222222222222222",
        "0x1111111111111111111111111111111111111111",
    ]


def test_req_dat_009_03_polymarket_history_checkpoint_upserts_by_source() -> None:
    """TST-REQ-DAT-009-03: Validates REQ-DAT-009

    Given: two checkpoint writes for the same source
    When: the importer records the newer cursor
    Then: the checkpoint row is updated instead of duplicated
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    observed = datetime(2026, 6, 25, 13, 0, tzinfo=UTC)

    first = importer.record_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="polygon_order_filled",
        cursor_type="block_number",
        cursor_value="100",
        status="stored",
        metadata={"range": "1-100"},
        last_success_at=observed,
    )
    second = importer.record_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source="polygon_order_filled",
        cursor_type="block_number",
        cursor_value="250",
        status="stored",
        metadata={"range": "101-250"},
        last_success_at=observed,
    )

    assert second["id"] == first["id"]
    assert second["cursor_value"] == "250"
    assert len(registry.state.rows("shared.historical_import_checkpoints")) == 1


def test_req_dat_009_04_gamma_market_backfill_uses_limit_offset_checkpoint() -> None:
    """TST-REQ-DAT-009-04: Validates REQ-DAT-009

    Given: Gamma returns two limit/offset pages of active markets
    When: the historical backfiller runs against the provider boundary
    Then: market metadata is persisted and the next offset checkpoint is stored
    """
    registry = RepositoryRegistry()
    observed = datetime(2026, 6, 25, 13, 15, tzinfo=UTC)
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/markets"
        params = dict(request.url.params)
        calls.append(params)
        offset = int(params["offset"])
        pages = {
            0: [
                _gamma_market("market-1", "0xcondition1"),
                _gamma_market("market-2", "0xcondition2"),
            ],
            2: [_gamma_market("market-3", "0xcondition3")],
        }
        return httpx.Response(200, json=pages[offset])

    backfiller = PolymarketGammaMarketBackfiller(
        registry,
        base_url="https://gamma.polymarket.test",
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill_markets(
        environment=Environment.DEVELOPMENT,
        limit=2,
        max_pages=2,
        active=True,
        closed=False,
        order="volume",
        ascending=False,
        fetched_at=observed,
    )

    rows = registry.state.rows("shared.polymarket_gamma_markets")
    checkpoint = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )[0]
    assert [call["offset"] for call in calls] == ["0", "2"]
    assert all(call["limit"] == "2" for call in calls)
    assert all(call["active"] == "true" for call in calls)
    assert all(call["closed"] == "false" for call in calls)
    assert summary.market_count == 3
    assert summary.status == "complete"
    assert summary.next_cursor == "3"
    assert summary.source == f"{POLYMARKET_GAMMA_MARKET_SOURCE}:active=true:closed=false"
    assert [row["market_id"] for row in rows] == ["market-1", "market-2", "market-3"]
    assert checkpoint["cursor_value"] == "3"
    assert checkpoint["status"] == "complete"
    assert checkpoint["last_success_at"] == observed


def test_req_dat_009_05_gamma_market_backfill_resumes_from_checkpoint() -> None:
    """TST-REQ-DAT-009-05: Validates REQ-DAT-009

    Given: a stored Gamma offset checkpoint
    When: the backfiller runs again
    Then: the next provider request starts from the checkpoint cursor
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    source = f"{POLYMARKET_GAMMA_MARKET_SOURCE}:closed=true"
    importer.record_import_checkpoint(
        environment=Environment.DEVELOPMENT,
        source=source,
        cursor_type="offset",
        cursor_value="2",
        status="stored",
    )
    requested_offsets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_offsets.append(str(request.url.params["offset"]))
        return httpx.Response(200, json=[_gamma_market("market-3", "0xcondition3")])

    backfiller = PolymarketGammaMarketBackfiller(
        registry,
        base_url="https://gamma.polymarket.test",
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill_markets(
        environment=Environment.DEVELOPMENT,
        limit=100,
        max_pages=1,
        closed=True,
    )

    checkpoint = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )[0]
    assert requested_offsets == ["2"]
    assert summary.market_count == 1
    assert summary.next_cursor == "3"
    assert checkpoint["cursor_value"] == "3"
    assert checkpoint["status"] == "complete"


def test_req_dat_009_06_gamma_market_backfill_records_rate_limit_status() -> None:
    """TST-REQ-DAT-009-06: Validates REQ-DAT-009

    Given: Gamma returns HTTP 429
    When: the backfiller runs
    Then: no market rows are stored and the checkpoint records rate limiting
    """
    registry = RepositoryRegistry()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    backfiller = PolymarketGammaMarketBackfiller(
        registry,
        base_url="https://gamma.polymarket.test",
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill_markets(environment=Environment.DEVELOPMENT, limit=50)

    checkpoint = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )[0]
    assert summary.status == "rate_limited"
    assert summary.error_code == "provider_rate_limited"
    assert summary.market_count == 0
    assert registry.state.rows("shared.polymarket_gamma_markets") == []
    assert checkpoint["status"] == "rate_limited"
    assert checkpoint["cursor_value"] == "0"


def test_req_dat_009_07_decodes_order_filled_v2_fixture_log() -> None:
    """TST-REQ-DAT-009-07: Validates REQ-DAT-009

    Given: a CTF Exchange V2 OrderFilled fixture log
    When: the log is decoded and stored through the importer boundary
    Then: indexed addresses, token id, amounts, and hex block fields are normalized
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    raw_log = _order_filled_log(
        block_number=84902321,
        log_index=4,
        transaction_hash="0xtx1",
        token_id=12345,
        maker_amount=1_000_000,
        taker_amount=420_000,
    )

    decoded = decode_order_filled_v2_log(raw_log)
    stored = importer.record_decoded_fill_event(
        environment=Environment.DEVELOPMENT,
        event=decoded,
        block_timestamp=datetime(2026, 6, 25, 14, 0, tzinfo=UTC),
    )

    assert decoded["args"]["orderHash"] == ORDER_HASH_TOPIC
    assert decoded["args"]["maker"] == MAKER_ADDRESS.lower()
    assert decoded["args"]["taker"] == TAKER_ADDRESS.lower()
    assert decoded["args"]["side"] == 0
    assert decoded["args"]["tokenId"] == "12345"
    assert decoded["args"]["makerAmountFilled"] == "1000000"
    assert decoded["args"]["takerAmountFilled"] == "420000"
    assert stored["block_number"] == 84902321
    assert stored["log_index"] == 4
    assert stored["maker_address"] == MAKER_ADDRESS.lower()
    assert stored["taker_address"] == TAKER_ADDRESS.lower()
    assert stored["asset_id"] == "12345"


def test_req_dat_009_08_polygon_order_filled_backfill_splits_retry_windows() -> None:
    """TST-REQ-DAT-009-08: Validates REQ-DAT-009

    Given: Polygon RPC rejects a broad eth_getLogs range but accepts smaller ranges
    When: the OrderFilled backfiller runs
    Then: it retries split block windows, persists logs, and checkpoints the scanned block
    """
    registry = RepositoryRegistry()
    observed = datetime(2026, 6, 25, 14, 10, tzinfo=UTC)
    requested_ranges: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _request_json(request)
        assert payload["method"] == "eth_getLogs"
        params = payload["params"][0]
        assert params["address"] == POLYMARKET_CTF_EXCHANGE_V2.lower()
        assert params["topics"] == [ORDER_FILLED_TOPIC]
        requested_ranges.append((params["fromBlock"], params["toBlock"]))
        if params["fromBlock"] == "0x64" and params["toBlock"] == "0x68":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32005, "message": "block range too large"},
                },
            )
        if params["fromBlock"] == "0x64" and params["toBlock"] == "0x66":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": [_order_filled_log(100, 1, "0xtx100")]},
            )
        if params["fromBlock"] == "0x67" and params["toBlock"] == "0x68":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": [_order_filled_log(104, 2, "0xtx104")]},
            )
        return httpx.Response(500, json={"error": "unexpected range"})

    backfiller = PolymarketPolygonOrderFilledBackfiller(
        registry,
        rpc_url="https://polygon-rpc.test",
        order_filled_topic=ORDER_FILLED_TOPIC,
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill_order_filled_events(
        environment=Environment.DEVELOPMENT,
        start_block=100,
        end_block=104,
        max_block_range=5,
        max_windows=1,
        fetched_at=observed,
    )

    rows = registry.state.rows("shared.polymarket_chain_fill_events")
    checkpoint = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )[0]
    assert requested_ranges == [("0x64", "0x68"), ("0x64", "0x66"), ("0x67", "0x68")]
    assert summary.chain_fill_count == 2
    assert summary.status == "complete"
    assert summary.next_cursor == "104"
    assert summary.source == (
        f"{POLYMARKET_POLYGON_ORDER_FILLED_SOURCE}:"
        f"{POLYMARKET_CTF_EXCHANGE_V2.lower()}:{ORDER_FILLED_TOPIC}"
    )
    assert [row["transaction_hash"] for row in rows] == ["0xtx100", "0xtx104"]
    assert checkpoint["cursor_value"] == "104"
    assert checkpoint["status"] == "complete"
    assert checkpoint["last_success_at"] == observed


def test_req_dat_009_09_polygon_order_filled_backfill_records_rate_limit() -> None:
    """TST-REQ-DAT-009-09: Validates REQ-DAT-009

    Given: Polygon RPC rate limits eth_getLogs
    When: the OrderFilled backfiller runs
    Then: no logs are stored and checkpoint status records the rate limit
    """
    registry = RepositoryRegistry()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    backfiller = PolymarketPolygonOrderFilledBackfiller(
        registry,
        rpc_url="https://polygon-rpc.test",
        order_filled_topic=ORDER_FILLED_TOPIC,
        transport=httpx.MockTransport(handler),
    )

    summary = backfiller.backfill_order_filled_events(
        environment=Environment.DEVELOPMENT,
        start_block=100,
        end_block=101,
    )

    checkpoint = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )[0]
    assert summary.status == "rate_limited"
    assert summary.error_code == "provider_rate_limited"
    assert summary.chain_fill_count == 0
    assert summary.next_cursor == "99"
    assert registry.state.rows("shared.polymarket_chain_fill_events") == []
    assert checkpoint["status"] == "rate_limited"
    assert checkpoint["cursor_value"] == "99"


def test_req_dat_009_10_wallet_performance_rebuild_feeds_target_ranking() -> None:
    """TST-REQ-DAT-009-10: Validates REQ-DAT-009 and REQ-STR-002

    Given: realized historical trade rows for several Polymarket wallets
    When: wallet performance stats and the target wallet snapshot are rebuilt
    Then: only wallets with 100+ realized trades and 70%+ win rate are ranked by P&L
    """
    registry = RepositoryRegistry()
    importer = PolymarketHistoryImporter(registry)
    observed = datetime(2026, 6, 25, 14, 30, tzinfo=UTC)
    wallet_high_pnl = "0x4444444444444444444444444444444444444444"
    wallet_lower_pnl = "0x5555555555555555555555555555555555555555"
    wallet_low_win_rate = "0x6666666666666666666666666666666666666666"
    wallet_low_count = "0x7777777777777777777777777777777777777777"

    _record_realized_trades(
        importer,
        wallet_address=wallet_high_pnl,
        trade_count=120,
        win_count=90,
        win_pnl=Decimal("1.00"),
        loss_pnl=Decimal("-0.10"),
        observed=observed,
    )
    _record_realized_trades(
        importer,
        wallet_address=wallet_lower_pnl,
        trade_count=100,
        win_count=80,
        win_pnl=Decimal("0.75"),
        loss_pnl=Decimal("-0.25"),
        observed=observed,
    )
    _record_realized_trades(
        importer,
        wallet_address=wallet_low_win_rate,
        trade_count=100,
        win_count=69,
        win_pnl=Decimal("2.00"),
        loss_pnl=Decimal("-0.10"),
        observed=observed,
    )
    _record_realized_trades(
        importer,
        wallet_address=wallet_low_count,
        trade_count=99,
        win_count=99,
        win_pnl=Decimal("5.00"),
        loss_pnl=Decimal("-0.01"),
        observed=observed,
    )

    stats = importer.rebuild_wallet_performance_stats(
        environment=Environment.DEVELOPMENT,
        calculated_at=observed,
    )
    snapshot = importer.build_target_wallet_snapshot(environment=Environment.DEVELOPMENT)

    stats_by_wallet = {row["wallet_address"]: row for row in stats}
    assert stats_by_wallet[wallet_high_pnl]["trade_count"] == 120
    assert stats_by_wallet[wallet_high_pnl]["win_rate"] == Decimal("0.75")
    assert stats_by_wallet[wallet_high_pnl]["total_realized_pnl_usd"] == Decimal("87.00")
    assert stats_by_wallet[wallet_lower_pnl]["trade_count"] == 100
    assert stats_by_wallet[wallet_lower_pnl]["win_rate"] == Decimal("0.8")
    assert stats_by_wallet[wallet_lower_pnl]["total_realized_pnl_usd"] == Decimal("55.00")
    assert snapshot["wallet_count"] == 2
    assert [wallet["walletAddress"] for wallet in snapshot["wallets"]] == [
        wallet_high_pnl,
        wallet_lower_pnl,
    ]


def _gamma_market(market_id: str, condition_id: str) -> dict:
    return {
        "id": market_id,
        "conditionId": condition_id,
        "slug": market_id,
        "question": f"Will {market_id} resolve yes?",
        "active": True,
        "closed": False,
        "category": "crypto",
        "endDate": "2026-07-01T00:00:00Z",
        "clobTokenIds": [f"{market_id}-yes", f"{market_id}-no"],
        "outcomes": ["YES", "NO"],
    }


def _order_filled_log(
    block_number: int,
    log_index: int,
    transaction_hash: str,
    *,
    token_id: int = 42,
    maker_amount: int = 1_000_000,
    taker_amount: int = 500_000,
) -> dict:
    return {
        "address": POLYMARKET_CTF_EXCHANGE_V2,
        "blockNumber": hex(block_number),
        "blockHash": "0xblock",
        "logIndex": hex(log_index),
        "transactionHash": transaction_hash,
        "topics": [
            ORDER_FILLED_TOPIC,
            ORDER_HASH_TOPIC,
            _address_topic(MAKER_ADDRESS),
            _address_topic(TAKER_ADDRESS),
        ],
        "data": "0x"
        + _word(0)
        + _word(token_id)
        + _word(maker_amount)
        + _word(taker_amount)
        + _word(0)
        + ("33" * 32)
        + ("44" * 32),
    }


def _address_topic(address: str) -> str:
    return "0x" + ("0" * 24) + address.lower().removeprefix("0x")


def _word(value: int) -> str:
    return f"{value:064x}"


def _request_json(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


def _record_realized_trades(
    importer: PolymarketHistoryImporter,
    *,
    wallet_address: str,
    trade_count: int,
    win_count: int,
    win_pnl: Decimal,
    loss_pnl: Decimal,
    observed: datetime,
) -> None:
    for index in range(trade_count):
        realized_pnl = win_pnl if index < win_count else loss_pnl
        importer.record_processed_trade(
            environment=Environment.DEVELOPMENT,
            trade={
                "market_id": f"market-{wallet_address[-4:]}",
                "condition_id": f"0xcondition{wallet_address[-4:]}",
                "asset_id": f"token-{wallet_address[-4:]}",
                "wallet_address": wallet_address,
                "side": "BUY",
                "price": "0.50",
                "size": "1",
                "realized_pnl_usd": str(realized_pnl),
                "outcome": "YES",
                "role": "maker",
                "transaction_hash": f"0xtx{wallet_address[-4:]}{index}",
                "block_number": 90000000 + index,
                "traded_at": observed.isoformat(),
            },
        )
