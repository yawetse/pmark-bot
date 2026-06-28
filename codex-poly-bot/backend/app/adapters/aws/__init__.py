"""AWS adapter contracts.

REQ: REQ-DAT-003, REQ-DAT-004, REQ-DAT-006, REQ-DAT-007,
REQ-DAT-008, REQ-WAL-003, REQ-WAL-007, REQ-NOT-001,
REQ-NOT-003, REQ-NOT-004, REQ-NOT-007
"""

from app.adapters.aws.billing import (
    AwsBillingCost,
    BillingUnavailableError,
    CostExplorerBillingAdapter,
    billing_adapter_from_env,
)
from app.adapters.aws.ses import (
    BotoSesEmailAdapter,
    EmailDeliveryResult,
    EmailMessage,
    InMemorySesEmailAdapter,
    ses_adapter_from_env,
)
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
    "AwsBillingCost",
    "BillingUnavailableError",
    "BotoSesEmailAdapter",
    "CostExplorerBillingAdapter",
    "EmailDeliveryResult",
    "EmailMessage",
    "InMemorySecretsAdapter",
    "InMemorySesEmailAdapter",
    "InMemoryS3StorageAdapter",
    "S3ObjectMetadata",
    "SecretRef",
    "SecretUnavailableError",
    "SecretValue",
    "SnapshotBatchResult",
    "SnapshotObject",
    "SnapshotStorageError",
    "billing_adapter_from_env",
    "build_snapshot_key",
    "ses_adapter_from_env",
    "store_snapshot_batch",
]
