"""Red-phase tests for Wallet and Secrets Management."""

from __future__ import annotations

import pytest

from app.adapters.aws import InMemorySecretsAdapter, SecretRef, SecretUnavailableError
from app.domain import Environment, ModelProvider, Venue
from app.services import (
    CredentialStatus,
    CredentialTarget,
    WalletGenerationRequest,
    build_credential_status,
    check_required_credentials,
    generate_polymarket_wallet,
    load_local_credential,
    resolve_credential_ref,
    validate_unique_credential_refs,
)
from tests.spec.helpers import pending


def test_req_wal_001_01_environment_venue_model_provider_combinations_credential_references_resolved() -> None:
    """TST-REQ-WAL-001-01: Validates REQ-WAL-001

    Given: environment, venue, and model provider combinations
    When: credential references are resolved
    Then: each combination can use separate wallet or brokerage credentials
    """
    refs = {
        resolve_credential_ref(CredentialTarget(Environment.DEVELOPMENT, Venue.POLYMARKET_US, ModelProvider.OPENAI)),
        resolve_credential_ref(CredentialTarget(Environment.DEVELOPMENT, Venue.POLYMARKET_US, ModelProvider.CLAUDE)),
        resolve_credential_ref(CredentialTarget(Environment.PRODUCTION, Venue.ALPACA, ModelProvider.OPENAI, "api-key")),
        resolve_credential_ref(CredentialTarget(Environment.PRODUCTION, Venue.ALPACA, ModelProvider.CLAUDE, "api-key")),
    }

    assert refs == {
        "/codex-poly-bot/development/polymarket_us/openai/wallet",
        "/codex-poly-bot/development/polymarket_us/claude/wallet",
        "/codex-poly-bot/production/alpaca/openai/api-key",
        "/codex-poly-bot/production/alpaca/claude/api-key",
    }

def test_req_wal_001_02_two_combinations_resolve_same_disallowed_credential_reference_live() -> None:
    """TST-REQ-WAL-001-02: Validates REQ-WAL-001

    Given: two combinations resolve to the same disallowed credential reference
    When: live checks run
    Then: the duplicate is rejected
    """
    result = validate_unique_credential_refs(
        {
            "openai": "/codex-poly-bot/production/alpaca/shared/api-key",
            "claude": "/codex-poly-bot/production/alpaca/shared/api-key",
        }
    )

    assert not result.ok
    assert result.refusal_reason == "duplicate credential reference"

def test_req_wal_002_01_wallet_generation_cli_inputs_environment_venue_provider_command() -> None:
    """TST-REQ-WAL-002-01: Validates REQ-WAL-002

    Given: wallet-generation CLI inputs for environment, venue, and provider
    When: the command runs
    Then: wallet material is generated for that target
    """
    result = generate_polymarket_wallet(
        WalletGenerationRequest(
            environment=Environment.DEVELOPMENT,
            venue=Venue.POLYMARKET_US,
            model_provider=ModelProvider.OPENAI,
        )
    )

    assert result.generated
    assert result.public_identifier == "pm-development-openai"
    assert result.secret_ref == "/codex-poly-bot/development/polymarket_us/openai/wallet"
    assert not hasattr(result, "private_key")

def test_req_wal_002_02_missing_unsupported_cli_inputs_wallet_generation_runs_no() -> None:
    """TST-REQ-WAL-002-02: Validates REQ-WAL-002

    Given: missing or unsupported CLI inputs
    When: wallet generation runs
    Then: no wallet material is produced and validation errors are returned
    """
    result = generate_polymarket_wallet(
        WalletGenerationRequest(
            environment=Environment.DEVELOPMENT,
            venue=Venue.ALPACA,
            model_provider=ModelProvider.OPENAI,
        )
    )

    assert not result.generated
    assert result.refusal_reason == "wallet generation supports Polymarket only"

def test_req_wal_003_01_deployed_environment_settings_private_keys_api_credentials_requested() -> None:
    """TST-REQ-WAL-003-01: Validates REQ-WAL-003

    Given: deployed environment settings
    When: private keys and API credentials are requested
    Then: they are read only from AWS Secrets Manager
    """
    adapter = InMemorySecretsAdapter(
        secrets={"/codex-poly-bot/production/polymarket/openai/wallet": "wallet-secret"}
    )

    result = adapter.get_secret(
        SecretRef(
            environment=Environment.PRODUCTION,
            path="/codex-poly-bot/production/polymarket/openai/wallet",
            source="aws_secrets_manager",
        )
    )

    assert result.value == "wallet-secret"
    assert result.source == "aws_secrets_manager"
    assert result.redacted_value == "****"

def test_req_wal_003_02_deployed_environment_settings_local_secret_file_path_credential() -> None:
    """TST-REQ-WAL-003-02: Validates REQ-WAL-003

    Given: deployed environment settings and a local secret file path
    When: credential loading runs
    Then: local secret loading is rejected
    """
    adapter = InMemorySecretsAdapter(secrets={})

    with pytest.raises(SecretUnavailableError, match="local secret files are not allowed"):
        adapter.get_secret(
            SecretRef(
                environment=Environment.PRODUCTION,
                path=".env.production",
                source="local_file",
            )
        )

def test_req_wal_004_01_local_development_settings_gitignored_env_values_credential_loading() -> None:
    """TST-REQ-WAL-004-01: Validates REQ-WAL-004

    Given: local development settings and gitignored `.env` values
    When: credential loading runs
    Then: private keys and API credentials are read from local environment values
    """
    result = load_local_credential(
        environment=Environment.LOCAL,
        env_var="POLYMARKET_OPENAI_WALLET",
        env_values={"POLYMARKET_OPENAI_WALLET": "local-wallet"},
    )

    assert result.ok
    assert result.value == "local-wallet"
    assert result.source == "local_env"

def test_req_wal_004_02_local_development_settings_missing_env_values_live_checks() -> None:
    """TST-REQ-WAL-004-02: Validates REQ-WAL-004

    Given: local development settings with missing `.env` values
    When: live checks run
    Then: orders requiring those credentials are refused
    """
    result = load_local_credential(
        environment=Environment.LOCAL,
        env_var="POLYMARKET_OPENAI_WALLET",
        env_values={},
    )

    assert not result.ok
    assert result.refusal_reason == "missing local credential"

def test_req_wal_005_01_wallet_credential_metadata_dashboard_status_rendered_public_identifiers() -> None:
    """TST-REQ-WAL-005-01: Validates REQ-WAL-005

    Given: wallet and credential metadata
    When: dashboard status is rendered
    Then: public identifiers and health are shown
    """
    status = build_credential_status(
        secret_ref="/codex-poly-bot/development/polymarket_us/openai/wallet",
        public_identifier="pm-development-openai",
        present=True,
    )

    payload = status.dashboard_payload()

    assert payload["public_identifier"] == "pm-development-openai"
    assert payload["secret_ref"].endswith("/wallet")
    assert payload["present"] is True

def test_req_wal_005_02_private_keys_api_secrets_present_in_secret_storage() -> None:
    """TST-REQ-WAL-005-02: Validates REQ-WAL-005

    Given: private keys or API secrets are present in secret storage
    When: dashboard status is rendered
    Then: secret values are never returned
    """
    status = build_credential_status(
        secret_ref="/codex-poly-bot/production/alpaca/openai/api-key",
        public_identifier="alpaca-openai-prod-live",
        present=True,
        secret_value="do-not-render",
    )

    payload = status.dashboard_payload()

    assert "secret_value" not in payload
    assert "do-not-render" not in str(payload)

def test_req_wal_006_01_all_required_wallet_brokerage_api_credentials_exist_live() -> None:
    """TST-REQ-WAL-006-01: Validates REQ-WAL-006

    Given: all required wallet, brokerage, and API credentials exist
    When: live order checks run
    Then: the credential gate passes
    """
    result = check_required_credentials(
        (
            CredentialStatus("wallet", "/codex-poly-bot/prod/polymarket/openai/wallet", True),
            CredentialStatus("api-key", "/codex-poly-bot/prod/alpaca/openai/api-key", True),
        )
    )

    assert result.ok

def test_req_wal_006_02_any_required_secret_credential_missing_live_order_checks() -> None:
    """TST-REQ-WAL-006-02: Validates REQ-WAL-006

    Given: any required secret or credential is missing
    When: live order checks run
    Then: the order is refused and the missing credential reason is recorded
    """
    result = check_required_credentials(
        (
            CredentialStatus("wallet", "/codex-poly-bot/prod/polymarket/openai/wallet", True),
            CredentialStatus("api-key", "/codex-poly-bot/prod/alpaca/openai/api-key", False),
        )
    )

    assert not result.ok
    assert result.refusal_reason == "CREDENTIAL_MISSING"
    assert result.payload["missing_refs"] == ("/codex-poly-bot/prod/alpaca/openai/api-key",)

def test_req_wal_007_01_credentials_rotated_in_configured_store_next_credential_refresh() -> None:
    """TST-REQ-WAL-007-01: Validates REQ-WAL-007

    Given: credentials are rotated in the configured store
    When: the next credential refresh runs
    Then: updated secrets are used without redeploy
    """
    ref = SecretRef(
        environment=Environment.PRODUCTION,
        path="/codex-poly-bot/production/alpaca/openai/api-key",
        source="aws_secrets_manager",
    )
    adapter = InMemorySecretsAdapter(secrets={ref.path: "initial-key"})

    initial = adapter.get_secret(ref)
    adapter.rotate_secret(ref.path, "rotated-key")
    refreshed = adapter.refresh_secret(ref)

    assert initial.value == "initial-key"
    assert refreshed.value == "rotated-key"
    assert refreshed.version != initial.version
