"""Spec tests for Polymarket historical trade import foundations."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services import (
    POLYMARKET_CTF_EXCHANGE_V2,
    POLYMARKET_GAMMA_MARKET_SOURCE,
    PolymarketGammaMarketBackfiller,
    PolymarketHistoryImporter,
)


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
