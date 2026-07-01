"""Database schema and repository layer.

REQ: REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005,
REQ-DB-006, REQ-DB-007, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018,
REQ-EXE-016, REQ-OBS-003, REQ-OBS-004
"""

from app.db.repositories import (
    AlpacaAccountRegistrationResult,
    AlpacaReconciliationResult,
    AlpacaReconciliationSnapshot,
    DatabaseState,
    OrderEventHandlingResult,
    PersistenceGate,
    PersistenceUnavailableError,
    RepositoryRegistry,
    SHARED_CONFIG_USERNAME,
    SchemaViolationError,
    UnitOfWork,
    live_order_persistence_gate,
    normalize_config_username,
)
from app.db.session import PersistenceConfigurationError, create_session_factory
from app.db.schema import (
    MODEL_SCHEMAS,
    REQUIRED_SCHEMAS,
    SHARED_SCHEMA,
    MigrationPlan,
    RetentionPolicy,
    migration_plan,
    provider_schema,
    retention_policy,
    run_migrations,
)

__all__ = [
    "AlpacaAccountRegistrationResult",
    "AlpacaReconciliationResult",
    "AlpacaReconciliationSnapshot",
    "DatabaseState",
    "MODEL_SCHEMAS",
    "MigrationPlan",
    "OrderEventHandlingResult",
    "PersistenceConfigurationError",
    "PersistenceGate",
    "PersistenceUnavailableError",
    "REQUIRED_SCHEMAS",
    "RepositoryRegistry",
    "RetentionPolicy",
    "SHARED_SCHEMA",
    "SHARED_CONFIG_USERNAME",
    "SchemaViolationError",
    "UnitOfWork",
    "create_session_factory",
    "live_order_persistence_gate",
    "migration_plan",
    "normalize_config_username",
    "provider_schema",
    "retention_policy",
    "run_migrations",
]
