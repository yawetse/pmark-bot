"""Spec tests for deterministic scanner persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db import DatabaseState, RepositoryRegistry
from app.domain import Environment, Venue
from app.services.scanner_service import ScannerService


class TrackingDatabaseState(DatabaseState):
    def __init__(self) -> None:
        super().__init__()
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def begin_transaction(self) -> dict[str, list[dict]]:
        self.begin_count += 1
        return super().begin_transaction()

    def commit_transaction(self, transaction: dict[str, list[dict]]) -> None:
        self.commit_count += 1
        super().commit_transaction(transaction)

    def rollback_transaction(self, transaction: dict[str, list[dict]]) -> None:
        self.rollback_count += 1
        super().rollback_transaction(transaction)


def _scanner_batch_pull(now: datetime) -> list[dict]:
    return [
        {
            "id": "pull-batch",
            "venue": Venue.POLYMARKET_US.value,
            "status": "pulled",
            "candidates": [
                {
                    "id": f"polymarket_us:condition-{index}:yes-token-{index}",
                    "venue": Venue.POLYMARKET_US.value,
                    "market": f"Batch market {index} - Yes",
                    "marketId": f"condition-{index}",
                    "tokenId": f"yes-token-{index}",
                    "state": "priced",
                    "price": "0.45",
                    "bestBid": "0.44",
                    "bestAsk": "0.46",
                    "bidDepth": "600",
                    "askDepth": "650",
                    "liquidity": "1250",
                    "spread": "0.02",
                    "volume": "10000",
                    "endDate": (now + timedelta(hours=24)).isoformat(),
                    "active": True,
                    "closed": False,
                }
                for index in range(3)
            ],
        }
    ]


def test_req_db_009_01_scanner_batch_commits_once() -> None:
    """TST-REQ-DB-009-01: Validates REQ-DB-009."""

    state = TrackingDatabaseState()
    registry = RepositoryRegistry(state)
    now = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)

    result = ScannerService(registry).run(
        environment=Environment.PRODUCTION,
        pipeline_run_id="batch-run",
        trigger="scheduled",
        market_data_pulls=_scanner_batch_pull(now),
        config_payload={},
        started_at=now,
        completed_at=now,
    )

    assert result.payload["candidateCount"] == 3
    assert state.begin_count == 1
    assert state.commit_count == 1
    assert state.rollback_count == 0
    assert len(state.rows("shared.scanner_runs")) == 1
    assert len(state.rows("shared.scanner_candidates")) == 3


def test_req_db_009_02_scanner_batch_rolls_back_on_candidate_failure() -> None:
    """TST-REQ-DB-009-02: Validates REQ-DB-009."""

    state = TrackingDatabaseState()
    state.fail_on_tables.add("shared.scanner_candidates")
    registry = RepositoryRegistry(state)
    now = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)

    result = ScannerService(registry).run(
        environment=Environment.PRODUCTION,
        pipeline_run_id="failed-batch-run",
        trigger="scheduled",
        market_data_pulls=_scanner_batch_pull(now),
        config_payload={},
        started_at=now,
        completed_at=now,
    )

    assert result.row is None
    assert state.begin_count == 1
    assert state.commit_count == 0
    assert state.rollback_count == 1
    assert state.rows("shared.scanner_runs") == []
    assert state.rows("shared.scanner_candidates") == []


def test_req_str_003_03_polymarket_scanner_persists_acceptance_rejection_and_wallet_overlap() -> None:
    """TST-REQ-STR-003-03: Validates REQ-STR-003 and REQ-OBS-005

    Given: Polymarket provider candidates and target wallet history
    When: the scanner runs
    Then: accepted and rejected scanner rows are persisted with refusal reasons and wallet overlap
    """

    registry = RepositoryRegistry()
    shared = registry.shared()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    wallet = "0x1111111111111111111111111111111111111111"
    shared.record_polymarket_wallet_performance_stat(
        environment=Environment.DEVELOPMENT,
        wallet_address=wallet,
        trade_count=125,
        win_rate=Decimal("0.75"),
        total_realized_pnl_usd=Decimal("250"),
        source="fixture",
        calculated_at=now,
    )
    shared.record_polymarket_target_wallet_snapshot(
        environment=Environment.DEVELOPMENT,
        min_trade_count=100,
        min_win_rate=Decimal("0.70"),
        wallets=[{"walletAddress": wallet}],
        source_stat_ids=["stat-1"],
        created_at=now,
    )
    shared.record_polymarket_wallet_position(
        environment=Environment.DEVELOPMENT,
        wallet_address=wallet,
        market_id="condition-1",
        asset_id="yes-token",
        state="open",
        size=Decimal("10"),
        realized_pnl_usd=Decimal("0"),
        trade_ids=[],
        opened_at=now - timedelta(hours=2),
    )

    result = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="run-1",
        trigger="manual",
        started_at=now,
        completed_at=now,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        market_data_pulls=[
            {
                "id": "pull-1",
                "venue": Venue.POLYMARKET_US.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "polymarket_us:condition-1:yes-token",
                        "venue": Venue.POLYMARKET_US.value,
                        "market": "Will rates fall? - Yes",
                        "marketId": "condition-1",
                        "tokenId": "yes-token",
                        "state": "priced",
                        "midpoint": "0.45",
                        "price": "0.45",
                        "bestBid": "0.44",
                        "bestAsk": "0.46",
                        "bidDepth": "600",
                        "askDepth": "650",
                        "liquidity": "1250",
                        "spread": "0.02",
                        "volume": "10000",
                        "category": "Politics",
                        "endDate": (now + timedelta(hours=24)).isoformat(),
                        "active": True,
                        "closed": False,
                    },
                    {
                        "id": "polymarket_us:condition-2:no-token",
                        "venue": Venue.POLYMARKET_US.value,
                        "market": "Will rates rise? - No",
                        "marketId": "condition-2",
                        "tokenId": "no-token",
                        "state": "priced",
                        "midpoint": "0.52",
                        "price": "0.52",
                        "bestBid": "0.50",
                        "bestAsk": "0.54",
                        "bidDepth": "600",
                        "askDepth": "50",
                        "liquidity": "650",
                        "spread": "0.04",
                        "volume": "10000",
                        "endDate": (now + timedelta(hours=24)).isoformat(),
                        "active": True,
                        "closed": False,
                    },
                ],
            }
        ],
    )

    rows = registry.shared().scanner_candidates(environment=Environment.DEVELOPMENT)
    accepted = [row for row in rows if row["status"] == "accepted"]
    rejected = [row for row in rows if row["status"] == "rejected"]

    assert result.payload["status"] == "completed"
    assert result.payload["acceptedCount"] == 1
    assert result.payload["rejectedCount"] == 1
    assert accepted[0]["metrics"]["targetWalletOverlap"] == 1
    assert accepted[0]["strategy_names"] == ["order_book_depth", "resolution_window"]
    assert rejected[0]["refusal_reason"] == "ask depth below minimum"


def test_req_str_003_04_stock_scanner_persists_strategy_matches_and_refusals() -> None:
    """TST-REQ-STR-003-04: Validates REQ-STR-003 and REQ-ALP-014

    Given: Alpaca candidates and stored stock bars
    When: the scanner runs over the configured universe
    Then: stock strategy matches and rejected symbols are persisted with reasons
    """

    registry = RepositoryRegistry()
    shared = registry.shared()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)
    for index, close_price in enumerate((Decimal("100"), Decimal("102"), Decimal("106"))):
        shared.record_stock_bar(
            environment=Environment.DEVELOPMENT,
            symbol="SPY",
            timeframe="1Day",
            bar_start_at=now - timedelta(days=2 - index),
            open_price=Decimal("102") if index == 2 else close_price,
            high_price=Decimal("107") if index == 2 else close_price,
            low_price=Decimal("101") if index == 2 else close_price,
            close_price=close_price,
            volume=Decimal("300000") if index == 2 else Decimal("100000"),
            source="alpaca market data api",
            raw_payload={"index": index},
        )

    result = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="run-2",
        trigger="manual",
        started_at=now,
        completed_at=now,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        market_data_pulls=[
            {
                "id": "pull-2",
                "venue": Venue.ALPACA.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "alpaca:SPY",
                        "venue": Venue.ALPACA.value,
                        "symbol": "SPY",
                        "state": "priced",
                        "price": "106",
                        "liquidity": "3",
                        "spread": "0.02",
                    },
                    {
                        "id": "alpaca:XYZ",
                        "venue": Venue.ALPACA.value,
                        "symbol": "XYZ",
                        "state": "priced",
                        "price": "10",
                        "liquidity": "5",
                        "spread": "0.01",
                    },
                ],
            }
        ],
    )

    rows = registry.shared().scanner_candidates(environment=Environment.DEVELOPMENT)
    spy = next(row for row in rows if row["symbol"] == "SPY")
    xyz = next(row for row in rows if row["symbol"] == "XYZ")

    assert result.payload["status"] == "completed"
    assert spy["status"] == "accepted"
    assert set(spy["strategy_names"]) >= {"momentum", "liquidity", "volatility", "unusual_volume"}
    assert spy["metrics"]["historyBarCount"] == 3
    assert xyz["status"] == "rejected"
    assert xyz["refusal_reason"] == "symbol outside universe"


def test_req_alp_014_04_stock_scanner_matches_class_share_symbol_aliases() -> None:
    """TST-REQ-ALP-014-04: Validates REQ-ALP-014 and REQ-STR-003

    Given: the configured universe stores a class-share symbol with hyphen notation
    When: Alpaca returns the API symbol with dot notation
    Then: the scanner treats the symbols as the same stock instead of rejecting it
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)

    result = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="run-class-share",
        trigger="manual",
        started_at=now,
        completed_at=now,
        config_payload={"alpaca": {"symbol_universe": ["BRK-B"]}},
        market_data_pulls=[
            {
                "id": "pull-class-share",
                "venue": Venue.ALPACA.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "alpaca:BRK.B",
                        "venue": Venue.ALPACA.value,
                        "symbol": "BRK.B",
                        "requestedSymbol": "BRK-B",
                        "state": "priced",
                        "price": "410",
                        "liquidity": "3",
                        "spread": "0.02",
                        "historyBarCount": 2,
                        "previousClose": "400",
                        "latestOpen": "402",
                        "latestHigh": "412",
                        "latestLow": "401",
                        "latestClose": "410",
                        "latestVolume": "150000",
                        "averageVolume": "100000",
                    },
                ],
            }
        ],
    )

    rows = registry.shared().scanner_candidates(environment=Environment.DEVELOPMENT)
    candidate = rows[0]

    assert result.payload["acceptedCount"] == 1
    assert candidate["symbol"] == "BRK.B"
    assert candidate["status"] == "accepted"
    assert candidate["refusal_reason"] is None
