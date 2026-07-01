"""Dashboard authentication and authorization service.

REQ: REQ-UI-002, REQ-UI-003, REQ-OBS-004
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services.audit_service import ActorContext, AuditService


@dataclass(frozen=True)
class DashboardAccessResult:
    """Authorization result for dashboard API requests.

    REQ: REQ-UI-002, REQ-UI-003
    """

    authenticated: bool
    authorized: bool
    status_code: int
    username: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class MutationContextResult:
    """CSRF and origin validation result for dashboard mutations.

    REQ: REQ-UI-002, REQ-UI-003
    """

    allowed: bool
    status_code: int
    reason: str | None = None


class AuthService:
    """Validate signed dashboard sessions and allowlisted GitHub users."""

    def __init__(
        self,
        *,
        allowed_usernames: set[str],
        signing_secret: str = "local-dev-session-secret",
        trusted_origins: set[str] | None = None,
        registry: RepositoryRegistry | None = None,
        token_ttl_seconds: int = 3600,
    ):
        self.allowed_usernames = {username.lower() for username in allowed_usernames}
        self.signing_secret = signing_secret.encode()
        self.trusted_origins = trusted_origins or {"http://localhost:3100"}
        self.registry = registry or RepositoryRegistry()
        self.audit_service = AuditService(self.registry)
        self.token_ttl_seconds = token_ttl_seconds

    def create_session_token(
        self,
        *,
        username: str,
        issued_at: datetime | None = None,
    ) -> str:
        """Create a signed session token after GitHub OAuth succeeds.

        REQ: REQ-UI-002
        """

        issued = issued_at or datetime.now(UTC)
        payload = {
            "username": username,
            "exp": int((issued + timedelta(seconds=self.token_ttl_seconds)).timestamp()),
        }
        body = self._encode_json(payload)
        signature = self._signature(body)
        return f"{body}.{signature}"

    def authorize_request(
        self,
        token: str | None,
        *,
        environment: Environment = Environment.LOCAL,
        ip_address: str = "unknown",
        now: datetime | None = None,
    ) -> DashboardAccessResult:
        """Authorize a dashboard request before protected service calls.

        REQ: REQ-UI-002, REQ-UI-003, REQ-OBS-004
        """

        if not token:
            return DashboardAccessResult(
                authenticated=False,
                authorized=False,
                status_code=401,
                reason="authentication required",
            )

        payload = self._decode_token(token)
        current_time = int((now or datetime.now(UTC)).timestamp())
        if payload is None or payload["exp"] < current_time:
            self._record_denial(
                username="unknown",
                ip_address=ip_address,
                environment=environment,
                action="dashboard.access",
                reason="invalid or expired session",
            )
            return DashboardAccessResult(
                authenticated=False,
                authorized=False,
                status_code=401,
                reason="invalid or expired session",
            )

        username = payload["username"]
        if username.lower() not in self.allowed_usernames:
            self._record_denial(
                username=username,
                ip_address=ip_address,
                environment=environment,
                action="dashboard.access",
                reason="user not in allowlist",
            )
            return DashboardAccessResult(
                authenticated=True,
                authorized=False,
                status_code=403,
                username=username,
                reason="user not in allowlist",
            )

        return DashboardAccessResult(
            authenticated=True,
            authorized=True,
            status_code=200,
            username=username,
        )

    def complete_oauth_login(
        self,
        *,
        username: str,
        state: str,
        expected_state: str,
        environment: Environment,
        ip_address: str,
    ) -> DashboardAccessResult:
        """Validate OAuth callback state before creating a session.

        REQ: REQ-UI-002, REQ-UI-003, REQ-OBS-004
        """

        if not hmac.compare_digest(state, expected_state):
            self._record_denial(
                username=username,
                ip_address=ip_address,
                environment=environment,
                action="oauth.callback",
                reason="invalid oauth state",
            )
            return DashboardAccessResult(
                authenticated=False,
                authorized=False,
                status_code=401,
                username=username,
                reason="invalid oauth state",
            )

        token = self.create_session_token(username=username)
        return self.authorize_request(
            token,
            environment=environment,
            ip_address=ip_address,
        )

    def validate_mutation_context(
        self,
        *,
        origin: str,
        csrf_token: str,
        expected_csrf_token: str,
    ) -> MutationContextResult:
        """Reject mutations from untrusted origins or invalid CSRF context.

        REQ: REQ-UI-002, REQ-UI-003
        """

        if origin not in self.trusted_origins:
            return MutationContextResult(
                allowed=False,
                status_code=403,
                reason="untrusted origin",
            )
        if not hmac.compare_digest(csrf_token, expected_csrf_token):
            return MutationContextResult(
                allowed=False,
                status_code=403,
                reason="invalid csrf token",
            )
        return MutationContextResult(allowed=True, status_code=200)

    def _record_denial(
        self,
        *,
        username: str,
        ip_address: str,
        environment: Environment,
        action: str,
        reason: str,
    ) -> None:
        self.audit_service.record_denied_dashboard_action(
            actor=ActorContext(username=username, ip_address=ip_address),
            environment=environment,
            action=action,
            reason=reason,
        )

    def _decode_token(self, token: str) -> dict | None:
        try:
            body, signature = token.split(".", 1)
        except ValueError:
            return None
        if not hmac.compare_digest(signature, self._signature(body)):
            return None
        try:
            payload = json.loads(self._decode_base64(body))
        except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("username"), str)
            or not isinstance(payload.get("exp"), int)
        ):
            return None
        return payload

    def _signature(self, body: str) -> str:
        digest = hmac.new(self.signing_secret, body.encode(), hashlib.sha256).digest()
        return self._encode_base64(digest)

    @staticmethod
    def _encode_json(payload: dict) -> str:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return AuthService._encode_base64(data)

    @staticmethod
    def _encode_base64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @staticmethod
    def _decode_base64(data: str) -> str:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(f"{data}{padding}").decode()
