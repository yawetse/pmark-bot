"""Fail-closed direct-funding orchestration for Alpaca incoming ACH.

REQ: REQ-FND-013 through REQ-FND-018, REQ-FND-020
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import httpx

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import (
    Environment,
    FundingConfig,
    FundingOccurrenceStatus,
    ModelProvider,
    Venue,
)
from app.services.funding_service import FundingRepository, funding_account_ref
from app.venues.alpaca_funding import AlpacaBrokerFundingAdapter


class DirectFundingService:
    """Apply every local safety gate before the one allowed Broker POST."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        adapter: AlpacaBrokerFundingAdapter,
    ) -> None:
        self.registry = registry
        self.repository = FundingRepository(registry)
        self.adapter = adapter

    def submit_occurrence(
        self,
        occurrence_id: str,
        *,
        config: FundingConfig,
        kill_switch_active: bool,
        now: datetime | None = None,
    ) -> dict:
        """Submit at most once after a durable claim, otherwise persist refusal."""

        del config  # The durable claim reloads the active config from persistence.
        current = self.repository.occurrence(occurrence_id)
        if current is None:
            raise PersistenceUnavailableError("funding occurrence was not found")
        if (
            current.get("post_attempted_at") is not None
            or current["status"] != FundingOccurrenceStatus.EXPECTED.value
        ):
            return current
        provider = ModelProvider(current["model_provider"])
        credentials = self.adapter.credentials(provider)
        required = (
            "ALPACA_BROKER_API_KEY",
            "ALPACA_BROKER_SECRET_KEY",
            "ALPACA_BROKER_ACCOUNT_ID",
            "ALPACA_BROKER_ACH_RELATIONSHIP_ID",
        )
        secrets_available = all(credentials.get(key, "").strip() for key in required)
        account_id = credentials.get("ALPACA_BROKER_ACCOUNT_ID", "").strip()
        relationship_id = credentials.get(
            "ALPACA_BROKER_ACH_RELATIONSHIP_ID",
            "",
        ).strip()
        broker_account_ref = (
            funding_account_ref(Venue.ALPACA, account_id) if account_id else None
        )
        at = (now or datetime.now(UTC)).astimezone(UTC)
        claimed = self.repository.claim_direct_occurrence(
            current["id"],
            broker_account_ref=broker_account_ref,
            broker_secrets_available=secrets_available,
            kill_switch_active=kill_switch_active,
            at=at,
        )
        if claimed["status"] != FundingOccurrenceStatus.RESERVED.value:
            return claimed
        amount = claimed["submitted_amount_usd"]
        try:
            result = self.adapter.create_incoming_ach(
                provider=provider,
                account_id=account_id,
                relationship_id=relationship_id,
                amount_usd=amount,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            return self.repository.update_occurrence(
                claimed["id"],
                status=FundingOccurrenceStatus.UNKNOWN.value,
            )
        except Exception:
            return self.repository.update_occurrence(
                claimed["id"],
                status=FundingOccurrenceStatus.UNKNOWN.value,
            )
        if result.status == "unknown" or result.retryable:
            return self.repository.update_occurrence(
                claimed["id"],
                status=FundingOccurrenceStatus.UNKNOWN.value,
            )
        if result.status in {"rejected", "returned", "failed"}:
            terminal = FundingOccurrenceStatus(result.status)
            return self.repository.transition_with_alert(
                claimed["id"],
                status=terminal,
                transition_type="failure",
                at=at,
                reserved_amount_usd=None,
                reserved_at=None,
                refusal_reason=result.error_code or f"broker_{result.status}",
            )
        return self.repository.update_occurrence(
            claimed["id"],
            status=FundingOccurrenceStatus.SUBMITTED.value,
            provider_transfer_id=result.provider_transfer_id,
        )

    def reconcile_occurrence(
        self,
        occurrence_id: str,
        *,
        now: datetime | None = None,
    ) -> dict:
        """Resolve an attempted Broker transfer without ever issuing another POST."""

        current = self.repository.occurrence(occurrence_id)
        if current is None:
            raise PersistenceUnavailableError("funding occurrence was not found")
        if current["execution_mode"] != "direct" or current.get("post_attempted_at") is None:
            return current
        if current["status"] in {
            FundingOccurrenceStatus.MATCHED.value,
            FundingOccurrenceStatus.REFUSED.value,
            FundingOccurrenceStatus.REJECTED.value,
            FundingOccurrenceStatus.RETURNED.value,
            FundingOccurrenceStatus.FAILED.value,
        }:
            return current
        if current["status"] == FundingOccurrenceStatus.RESERVED.value:
            current = self.repository.update_occurrence(
                occurrence_id,
                status=FundingOccurrenceStatus.UNKNOWN.value,
            )

        provider = ModelProvider(current["model_provider"])
        credentials = self.adapter.credentials(provider)
        account_id = credentials.get("ALPACA_BROKER_ACCOUNT_ID", "").strip()
        relationship_id = credentials.get(
            "ALPACA_BROKER_ACH_RELATIONSHIP_ID",
            "",
        ).strip()
        if not account_id or not relationship_id:
            return current
        transfers = self.adapter.list_transfers(provider=provider, account_id=account_id)
        provider_transfer_id = str(current.get("provider_transfer_id") or "").strip()
        if provider_transfer_id:
            candidates = [
                transfer
                for transfer in transfers
                if str(transfer.get("id") or "").strip() == provider_transfer_id
            ]
        else:
            candidates = [
                transfer
                for transfer in transfers
                if self._is_conservative_candidate(
                    current,
                    transfer,
                    relationship_id=relationship_id,
                )
            ]
        if len(candidates) != 1:
            return current

        transfer = candidates[0]
        transfer_id = str(transfer.get("id") or "").strip() or None
        status = str(transfer.get("status") or "submitted").strip().lower()
        at = (now or datetime.now(UTC)).astimezone(UTC)
        terminal_status = {
            "rejected": FundingOccurrenceStatus.REJECTED,
            "returned": FundingOccurrenceStatus.RETURNED,
            "failed": FundingOccurrenceStatus.FAILED,
            "canceled": FundingOccurrenceStatus.FAILED,
            "cancelled": FundingOccurrenceStatus.FAILED,
        }.get(status)
        if terminal_status is not None:
            return self.repository.transition_with_alert(
                occurrence_id,
                status=terminal_status,
                transition_type="failure",
                at=at,
                provider_transfer_id=transfer_id,
                reserved_amount_usd=None,
                reserved_at=None,
                refusal_reason=f"broker_{status}",
            )
        if current["status"] == FundingOccurrenceStatus.MISSING.value:
            return self.repository.update_occurrence(
                occurrence_id,
                provider_transfer_id=transfer_id,
            )
        return self.repository.update_occurrence(
            occurrence_id,
            status=FundingOccurrenceStatus.SUBMITTED.value,
            provider_transfer_id=transfer_id,
        )

    @staticmethod
    def _is_conservative_candidate(
        occurrence: dict,
        transfer: dict,
        *,
        relationship_id: str,
    ) -> bool:
        direction = str(transfer.get("direction") or "").strip().upper()
        if direction != "INCOMING":
            return False
        if str(transfer.get("relationship_id") or "").strip() != relationship_id:
            return False
        try:
            transfer_amount = Decimal(str(transfer.get("amount")))
            expected_amount = Decimal(
                str(
                    occurrence.get("submitted_amount_usd")
                    or occurrence.get("reserved_amount_usd")
                )
            )
        except (InvalidOperation, TypeError, ValueError):
            return False
        if transfer_amount != expected_amount:
            return False
        raw_created_at = transfer.get("created_at") or transfer.get("createdAt")
        if not raw_created_at:
            return False
        try:
            created_at = datetime.fromisoformat(str(raw_created_at).replace("Z", "+00:00"))
        except ValueError:
            return False
        if created_at.tzinfo is None:
            return False
        post_attempted_at = occurrence.get("post_attempted_at")
        if not isinstance(post_attempted_at, datetime):
            return False
        return (
            post_attempted_at.astimezone(UTC) - timedelta(minutes=5)
            <= created_at.astimezone(UTC)
            <= post_attempted_at.astimezone(UTC) + timedelta(hours=1)
        )

__all__ = ["DirectFundingService"]
