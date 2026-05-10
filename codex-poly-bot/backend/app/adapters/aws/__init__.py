"""AWS adapter contracts.

REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
REQ-DAT-008, REQ-WAL-003, REQ-WAL-007
"""

from app.adapters.aws.secrets import (
    InMemorySecretsAdapter,
    SecretRef,
    SecretUnavailableError,
    SecretValue,
)
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
    "InMemorySecretsAdapter",
    "InMemoryS3StorageAdapter",
    "S3ObjectMetadata",
    "SecretRef",
    "SecretUnavailableError",
    "SecretValue",
    "SnapshotBatchResult",
    "SnapshotObject",
    "SnapshotStorageError",
    "build_snapshot_key",
    "store_snapshot_batch",
]
