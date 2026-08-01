"""Tests for the deployed recurring-funding release guardrail verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.services.auth_service import AuthService


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify-funding-release.py"


def _script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_funding_release", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPLICATION_DOMAIN_NAME", "example.test")
    monkeypatch.setenv("BACKEND_TOKEN_SIGNING_SECRET", "test-signing-secret")
    monkeypatch.setenv("CERTIFICATE_ARN", "arn:aws:acm:us-east-1:123:certificate/test")
    monkeypatch.setenv("SES_IDENTITY_EMAIL", "alerts@example.test")
    monkeypatch.setenv("DEPLOY_ENVIRONMENT", "development")
    monkeypatch.setenv("RELEASE_START_MS", "1785546000000")
    monkeypatch.setenv("RUNTIME_CONFIG_USERNAME", "yaw")


def test_release_verifier_mints_a_backend_compatible_token() -> None:
    module = _script_module()

    token = module._backend_token("yaw", "test-signing-secret")
    access = AuthService(
        allowed_usernames={"yaw"},
        signing_secret="test-signing-secret",
    ).authorize_request(token)

    assert access.authorized
    assert access.username == "yaw"


def test_release_verifier_uses_the_single_allowed_user_when_runtime_owner_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUNTIME_CONFIG_USERNAME", raising=False)
    monkeypatch.setenv("DASHBOARD_ALLOWED_USERS", "yawetse")
    module = _script_module()

    assert module._runtime_username() == "yawetse"


def test_release_verifier_requires_safe_readback_and_zero_broker_posts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _script_module()
    _safe_environment(monkeypatch)

    def get_json(url: str, **_: object) -> dict[str, object]:
        if url.endswith("/health"):
            return {"status": "ok"}
        return {
            "environment": "development",
            "directTransferReadiness": {
                "enabled": False,
                "maxTransferUsd": "0.00",
                "maxMonthlyTransferUsd": "0.00",
            },
        }

    monkeypatch.setattr(module, "_get_json", get_json)
    monkeypatch.setattr(
        module,
        "_release_asset_status",
        lambda *_: {
            "sesIdentityVerified": True,
            "cloudFormationStatus": "UPDATE_COMPLETE",
            "acmCertificateBinding": "STACK_OUTPUT_MATCH",
            "tlsCertificateStatus": "VALID",
        },
    )
    monkeypatch.setattr(module, "_broker_post_count", lambda *_: 0)

    assert module.main() == 0
    output = capsys.readouterr().out
    assert '"brokerPostEvents": 0' in output
    assert '"sesIdentityVerified": true' in output
    assert '"acmCertificateBinding": "STACK_OUTPUT_MATCH"' in output
    assert '"tlsCertificateStatus": "VALID"' in output
    assert '"realTransferSmokeTest": "not-performed"' in output


@pytest.mark.parametrize(
    ("readiness", "broker_posts"),
    [
        (
            {
                "enabled": True,
                "maxTransferUsd": "1.00",
                "maxMonthlyTransferUsd": "1.00",
            },
            0,
        ),
        (
            {
                "enabled": False,
                "maxTransferUsd": "0.00",
                "maxMonthlyTransferUsd": "0.00",
            },
            1,
        ),
    ],
)
def test_release_verifier_blocks_unsafe_readback_or_broker_post_events(
    monkeypatch: pytest.MonkeyPatch,
    readiness: dict[str, object],
    broker_posts: int,
) -> None:
    module = _script_module()
    _safe_environment(monkeypatch)

    def get_json(url: str, **_: object) -> dict[str, object]:
        if url.endswith("/health"):
            return {"status": "ok"}
        return {
            "environment": "development",
            "directTransferReadiness": readiness,
        }

    monkeypatch.setattr(module, "_get_json", get_json)
    monkeypatch.setattr(
        module,
        "_release_asset_status",
        lambda *_: {
            "sesIdentityVerified": True,
            "cloudFormationStatus": "UPDATE_COMPLETE",
            "acmCertificateBinding": "STACK_OUTPUT_MATCH",
            "tlsCertificateStatus": "VALID",
        },
    )
    monkeypatch.setattr(module, "_broker_post_count", lambda *_: broker_posts)

    with pytest.raises(RuntimeError):
        module.main()


@pytest.mark.parametrize(
    ("ses_verified", "stack_status", "stack_certificate", "expected_message"),
    [
        (False, "UPDATE_COMPLETE", "expected", "SES identity is not verified"),
        (True, "UPDATE_ROLLBACK_COMPLETE", "expected", "stack is not complete"),
        (True, "UPDATE_COMPLETE", "wrong", "certificate output does not match"),
    ],
)
def test_release_verifier_blocks_unverified_or_mismatched_release_assets(
    monkeypatch: pytest.MonkeyPatch,
    ses_verified: bool,
    stack_status: str,
    stack_certificate: str,
    expected_message: str,
) -> None:
    module = _script_module()

    def aws_json(arguments: list[str]) -> dict[str, object]:
        if arguments[0] == "sesv2":
            return {"VerifiedForSendingStatus": ses_verified}
        return {
            "Stacks": [
                {
                    "StackStatus": stack_status,
                    "Outputs": [
                        {
                            "OutputKey": "CertificateArn",
                            "OutputValue": stack_certificate,
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "_aws_json", aws_json)

    with pytest.raises(RuntimeError, match=expected_message):
        module._release_asset_status(
            "development",
            "alerts@example.test",
            "expected",
        )


def test_release_verifier_accepts_verified_ses_and_stack_bound_tls_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _script_module()

    def aws_json(arguments: list[str]) -> dict[str, object]:
        if arguments[0] == "sesv2":
            return {"VerifiedForSendingStatus": True}
        return {
            "Stacks": [
                {
                    "StackStatus": "UPDATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "CertificateArn",
                            "OutputValue": "expected",
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(module, "_aws_json", aws_json)

    assert module._release_asset_status(
        "development",
        "alerts@example.test",
        "expected",
    ) == {
        "sesIdentityVerified": True,
        "cloudFormationStatus": "UPDATE_COMPLETE",
        "acmCertificateBinding": "STACK_OUTPUT_MATCH",
        "tlsCertificateStatus": "VALID",
    }


def test_active_workflow_runs_funding_checks_and_both_release_verifiers() -> None:
    root_workflow = (
        PROJECT_ROOT.parent / ".github" / "workflows" / "codex-poly-bot-ci.yml"
    ).read_text()
    nested_workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text()

    assert "npm run test:funding-controls" in root_workflow
    assert root_workflow.count("python codex-poly-bot/scripts/verify-funding-release.py") == 2
    assert root_workflow == nested_workflow
