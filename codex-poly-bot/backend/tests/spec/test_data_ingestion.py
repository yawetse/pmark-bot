"""Red-phase tests for Data Ingestion and S3 Storage."""

from __future__ import annotations

from datetime import date

import pytest

from app.adapters.aws import (
    InMemoryS3StorageAdapter,
    SnapshotObject,
    build_snapshot_key,
    store_snapshot_batch,
)
from app.domain import Environment, Venue
from tests.spec.helpers import pending


def test_req_dat_001_01_enabled_venues_clock_reaches_06_00_utc_daily() -> None:
    """TST-REQ-DAT-001-01: Validates REQ-DAT-001

    Given: enabled venues and the clock reaches 06:00 UTC
    When: the daily full-ingestion scheduler fires
    Then: a full market and trade snapshot is downloaded
    """
    pending("TST-REQ-DAT-001-01", "REQ-DAT-001")

def test_req_dat_001_02_no_venues_enabled_06_00_utc_full_ingestion() -> None:
    """TST-REQ-DAT-001-02: Validates REQ-DAT-001

    Given: no venues are enabled at 06:00 UTC
    When: full ingestion runs
    Then: no venue download starts and the skipped state is recorded
    """
    pending("TST-REQ-DAT-001-02", "REQ-DAT-001")

def test_req_dat_002_01_existing_checkpoint_elapsed_incremental_interval_incremental_ingestion_runs() -> None:
    """TST-REQ-DAT-002-01: Validates REQ-DAT-002

    Given: an existing checkpoint and elapsed incremental interval
    When: incremental ingestion runs
    Then: only new or changed data since that checkpoint is downloaded
    """
    pending("TST-REQ-DAT-002-01", "REQ-DAT-002")

def test_req_dat_002_02_checkpoint_missing_corrupt_incremental_ingestion_runs_job_fails() -> None:
    """TST-REQ-DAT-002-02: Validates REQ-DAT-002

    Given: the checkpoint is missing or corrupt
    When: incremental ingestion runs
    Then: the job fails safely or falls back according to configured policy without advancing the checkpoint
    """
    pending("TST-REQ-DAT-002-02", "REQ-DAT-002")

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
    pending("TST-REQ-DAT-005-01", "REQ-DAT-005")

def test_req_dat_005_02_stale_market_data_beyond_configured_threshold_live_order() -> None:
    """TST-REQ-DAT-005-02: Validates REQ-DAT-005

    Given: stale market data beyond the configured threshold
    When: live order checks run
    Then: dependent live orders are blocked
    """
    pending("TST-REQ-DAT-005-02", "REQ-DAT-005")

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
