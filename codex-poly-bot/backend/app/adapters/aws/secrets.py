"""Secrets Manager adapter contract helpers.

REQ: REQ-WAL-003, REQ-WAL-007
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import Environment


class SecretUnavailableError(RuntimeError):
    """Expected secret loading failure.

    REQ: REQ-WAL-003, REQ-WAL-007
    """


@dataclass(frozen=True)
class SecretRef:
    """Reference to a credential without the secret value.

    REQ: REQ-WAL-003, REQ-WAL-007
    """

    environment: Environment
    path: str
    source: str = "aws_secrets_manager"


@dataclass(frozen=True)
class SecretValue:
    """Loaded secret value with safe display metadata.

    REQ: REQ-WAL-003, REQ-WAL-007
    """

    ref: SecretRef
    value: str
    version: int
    source: str = "aws_secrets_manager"

    @property
    def redacted_value(self) -> str:
        return "****"


class InMemorySecretsAdapter:
    """Mockable Secrets Manager adapter with explicit refresh.

    REQ: REQ-WAL-003, REQ-WAL-007
    """

    def __init__(self, *, secrets: dict[str, str]) -> None:
        self.secrets = dict(secrets)
        self.versions = {path: 1 for path in secrets}
        self.cache: dict[str, SecretValue] = {}
        self.stale_reasons: dict[str, str] = {}

    def get_secret(self, ref: SecretRef) -> SecretValue:
        """Return a secret from AWS-style storage only.

        REQ: REQ-WAL-003
        """

        self._validate_ref(ref)
        cached = self.cache.get(ref.path)
        if cached is not None:
            return cached
        value = self.secrets.get(ref.path)
        if value is None:
            raise SecretUnavailableError(f"secret not found: {ref.path}")
        result = SecretValue(
            ref=ref,
            value=value,
            version=self.versions.get(ref.path, 1),
        )
        self.cache[ref.path] = result
        return result

    def refresh_secret(self, ref: SecretRef) -> SecretValue:
        """Invalidate and reload a secret after rotation.

        REQ: REQ-WAL-007
        """

        self.invalidate(ref)
        return self.get_secret(ref)

    def invalidate(self, ref: SecretRef) -> None:
        """Remove a cached value for the next load.

        REQ: REQ-WAL-007
        """

        self.cache.pop(ref.path, None)

    def mark_stale(self, ref: SecretRef, reason: str) -> None:
        """Mark a secret reference stale without storing secret data.

        REQ: REQ-WAL-007
        """

        self.stale_reasons[ref.path] = reason
        self.invalidate(ref)

    def rotate_secret(self, path: str, value: str) -> None:
        """Update backing secret storage for refresh tests.

        REQ: REQ-WAL-007
        """

        self.secrets[path] = value
        self.versions[path] = self.versions.get(path, 1) + 1

    def _validate_ref(self, ref: SecretRef) -> None:
        if not ref.path.strip():
            raise SecretUnavailableError("secret path is required")
        if ref.source != "aws_secrets_manager":
            if ref.environment in {Environment.DEVELOPMENT, Environment.PRODUCTION}:
                raise SecretUnavailableError(
                    "local secret files are not allowed in deployed environments"
                )
            raise SecretUnavailableError("unsupported secret source")
