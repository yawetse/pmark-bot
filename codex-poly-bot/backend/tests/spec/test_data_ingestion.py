"""Red-phase tests for Data Ingestion and S3 Storage."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import logging

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

    bar_params: list[dict[str, str]] = []

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
            bar_params.append(dict(request.url.params))
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
    assert bar_params[0]["start"] == "2026-05-10T18:00:00Z"
    assert bar_params[0]["end"] == "2026-06-24T18:00:00Z"
    assert bar_params[0]["limit"] == "30"


def test_req_dat_008_07_alpaca_provider_normalizes_class_share_symbols(caplog: pytest.LogCaptureFixture) -> None:
    """TST-REQ-DAT-008-07: Validates REQ-DAT-008

    Given: Alpaca symbols include class-share hyphen notation
    When: provider-backed ingestion builds batch requests
    Then: Alpaca API symbols use dot notation while dashboard candidates retain requested symbols
    """

    requested_symbols: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_symbols.append(str(request.url.params.get("symbols")))
        if request.url.path == "/v2/stocks/snapshots":
            return httpx.Response(
                200,
                json={
                    "snapshots": {
                        "BRK.B": {"latestQuote": {"t": "2026-06-24T18:00:00Z", "bp": 400, "ap": 400.2}},
                        "BF.B": {"latestQuote": {"t": "2026-06-24T18:00:10Z", "bp": 60, "ap": 60.1}},
                    },
                },
            )
        if request.url.path == "/v2/stocks/bars":
            return httpx.Response(200, json={"bars": {"BRK.B": [], "BF.B": []}})
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "ALPACA_KEY_ID": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_DATA_BASE_URL": "https://data.alpaca.test/v2",
        },
        transport=httpx.MockTransport(handler),
    )

    with caplog.at_level(logging.WARNING):
        result = fetcher.fetch(
            venue=Venue.ALPACA.value,
            config_payload={"alpaca": {"symbol_universe": ["BRK-B", "BF-B"]}},
            pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
        )

    assert result.status == "pulled"
    assert requested_symbols == ["BRK.B,BF.B", "BRK.B,BF.B"]
    assert [candidate["symbol"] for candidate in result.candidates] == ["BRK.B", "BF.B"]
    assert [candidate["requestedSymbol"] for candidate in result.candidates] == ["BRK-B", "BF-B"]
    assert "provider_symbols_normalized" in caplog.text


def test_req_dat_008_06_alpaca_provider_does_not_fallback_on_rate_limit() -> None:
    """TST-REQ-DAT-008-06: Validates REQ-DAT-008

    Given: Alpaca batch endpoints are rate limited for a large universe
    When: provider-backed ingestion runs with per-symbol fallback available
    Then: the fetcher reports the batch rate limit without issuing per-symbol quote calls
    """

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path in {"/v2/stocks/snapshots", "/v2/stocks/bars"}:
            return httpx.Response(429, json={"message": "rate limit"})
        return httpx.Response(500, json={"message": "unexpected per-symbol call"})

    symbols = [f"SYM{index}" for index in range(120)]
    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "ALPACA_KEY_ID": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_DATA_BASE_URL": "https://data.alpaca.test/v2",
            "ALPACA_SYMBOL_CHUNK_SIZE": "100",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.ALPACA.value,
        config_payload={"alpaca": {"symbol_universe": symbols}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "rate_limited"
    assert result.error_code == "provider_rate_limited"
    assert "/v2/stocks/SYM0/quotes/latest" not in paths
    assert paths.count("/v2/stocks/snapshots") == 2
    assert paths.count("/v2/stocks/bars") == 2


def test_req_dat_008_08_alpaca_provider_uses_capped_fallback_after_batch_400() -> None:
    """TST-REQ-DAT-008-08: Validates REQ-DAT-008

    Given: Alpaca batch endpoints reject a request with HTTP 400
    When: provider-backed ingestion runs with default fallback settings
    Then: capped per-symbol fallback rescues priced candidates and preserves partial status
    """

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path in {"/v2/stocks/snapshots", "/v2/stocks/bars"}:
            return httpx.Response(400, json={"message": "invalid symbol"})
        if request.url.path == "/v2/stocks/SPY/quotes/latest":
            return httpx.Response(
                200,
                json={"quote": {"t": "2026-06-24T18:00:00Z", "bp": 500, "ap": 500.2, "bs": 1, "as": 2}},
            )
        if request.url.path == "/v2/stocks/SPY/bars/latest":
            return httpx.Response(200, json={"bar": {"t": "2026-06-24T18:00:00Z", "c": 500.1, "v": 1000}})
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "ALPACA_KEY_ID": "key",
            "ALPACA_SECRET_KEY": "secret",
            "ALPACA_DATA_BASE_URL": "https://data.alpaca.test/v2",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.ALPACA.value,
        config_payload={"alpaca": {"symbol_universe": ["SPY"]}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "partial"
    assert result.error_code == "provider_http_400"
    assert result.candidates[0]["symbol"] == "SPY"
    assert result.candidates[0]["price"] == "500.1"
    assert "/v2/stocks/SPY/quotes/latest" in paths
    assert "/v2/stocks/SPY/bars/latest" in paths


def test_req_dat_008_05_polymarket_provider_fetches_active_market_order_books() -> None:
    """TST-REQ-DAT-008-05: Validates REQ-DAT-008

    Given: Polymarket US active markets and gateway order books return data
    When: provider-backed ingestion runs for Polymarket US
    Then: priced dashboard candidates include midpoint, spread, liquidity, and tradable slug metadata
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/markets":
            return httpx.Response(
                200,
                json={
                    "markets": [
                        {
                            "id": "7898",
                            "question": "Will New York win?",
                            "slug": "tec-mlb-win-2026-07-25-nym",
                            "endDate": "2026-07-25T21:00:00Z",
                            "category": "sports",
                            "active": True,
                            "closed": False,
                            "hidden": False,
                            "ep3Status": "OPEN",
                            "marketSides": [
                                {
                                    "id": "15795",
                                    "description": "Yes",
                                    "long": True,
                                    "tradable": True,
                                }
                            ],
                            "volume24hr": 1000,
                        }
                    ]
                },
            )
        if request.url.path == "/v1/markets/tec-mlb-win-2026-07-25-nym/book":
            return httpx.Response(
                200,
                json={
                    "marketData": {
                        "marketSlug": "tec-mlb-win-2026-07-25-nym",
                        "transactTime": "2026-06-24T18:00:00Z",
                        "bids": [{"px": {"value": "0.44", "currency": "USD"}, "qty": "100"}],
                        "offers": [{"px": {"value": "0.46", "currency": "USD"}, "qty": "150"}],
                    }
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GATEWAY_BASE_URL": "https://gateway.polymarket.test",
            "POLYMARKET_US_MARKET_SOURCE_LIMIT": "1",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_US.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert result.source == "polymarket us market api"
    assert result.candidates[0]["market"] == "Will New York win? - Yes"
    assert result.candidates[0]["marketSlug"] == "tec-mlb-win-2026-07-25-nym"
    assert result.candidates[0]["price"] == "0.45"
    assert result.candidates[0]["spread"] == "0.02"
    assert result.candidates[0]["liquidity"] == "250"
    assert result.candidates[0]["tokenId"] == "15795"


def test_req_dat_008_15_polymarket_us_pages_and_prefers_near_resolution_markets() -> None:
    """TST-REQ-DAT-008-15: Validates REQ-DAT-008

    Given: the first Polymarket US page has a longer-dated market than a later page
    When: provider-backed ingestion scans multiple US pages
    Then: it fetches the order book for the nearer market first
    """

    book_calls: list[str] = []

    def market(slug: str, end_date: str) -> dict:
        return {
            "id": slug,
            "question": slug,
            "slug": slug,
            "endDate": end_date,
            "category": "sports",
            "active": True,
            "closed": False,
            "hidden": False,
            "ep3Status": "OPEN",
            "marketSides": [{"id": f"{slug}-side", "description": "Yes", "long": True, "tradable": True}],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/markets":
            offset = int(request.url.params.get("offset", "0"))
            return httpx.Response(
                200,
                json={
                    "markets": [
                        market("long-market", "2026-11-06T16:20:09Z")
                        if offset == 0
                        else market("near-market", "2026-07-25T21:00:00Z")
                    ]
                },
            )
        if request.url.path.startswith("/v1/markets/") and request.url.path.endswith("/book"):
            slug = request.url.path.removeprefix("/v1/markets/").removesuffix("/book")
            book_calls.append(slug)
            return httpx.Response(
                200,
                json={
                    "marketData": {
                        "marketSlug": slug,
                        "transactTime": "2026-06-24T18:00:00Z",
                        "bids": [{"px": {"value": "0.44", "currency": "USD"}, "qty": "1000"}],
                        "offers": [{"px": {"value": "0.46", "currency": "USD"}, "qty": "1000"}],
                    }
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GATEWAY_BASE_URL": "https://gateway.polymarket.test",
            "POLYMARKET_US_MARKET_PAGE_SIZE": "1",
            "POLYMARKET_US_MARKET_SOURCE_LIMIT": "2",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_US.value,
        config_payload={"scanner": {"polymarket": {"market_data_limit": 1}}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert book_calls == ["near-market"]
    assert result.candidates[0]["marketSlug"] == "near-market"


def test_req_dat_008_12_polymarket_market_data_limit_comes_from_runtime_config() -> None:
    """TST-REQ-DAT-008-12: Validates REQ-DAT-008

    Given: the environment default only considers one Polymarket candidate
    When: runtime config raises the Polymarket market data limit
    Then: the provider requests and returns the configured candidate count
    """

    requested_limits: list[str] = []
    token_ids = ["yes-token-1", "yes-token-2", "yes-token-3"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            requested_limits.append(request.url.params.get("limit", ""))
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": f"condition-{index}",
                        "question": f"Will event {index} happen?",
                        "clobTokenIds": json.dumps([token_id]),
                        "outcomes": json.dumps(["Yes"]),
                    }
                    for index, token_id in enumerate(token_ids, start=1)
                ],
            )
        if request.url.path == "/book":
            token_id = request.url.params.get("token_id", "")
            return httpx.Response(
                200,
                json={
                    "market": token_id,
                    "asset_id": token_id,
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
            "POLYMARKET_MARKET_DATA_LIMIT": "1",
            "POLYMARKET_ORDER_BOOK_CONCURRENCY": "1",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={"scanner": {"polymarket": {"market_data_limit": 3}}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert requested_limits == ["3"]
    assert result.status == "pulled"
    assert len(result.candidates) == 3
    assert [candidate["tokenId"] for candidate in result.candidates] == token_ids


def test_req_dat_008_14_polymarket_order_books_stop_after_candidate_limit() -> None:
    """TST-REQ-DAT-008-14: Validates REQ-DAT-008

    Given: active Polymarket markets include more CLOB tokens than the runtime candidate limit
    When: provider-backed ingestion fetches order books concurrently
    Then: it stops after enough priced candidates are found instead of retaining every order book
    """

    book_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": f"condition-{index}",
                        "question": f"Will event {index} happen?",
                        "clobTokenIds": json.dumps([f"yes-token-{index}"]),
                        "outcomes": json.dumps(["Yes"]),
                    }
                    for index in range(1, 6)
                ],
            )
        if request.url.path == "/book":
            token_id = request.url.params.get("token_id", "")
            book_calls.append(token_id)
            return httpx.Response(
                200,
                json={
                    "market": token_id,
                    "asset_id": token_id,
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
            "POLYMARKET_ORDER_BOOK_CONCURRENCY": "2",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={"scanner": {"polymarket": {"market_data_limit": 2}}},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert len(result.candidates) == 2
    assert len(book_calls) == 2
    assert set(book_calls) == {"yes-token-1", "yes-token-2"}


def test_req_dat_008_13_polymarket_default_market_data_limit_is_one_hundred() -> None:
    """TST-REQ-DAT-008-13: Validates REQ-DAT-008

    Given: no runtime override is set for the Polymarket market data limit
    When: provider-backed ingestion fetches active markets
    Then: the provider requests the default 100 candidate set
    """

    requested_limits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            limit = int(request.url.params.get("limit", "0"))
            requested_limits.append(str(limit))
            return httpx.Response(
                200,
                json=[
                    {
                        "conditionId": f"condition-{index}",
                        "question": f"Will event {index} happen?",
                        "clobTokenIds": json.dumps([f"yes-token-{index}"]),
                        "outcomes": json.dumps(["Yes"]),
                    }
                    for index in range(1, limit + 1)
                ],
            )
        if request.url.path == "/book":
            token_id = request.url.params.get("token_id", "")
            return httpx.Response(
                200,
                json={
                    "market": token_id,
                    "asset_id": token_id,
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
            "POLYMARKET_ORDER_BOOK_CONCURRENCY": "1",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert requested_limits == ["100"]
    assert result.status == "pulled"
    assert len(result.candidates) == 100


def test_req_dat_008_09_polymarket_order_book_retries_after_timeout() -> None:
    """TST-REQ-DAT-008-09: Validates REQ-DAT-008

    Given: the first Polymarket CLOB order book call times out
    When: provider-backed ingestion retries the order book
    Then: the retry succeeds and the pull remains healthy
    """

    book_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal book_calls
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
            book_calls += 1
            if book_calls == 1:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(
                200,
                json={
                    "market": "condition-1",
                    "asset_id": "yes-token",
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
            "POLYMARKET_ORDER_BOOK_RETRIES": "1",
            "POLYMARKET_ORDER_BOOK_RETRY_BACKOFF_SECONDS": "0",
            "POLYMARKET_ORDER_BOOK_CONCURRENCY": "1",
        },
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )

    assert result.status == "pulled"
    assert book_calls == 2
    assert result.candidates[0]["tokenId"] == "yes-token"


def test_req_dat_008_10_polymarket_order_book_uses_stale_cache_after_timeout() -> None:
    """TST-REQ-DAT-008-10: Validates REQ-DAT-008

    Given: a prior Polymarket CLOB order book succeeded
    When: a later order book fetch times out
    Then: the provider uses the short-lived cached book and reports a degraded pull
    """

    fail_books = False

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
            if fail_books:
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(
                200,
                json={
                    "market": "condition-1",
                    "asset_id": "yes-token",
                    "timestamp": "1782324000",
                    "bids": [{"price": "0.44", "size": "100"}],
                    "asks": [{"price": "0.46", "size": "150"}],
                },
            )
        return httpx.Response(404)

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "POLYMARKET_GAMMA_BASE_URL": "https://gamma.polymarket.test",
            "POLYMARKET_CLOB_BASE_URL": "https://clob.polymarket.test",
            "POLYMARKET_ORDER_BOOK_RETRIES": "1",
            "POLYMARKET_ORDER_BOOK_RETRY_BACKOFF_SECONDS": "0",
            "POLYMARKET_ORDER_BOOK_CONCURRENCY": "1",
            "POLYMARKET_ORDER_BOOK_CACHE_TTL_SECONDS": "300",
        },
        transport=httpx.MockTransport(handler),
    )

    first = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC),
    )
    fail_books = True
    second = fetcher.fetch(
        venue=Venue.POLYMARKET_INTERNATIONAL.value,
        config_payload={},
        pulled_at=datetime(2026, 6, 24, 18, 1, tzinfo=UTC),
    )

    assert first.status == "pulled"
    assert second.status == "partial"
    assert second.error_code == "provider_http_error"
    assert second.candidates[0]["orderBookStatus"] == "stale_cache"
    assert second.candidates[0]["orderBookErrorCode"] == "provider_http_error"
