"""S3 snapshot storage contract helpers.

REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
REQ-DAT-008
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256

from app.domain import Environment, Venue


class SnapshotStorageError(RuntimeError):
    """Expected snapshot storage failure.

    REQ: REQ-DAT-003, REQ-DAT-008
    """


@dataclass(frozen=True)
class SnapshotObject:
    """Snapshot bytes and deterministic key parts.

    REQ: REQ-DAT-003, REQ-DAT-004
    """

    environment: Environment
    venue: Venue
    snapshot_type: str
    dt: date
    window_id: str
    extension: str
    payload: bytes

    @property
    def key(self) -> str:
        return build_snapshot_key(
            environment=self.environment,
            venue=self.venue,
            snapshot_type=self.snapshot_type,
            dt=self.dt,
            window_id=self.window_id,
            extension=self.extension,
        )

    @property
    def checksum_sha256(self) -> str:
        return sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class S3ObjectMetadata:
    """Stored snapshot object metadata.

    REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
    REQ-DAT-008
    """

    key: str
    checksum_sha256: str
    lifecycle_days: int
    idempotent: bool = False
    conflict: bool = False


@dataclass(frozen=True)
class SnapshotBatchResult:
    """Batch snapshot storage result."""

    fully_stored: bool
    checkpoint_advanced: bool
    metadata: tuple[S3ObjectMetadata, ...]
    errors: tuple[str, ...] = ()


def _value(value: Environment | Venue | str) -> str:
    return value.value if isinstance(value, (Environment, Venue)) else str(value)


def _require(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if "/" in normalized:
        raise ValueError(f"{field_name} cannot contain '/'")
    return normalized


def build_snapshot_key(
    *,
    environment: Environment | str,
    venue: Venue | str,
    snapshot_type: str,
    dt: date,
    window_id: str,
    extension: str,
) -> str:
    """Build deterministic S3 keys with required partitions.

    REQ: REQ-DAT-004, REQ-DAT-008
    """

    environment_part = _require(_value(environment), "environment")
    venue_part = _require(_value(venue), "venue")
    snapshot_type_part = _require(snapshot_type, "snapshot_type")
    window_part = _require(window_id, "window_id")
    extension_part = _require(extension.lstrip("."), "extension")
    return (
        f"{environment_part}/{venue_part}/{snapshot_type_part}/"
        f"dt={dt.isoformat()}/{window_part}.{extension_part}"
    )


def lifecycle_days(snapshot_type: str) -> int:
    """Return retention days for raw or normalized snapshots.

    REQ: REQ-DAT-006, REQ-DAT-007
    """

    return 730 if snapshot_type == "normalized" else 365


class InMemoryS3StorageAdapter:
    """Mockable S3 storage adapter with checksum idempotency.

    REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
    REQ-DAT-008
    """

    def __init__(self, *, fail_snapshot_types: set[str] | None = None) -> None:
        self.fail_snapshot_types = fail_snapshot_types or set()
        self.objects: dict[str, bytes] = {}
        self.metadata_by_key: dict[str, S3ObjectMetadata] = {}

    def put_snapshot(self, snapshot: SnapshotObject) -> S3ObjectMetadata:
        """Store a snapshot with deterministic key and checksum handling.

        REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-008
        """

        if snapshot.snapshot_type in self.fail_snapshot_types:
            raise SnapshotStorageError(f"S3 write failed for {snapshot.snapshot_type}")
        key = snapshot.key
        checksum = snapshot.checksum_sha256
        existing = self.metadata_by_key.get(key)
        if existing is not None:
            if existing.checksum_sha256 == checksum:
                metadata = S3ObjectMetadata(
                    key=key,
                    checksum_sha256=checksum,
                    lifecycle_days=existing.lifecycle_days,
                    idempotent=True,
                )
                self.metadata_by_key[key] = metadata
                return metadata
            metadata = S3ObjectMetadata(
                key=key,
                checksum_sha256=checksum,
                lifecycle_days=lifecycle_days(snapshot.snapshot_type),
                conflict=True,
            )
            self.metadata_by_key[key] = metadata
            return metadata

        metadata = S3ObjectMetadata(
            key=key,
            checksum_sha256=checksum,
            lifecycle_days=lifecycle_days(snapshot.snapshot_type),
        )
        self.objects[key] = snapshot.payload
        self.metadata_by_key[key] = metadata
        return metadata


def store_snapshot_batch(
    adapter: InMemoryS3StorageAdapter,
    snapshots: list[SnapshotObject],
    *,
    metadata_persistence_ok: bool = True,
) -> SnapshotBatchResult:
    """Store related snapshots and preserve checkpoints on partial failure.

    REQ: REQ-DAT-003, REQ-DAT-008
    """

    metadata: list[S3ObjectMetadata] = []
    errors: list[str] = []
    for snapshot in snapshots:
        try:
            result = adapter.put_snapshot(snapshot)
        except SnapshotStorageError as exc:
            errors.append(str(exc))
            continue
        if result.conflict:
            errors.append(f"snapshot checksum conflict for {result.key}")
        metadata.append(result)

    if not metadata_persistence_ok and not errors:
        errors.append("metadata persistence failed")

    fully_stored = len(metadata) == len(snapshots) and not errors
    return SnapshotBatchResult(
        fully_stored=fully_stored,
        checkpoint_advanced=fully_stored,
        metadata=tuple(metadata),
        errors=tuple(errors),
    )
