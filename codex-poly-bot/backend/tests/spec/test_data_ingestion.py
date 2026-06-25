"""Red-phase tests for Data Ingestion and S3 Storage."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json

import httpx
import pytest

from app.adapters.aws import (
    InMemoryS3StorageAdapter,
    SnapshotObject,
    build_snapshot_key,
    store_snapshot_batch,
)
from app.domain import Environment, Venue
from app.services import (
    FakeSnapshotSource,
    IngestionCheckpoint,
    IngestionService,
    check_market_data_freshness,
)
from app.services.market_data_provider import ProviderBackedMarketDataFetcher
from tests.spec.helpers import pending


def test_req_dat_001_01_enabled_venues_clock_reaches_06_00_utc_daily() -> None:
    """TST-REQ-DAT-001-01: Validates REQ-DAT-001

    Given: enabled venues and the clock reaches 06:00 UTC
    When: the daily full-ingestion scheduler fires
    Then: a full market and trade snapshot is downloaded
    """
    source = FakeSnapshotSource()
    service = IngestionService(storage=InMemoryS3StorageAdapter(), source=source)

    results = service.run_daily_full_ingestion(
        environment=Environment.DEVELOPMENT,
        enabled_venues=[Venue.POLYMARKET_US],
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
    )

    assert len(results) == 1
    assert results[0].ok
    assert results[0].snapshot_type == "raw_full"
    assert source.full_fetches == (Venue.POLYMARKET_US,)

def test_req_dat_001_02_no_venues_enabled_06_00_utc_full_ingestion() -> None:
    """TST-REQ-DAT-001-02: Validates REQ-DAT-001

    Given: no venues are enabled at 06:00 UTC
    When: full ingestion runs
    Then: no venue download starts and the skipped state is recorded
    """
    source = FakeSnapshotSource()
    service = IngestionService(storage=InMemoryS3StorageAdapter(), source=source)

    results = service.run_daily_full_ingestion(
        environment=Environment.DEVELOPMENT,
        enabled_venues=[],
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
    )

    assert results[0].status == "skipped"
    assert results[0].message == "no enabled venues"
    assert source.full_fetches == ()

def test_req_dat_002_01_existing_checkpoint_elapsed_incremental_interval_incremental_ingestion_runs() -> None:
    """TST-REQ-DAT-002-01: Validates REQ-DAT-002

    Given: an existing checkpoint and elapsed incremental interval
    When: incremental ingestion runs
    Then: only new or changed data since that checkpoint is downloaded
    """
    source = FakeSnapshotSource()
    service = IngestionService(storage=InMemoryS3StorageAdapter(), source=source)
    checkpoint = IngestionCheckpoint(
        value="checkpoint-1",
        last_success_at=datetime(2026, 5, 10, 5, 58, tzinfo=UTC),
    )

    result = service.run_incremental_if_due(
        environment=Environment.DEVELOPMENT,
        venue=Venue.POLYMARKET_US,
        checkpoint=checkpoint,
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        interval=timedelta(seconds=60),
    )

    assert result.ok
    assert result.checkpoint_before == "checkpoint-1"
    assert result.checkpoint_after == "2026-05-10T06:00:00+00:00"
    assert source.incremental_fetches == ((Venue.POLYMARKET_US, "checkpoint-1"),)

def test_req_dat_002_02_checkpoint_missing_corrupt_incremental_ingestion_runs_job_fails() -> None:
    """TST-REQ-DAT-002-02: Validates REQ-DAT-002

    Given: the checkpoint is missing or corrupt
    When: incremental ingestion runs
    Then: the job fails safely or falls back according to configured policy without advancing the checkpoint
    """
    source = FakeSnapshotSource()
    service = IngestionService(storage=InMemoryS3StorageAdapter(), source=source)

    result = service.run_incremental_if_due(
        environment=Environment.DEVELOPMENT,
        venue=Venue.POLYMARKET_US,
        checkpoint=IngestionCheckpoint(value="", last_success_at=None, corrupt=True),
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        interval=timedelta(seconds=60),
    )

    assert not result.ok
    assert result.error_code == "INVALID_CHECKPOINT"
    assert result.checkpoint_after is None
    assert source.incremental_fetches == ()

def test_req_dat_003_01_raw_full_raw_incremental_normalized_outputs_storage_writes() -> None:
    """TST-REQ-DAT-003-01: Validates REQ-DAT-003

    Given: raw full, raw incremental, and normalized outputs
    When: storage writes complete
    Then: each output category is stored in S3
    """
    adapter = InMemoryS3StorageAdapter()
    snapshots = [
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "raw_full", date(2026, 5, 10), "daily", "json", b"full"),
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "raw_incremental", date(2026, 5, 10), "loop-1", "json", b"incr"),
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "normalized", date(2026, 5, 10), "loop-1", "json", b"norm"),
    ]

    result = store_snapshot_batch(adapter, snapshots)

    assert result.fully_stored
    assert result.checkpoint_advanced
    assert set(adapter.objects) == {metadata.key for metadata in result.metadata}

def test_req_dat_003_02_s3_write_failure_one_output_category_ingestion_completes() -> None:
    """TST-REQ-DAT-003-02: Validates REQ-DAT-003

    Given: an S3 write failure for one output category
    When: ingestion completes
    Then: the job records failure and does not mark the snapshot fully stored
    """
    adapter = InMemoryS3StorageAdapter(fail_snapshot_types={"normalized"})
    snapshots = [
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "raw_full", date(2026, 5, 10), "daily", "json", b"full"),
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "normalized", date(2026, 5, 10), "daily", "json", b"norm"),
    ]

    result = store_snapshot_batch(adapter, snapshots)

    assert not result.fully_stored
    assert not result.checkpoint_advanced
    assert result.errors == ("S3 write failed for normalized",)

def test_req_dat_004_01_environment_venue_snapshot_type_utc_date_s3_object() -> None:
    """TST-REQ-DAT-004-01: Validates REQ-DAT-004

    Given: environment, venue, snapshot type, and UTC date
    When: an S3 object key is built
    Then: the path includes each partition
    """
    key = build_snapshot_key(
        environment=Environment.PRODUCTION,
        venue=Venue.ALPACA,
        snapshot_type="raw_full",
        dt=date(2026, 5, 10),
        window_id="daily",
        extension="json",
    )

    assert key == "production/alpaca/raw_full/dt=2026-05-10/daily.json"

def test_req_dat_004_02_missing_partition_value_s3_object_key_built_system() -> None:
    """TST-REQ-DAT-004-02: Validates REQ-DAT-004

    Given: a missing partition value
    When: an S3 object key is built
    Then: the system rejects the write before storing an incorrectly partitioned object
    """
    with pytest.raises(ValueError, match="snapshot_type is required"):
        build_snapshot_key(
            environment=Environment.PRODUCTION,
            venue=Venue.ALPACA,
            snapshot_type="",
            dt=date(2026, 5, 10),
            window_id="daily",
            extension="json",
        )

def test_req_dat_005_01_fresh_market_data_within_configured_threshold_live_order() -> None:
    """TST-REQ-DAT-005-01: Validates REQ-DAT-005

    Given: fresh market data within the configured threshold
    When: live order checks run
    Then: the freshness gate passes
    """
    result = check_market_data_freshness(
        observed_at=datetime(2026, 5, 10, 5, 59, 30, tzinfo=UTC),
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        threshold=timedelta(seconds=60),
    )

    assert result.ok
    assert result.age_seconds == 30

def test_req_dat_005_02_stale_market_data_beyond_configured_threshold_live_order() -> None:
    """TST-REQ-DAT-005-02: Validates REQ-DAT-005

    Given: stale market data beyond the configured threshold
    When: live order checks run
    Then: dependent live orders are blocked
    """
    result = check_market_data_freshness(
        observed_at=datetime(2026, 5, 10, 5, 58, 59, tzinfo=UTC),
        now=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        threshold=timedelta(seconds=60),
    )

    assert not result.ok
    assert result.refusal_reason == "STALE_MARKET_DATA"
    assert result.age_seconds == 61

def test_req_dat_006_01_raw_snapshot_lifecycle_rules_synthesized_infrastructure_configuration_validated() -> None:
    """TST-REQ-DAT-006-01: Validates REQ-DAT-006

    Given: raw snapshot lifecycle rules are synthesized
    When: infrastructure configuration is validated
    Then: raw snapshots have a 365-day retention policy
    """
    adapter = InMemoryS3StorageAdapter()
    metadata = adapter.put_snapshot(
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "raw_full", date(2026, 5, 10), "daily", "json", b"full")
    )

    assert metadata.lifecycle_days == 365

def test_req_dat_007_01_normalized_snapshot_lifecycle_rules_synthesized_infrastructure_configuration_validated() -> None:
    """TST-REQ-DAT-007-01: Validates REQ-DAT-007

    Given: normalized snapshot lifecycle rules are synthesized
    When: infrastructure configuration is validated
    Then: normalized snapshots have a 730-day retention policy
    """
    adapter = InMemoryS3StorageAdapter()
    metadata = adapter.put_snapshot(
        SnapshotObject(Environment.DEVELOPMENT, Venue.POLYMARKET_US, "normalized", date(2026, 5, 10), "daily", "json", b"norm")
    )

    assert metadata.lifecycle_days == 730

def test_req_dat_008_01_ingestion_job_fails_after_prior_checkpoint_retry_policy() -> None:
    """TST-REQ-DAT-008-01: Validates REQ-DAT-008

    Given: an ingestion job fails after a prior checkpoint
    When: retry policy runs
    Then: the error is recorded, the checkpoint is preserved, and retry timing follows config
    """
    adapter = InMemoryS3StorageAdapter()
    snapshot = SnapshotObject(
        Environment.DEVELOPMENT,
        Venue.POLYMARKET_US,
        "raw_incremental",
        date(2026, 5, 10),
        "loop-1",
        "json",
        b"same-payload",
    )

    first = store_snapshot_batch(adapter, [snapshot], metadata_persistence_ok=False)
    retry = store_snapshot_batch(adapter, [snapshot], metadata_persistence_ok=True)

    assert not first.checkpoint_advanced
    assert first.errors == ("metadata persistence failed",)
    assert retry.fully_stored
    assert retry.metadata[0].idempotent
    assert retry.checkpoint_advanced


def test_req_dat_008_04_alpaca_provider_fetches_latest_quote_and_bar_candidates() -> None:
    """TST-REQ-DAT-008-04: Validates REQ-DAT-008

    Given: Alpaca batch snapshot and historical bar endpoints return market data
    When: provider-backed ingestion runs for configured symbols
    Then: priced dashboard candidates include price, spread, liquidity, timestamp, and history metadata
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/stocks/snapshots":
            return httpx.Response(
                200,
                json={
                    "snapshots": {
                        "SPY": {
                            "latestQuote": {
                                "t": "2026-06-24T18:00:00Z",
                                "bp": 500,
                                "ap": 500.02,
                                "bs": 1,
                                "as": 2,
                            }
                        },
                        "QQQ": {
                            "latestQuote": {
                                "t": "2026-06-24T18:00:10Z",
                                "bp": 380,
                                "ap": 380.04,
                                "bs": 4,
                                "as": 5,
                            }
                        },
                    },
                },
            )
        if request.url.path == "/v2/stocks/bars":
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "SPY": [
                            {"t": "2026-06-23T20:00:00Z", "c": 498.25, "v": 900},
                            {"t": "2026-06-24T20:00:00Z", "c": 499.9, "v": 1000},
                        ],
                        "QQQ": [
                            {"t": "2026-06-23T20:00:00Z", "c": 379.25, "v": 800},
                            {"t": "2026-06-24T20:00:00Z", "c": 380.1, "v": 850},
                        ],
                    }
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "ALPACA_KEY_ID": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_DATA_BASE_URL": "https://data.alpaca.test/v2",
            "ALPACA_SYMBOL_CHUNK_SIZE": "100",
            "ALPACA_HISTORICAL_BAR_LIMIT": "30",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.ALPACA.value,
        config_payload={"alpaca": {"symbol_universe": ["SPY", "QQQ"]}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert result.source == "alpaca market data api"
    assert [candidate["symbol"] for candidate in result.candidates] == ["SPY", "QQQ"]
    assert result.candidates[0]["symbol"] == "SPY"
    assert result.candidates[0]["price"] == "500.01"
    assert result.candidates[0]["spread"] == "0.02"
    assert result.candidates[0]["liquidity"] == "3"
    assert result.candidates[0]["pulledAt"] == "2026-06-24T18:00:00Z"
    assert result.candidates[0]["dataSource"] == "snapshot+historical_bars"
    assert result.candidates[0]["historyBarCount"] == 2
    assert result.candidates[0]["previousClose"] == "498.25"
    assert result.candidates[1]["price"] == "380.02"


def test_req_dat_008_05_polymarket_provider_fetches_active_market_order_books() -> None:
    """TST-REQ-DAT-008-05: Validates REQ-DAT-008

    Given: Polymarket active markets and CLOB order books return data
    When: provider-backed ingestion runs for Polymarket
    Then: priced dashboard candidates include midpoint, spread, liquidity, and token metadata
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": "condition-1",
                        "question": "Will rates fall?",
                        "clobTokenIds": json.dumps(["yes-token"]),
                        "outcomes": json.dumps(["Yes"]),
                    }
                ],
            )
        if request.url.path == "/book":
            return httpx.Response(
                200,
                json={
                    "market": "condition-1",
                    "asset_id": "yes-token",
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                    "last_trade_price": "0.45",
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_US.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert result.source == "polymarket gamma and clob api"
    assert result.candidates[0]["market"] == "Will rates fall? - Yes"
    assert result.candidates[0]["price"] == "0.45"
    assert result.candidates[0]["spread"] == "0.02"
    assert result.candidates[0]["liquidity"] == "250"
    assert result.candidates[0]["tokenId"] == "yes-token"
