"""Ingestion scheduler and market-data freshness helpers.

REQ: REQ-DAT-001, REQ-DAT-002, REQ-DAT-005, REQ-DAT-008
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.adapters.aws import InMemoryS3StorageAdapter, SnapshotObject, store_snapshot_batch
from app.domain import Environment, Venue


@dataclass(frozen=True)
class IngestionCheckpoint:
    """Last successful ingestion boundary.

    REQ: REQ-DAT-002, REQ-DAT-008
    """

    value: str
    last_success_at: datetime | None
    corrupt: bool = False


@dataclass(frozen=True)
class IngestionRunResult:
    """Worker-visible ingestion result.

    REQ: REQ-DAT-001, REQ-DAT-002, REQ-DAT-008
    """

    ok: bool
    status: str
    environment: Environment
    venue: Venue | None
    snapshot_type: str
    run_id: str
    object_keys: tuple[str, ...] = ()
    checkpoint_before: str | None = None
    checkpoint_after: str | None = None
    retry_state: str | None = None
    error_code: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class DataFreshnessStatus:
    """Freshness gate result for market data.

    REQ: REQ-DAT-005
    """

    ok: bool
    age_seconds: int | None
    threshold_seconds: int
    refusal_reason: str | None = None


@dataclass
class FakeSnapshotSource:
    """Fake venue snapshot source used by spec tests.

    REQ: REQ-DAT-001, REQ-DAT-002
    """

    full_payload: bytes = b"full-snapshot"
    incremental_payload: bytes = b"incremental-snapshot"
    full_fetches: tuple[Venue, ...] = field(default_factory=tuple)
    incremental_fetches: tuple[tuple[Venue, str], ...] = field(default_factory=tuple)

    def fetch_full_snapshot(self, venue: Venue) -> bytes:
        """Record and return a full snapshot payload.

        REQ: REQ-DAT-001
        """

        self.full_fetches = (*self.full_fetches, venue)
        return self.full_payload

    def fetch_incremental_snapshot(self, venue: Venue, checkpoint: str) -> bytes:
        """Record and return an incremental snapshot payload.

        REQ: REQ-DAT-002
        """

        self.incremental_fetches = (*self.incremental_fetches, (venue, checkpoint))
        return self.incremental_payload


class IngestionService:
    """Run full and incremental ingestion against injected adapters.

    REQ: REQ-DAT-001, REQ-DAT-002, REQ-DAT-008
    """

    def __init__(self, *, storage: InMemoryS3StorageAdapter, source: FakeSnapshotSource) -> None:
        self.storage = storage
        self.source = source

    def run_daily_full_ingestion(
        self,
        *,
        environment: Environment,
        enabled_venues: list[Venue],
        now: datetime,
    ) -> list[IngestionRunResult]:
        """Run daily full snapshots at 06:00 UTC for enabled venues.

        REQ: REQ-DAT-001
        """

        if now.hour != 6 or now.minute != 0:
            return [
                IngestionRunResult(
                    ok=True,
                    status="skipped",
                    environment=environment,
                    venue=None,
                    snapshot_type="raw_full",
                    run_id=now.isoformat(),
                    message="not scheduled",
                )
            ]
        if not enabled_venues:
            return [
                IngestionRunResult(
                    ok=True,
                    status="skipped",
                    environment=environment,
                    venue=None,
                    snapshot_type="raw_full",
                    run_id=now.isoformat(),
                    message="no enabled venues",
                )
            ]

        results: list[IngestionRunResult] = []
        for venue in enabled_venues:
            payload = self.source.fetch_full_snapshot(venue)
            snapshot = SnapshotObject(
                environment,
                venue,
                "raw_full",
                now.date(),
                "daily",
                "json",
                payload,
            )
            stored = store_snapshot_batch(self.storage, [snapshot])
            results.append(
                IngestionRunResult(
                    ok=stored.fully_stored,
                    status="stored" if stored.fully_stored else "failed",
                    environment=environment,
                    venue=venue,
                    snapshot_type="raw_full",
                    run_id=now.isoformat(),
                    object_keys=tuple(metadata.key for metadata in stored.metadata),
                    checkpoint_after=now.isoformat() if stored.fully_stored else None,
                    error_code=None if stored.fully_stored else "SNAPSHOT_STORE_FAILED",
                    message="; ".join(stored.errors) if stored.errors else None,
                )
            )
        return results

    def run_incremental_if_due(
        self,
        *,
        environment: Environment,
        venue: Venue,
        checkpoint: IngestionCheckpoint,
        now: datetime,
        interval: timedelta,
    ) -> IngestionRunResult:
        """Run incremental snapshots only from a valid due checkpoint.

        REQ: REQ-DAT-002, REQ-DAT-008
        """

        if checkpoint.corrupt or not checkpoint.value or checkpoint.last_success_at is None:
            return IngestionRunResult(
                ok=False,
                status="failed",
                environment=environment,
                venue=venue,
                snapshot_type="raw_incremental",
                run_id=now.isoformat(),
                checkpoint_before=checkpoint.value or None,
                error_code="INVALID_CHECKPOINT",
                retry_state="preserve_checkpoint",
            )
        if now - checkpoint.last_success_at < interval:
            return IngestionRunResult(
                ok=True,
                status="skipped",
                environment=environment,
                venue=venue,
                snapshot_type="raw_incremental",
                run_id=now.isoformat(),
                checkpoint_before=checkpoint.value,
                checkpoint_after=checkpoint.value,
                message="interval not elapsed",
            )

        payload = self.source.fetch_incremental_snapshot(venue, checkpoint.value)
        snapshot = SnapshotObject(
            environment,
            venue,
            "raw_incremental",
            now.date(),
            now.isoformat(),
            "json",
            payload,
        )
        stored = store_snapshot_batch(self.storage, [snapshot])
        return IngestionRunResult(
            ok=stored.fully_stored,
            status="stored" if stored.fully_stored else "failed",
            environment=environment,
            venue=venue,
            snapshot_type="raw_incremental",
            run_id=now.isoformat(),
            object_keys=tuple(metadata.key for metadata in stored.metadata),
            checkpoint_before=checkpoint.value,
            checkpoint_after=now.isoformat() if stored.fully_stored else None,
            retry_state=None if stored.fully_stored else "preserve_checkpoint",
            error_code=None if stored.fully_stored else "SNAPSHOT_STORE_FAILED",
            message="; ".join(stored.errors) if stored.errors else None,
        )


def check_market_data_freshness(
    *,
    observed_at: datetime | None,
    now: datetime,
    threshold: timedelta,
) -> DataFreshnessStatus:
    """Return stale-market-data refusal status for live order gates.

    REQ: REQ-DAT-005
    """

    threshold_seconds = int(threshold.total_seconds())
    if observed_at is None:
        return DataFreshnessStatus(
            ok=False,
            age_seconds=None,
            threshold_seconds=threshold_seconds,
            refusal_reason="STALE_MARKET_DATA",
        )
    age_seconds = int((now - observed_at).total_seconds())
    if age_seconds > threshold_seconds:
        return DataFreshnessStatus(
            ok=False,
            age_seconds=age_seconds,
            threshold_seconds=threshold_seconds,
            refusal_reason="STALE_MARKET_DATA",
        )
    return DataFreshnessStatus(
        ok=True,
        age_seconds=age_seconds,
        threshold_seconds=threshold_seconds,
    )
