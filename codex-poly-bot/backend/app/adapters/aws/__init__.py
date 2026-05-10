"""AWS adapter contracts.

REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
REQ-DAT-008
"""

from app.adapters.aws.s3 import (
    InMemoryS3StorageAdapter,
    S3ObjectMetadata,
    SnapshotBatchResult,
    SnapshotObject,
    SnapshotStorageError,
    build_snapshot_key,
    store_snapshot_batch,
)

__all__ = [
    "InMemoryS3StorageAdapter",
    "S3ObjectMetadata",
    "SnapshotBatchResult",
    "SnapshotObject",
    "SnapshotStorageError",
    "build_snapshot_key",
    "store_snapshot_batch",
]
