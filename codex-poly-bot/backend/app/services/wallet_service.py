"""Wallet and credential setup helpers.

REQ: REQ-WAL-001, REQ-WAL-002, REQ-WAL-004, REQ-WAL-005,
REQ-WAL-006
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain import Environment, ModelProvider, Venue, supported_polymarket_venues
from app.venues.polymarket import VenueCallResult


@dataclass(frozen=True)
class CredentialTarget:
    """Target used to derive a non-secret credential reference.

    REQ: REQ-WAL-001
    """

    environment: Environment
    venue: Venue
    model_provider: ModelProvider
    credential_type: str = "wallet"


@dataclass(frozen=True)
class WalletGenerationRequest:
    """Polymarket wallet generation request.

    REQ: REQ-WAL-002
    """

    environment: Environment
    venue: Venue
    model_provider: ModelProvider


@dataclass(frozen=True)
class WalletGenerationResult:
    """Safe wallet generation result without private key material."""

    generated: bool
    public_identifier: str | None = None
    secret_ref: str | None = None
    refusal_reason: str | None = None


@dataclass(frozen=True)
class LocalCredentialResult:
    """Local `.env` credential loading result."""

    ok: bool
    env_var: str
    source: str = "local_env"
    value: str | None = None
    refusal_reason: str | None = None


@dataclass(frozen=True)
class CredentialStatus:
    """Safe credential status for live gates and dashboard views.

    REQ: REQ-WAL-005, REQ-WAL-006
    """

    credential_type: str
    secret_ref: str
    present: bool
    public_identifier: str | None = None
    stale_reason: str | None = None
    secret_value: str | None = field(default=None, repr=False, compare=False)

    def dashboard_payload(self) -> dict[str, Any]:
        """Return safe credential metadata without private secret values.

        REQ: REQ-WAL-005
        """

        return {
            "credential_type": self.credential_type,
            "secret_ref": self.secret_ref,
            "present": self.present,
            "public_identifier": self.public_identifier,
            "stale_reason": self.stale_reason,
        }


def resolve_credential_ref(target: CredentialTarget) -> str:
    """Build separate credential references by environment, venue, and provider.

    REQ: REQ-WAL-001
    """

    credential_type = target.credential_type.strip()
    if not credential_type:
        raise ValueError("credential_type is required")
    return (
        f"/codex-poly-bot/{target.environment.value}/{target.venue.value}/"
        f"{target.model_provider.value}/{credential_type}"
    )


def validate_unique_credential_refs(named_refs: dict[str, str]) -> VenueCallResult:
    """Reject duplicate live credential references when sharing is disallowed.

    REQ: REQ-WAL-001
    """

    refs = [ref for ref in named_refs.values() if ref]
    if len(refs) != len(set(refs)):
        return VenueCallResult(
            ok=False,
            refusal_reasons=("duplicate credential reference",),
            payload={"credential_refs": tuple(refs)},
        )
    return VenueCallResult(ok=True, payload={"credential_refs": tuple(refs)})


def generate_polymarket_wallet(request: WalletGenerationRequest) -> WalletGenerationResult:
    """Generate safe Polymarket wallet metadata for CLI output.

    REQ: REQ-WAL-002
    """

    if request.venue not in supported_polymarket_venues():
        return WalletGenerationResult(
            generated=False,
            refusal_reason="wallet generation supports Polymarket only",
        )
    target = CredentialTarget(
        environment=request.environment,
        venue=request.venue,
        model_provider=request.model_provider,
        credential_type="wallet",
    )
    return WalletGenerationResult(
        generated=True,
        public_identifier=f"pm-{request.environment.value}-{request.model_provider.value}",
        secret_ref=resolve_credential_ref(target),
    )


def load_local_credential(
    *,
    environment: Environment,
    env_var: str,
    env_values: dict[str, str],
) -> LocalCredentialResult:
    """Load local development credentials from gitignored environment values.

    REQ: REQ-WAL-004
    """

    if environment != Environment.LOCAL:
        return LocalCredentialResult(
            ok=False,
            env_var=env_var,
            refusal_reason="local credentials are allowed only in local environment",
        )
    value = env_values.get(env_var, "").strip()
    if not value:
        return LocalCredentialResult(
            ok=False,
            env_var=env_var,
            refusal_reason="missing local credential",
        )
    return LocalCredentialResult(ok=True, env_var=env_var, value=value)


def build_credential_status(
    *,
    secret_ref: str,
    public_identifier: str | None,
    present: bool,
    credential_type: str = "credential",
    secret_value: str | None = None,
) -> CredentialStatus:
    """Create dashboard-safe credential status metadata.

    REQ: REQ-WAL-005
    """

    return CredentialStatus(
        credential_type=credential_type,
        secret_ref=secret_ref,
        present=present,
        public_identifier=public_identifier,
        secret_value=secret_value,
    )


def check_required_credentials(statuses: tuple[CredentialStatus, ...]) -> VenueCallResult:
    """Gate live orders on required wallet or API credential presence.

    REQ: REQ-WAL-006
    """

    missing_refs = tuple(status.secret_ref for status in statuses if not status.present)
    if missing_refs:
        return VenueCallResult(
            ok=False,
            refusal_reasons=("CREDENTIAL_MISSING",),
            payload={"missing_refs": missing_refs},
        )
    return VenueCallResult(ok=True, payload={"checked_refs": tuple(s.secret_ref for s in statuses)})
