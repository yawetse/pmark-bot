"""Alpaca Broker API boundary for incoming ACH transfers.

REQ: REQ-FND-013, REQ-FND-016, REQ-FND-017
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
from typing import Any

import httpx

from app.domain import ModelProvider


LOGGER = logging.getLogger(__name__)
BROKER_POST_EVENT = "funding_broker_post_attempt"


@dataclass(frozen=True)
class BrokerTransferResult:
    provider_transfer_id: str | None
    status: str
    retryable: bool = False
    error_code: str | None = None


class AlpacaBrokerFundingAdapter:
    """Submit incoming ACH using separately entitled Broker credentials."""

    def __init__(
        self,
        *,
        runtime_env: dict[str, str],
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.runtime_env = dict(runtime_env)
        self.transport = transport
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    def create_incoming_ach(
        self,
        *,
        provider: ModelProvider,
        account_id: str,
        relationship_id: str,
        amount_usd: Decimal,
    ) -> BrokerTransferResult:
        """POST one incoming transfer. Callers must commit their claim first."""

        credentials = self.credentials(provider)
        base_url = (
            credentials.get("ALPACA_BROKER_BASE_URL")
            or "https://broker-api.alpaca.markets"
        ).rstrip("/")
        api_key = credentials.get("ALPACA_BROKER_API_KEY", "").strip()
        secret_key = credentials.get("ALPACA_BROKER_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise ValueError("Alpaca Broker credentials are unavailable")
        payload = {
            "transfer_type": "ach",
            "relationship_id": relationship_id,
            "amount": f"{amount_usd:.2f}",
            "direction": "INCOMING",
        }
        LOGGER.info(
            "%s provider=%s direction=incoming transfer_type=ach",
            BROKER_POST_EVENT,
            provider.value,
        )
        with httpx.Client(
            auth=(api_key, secret_key),
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{base_url}/v1/accounts/{account_id}/transfers",
                json=payload,
            )
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if 200 <= response.status_code < 300:
            return BrokerTransferResult(
                provider_transfer_id=str(body.get("id") or "").strip() or None,
                status=str(body.get("status") or "submitted").strip().lower(),
            )
        if response.status_code >= 500:
            return BrokerTransferResult(
                provider_transfer_id=None,
                status="unknown",
                retryable=True,
                error_code=f"broker_http_{response.status_code}",
            )
        return BrokerTransferResult(
            provider_transfer_id=None,
            status="rejected",
            error_code=f"broker_http_{response.status_code}",
        )

    def list_transfers(
        self,
        *,
        provider: ModelProvider,
        account_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """Read account transfers for conservative unknown reconciliation."""

        credentials = self.credentials(provider)
        base_url = (
            credentials.get("ALPACA_BROKER_BASE_URL")
            or "https://broker-api.alpaca.markets"
        ).rstrip("/")
        api_key = credentials.get("ALPACA_BROKER_API_KEY", "").strip()
        secret_key = credentials.get("ALPACA_BROKER_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            return ()
        transfers: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        with httpx.Client(
            auth=(api_key, secret_key),
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for page_index in range(20):
                try:
                    response = client.get(
                        f"{base_url}/v1/accounts/{account_id}/transfers",
                        params={
                            "direction": "INCOMING",
                            "limit": "100",
                            "offset": str(page_index * 100),
                        },
                    )
                except (httpx.TimeoutException, httpx.TransportError):
                    return tuple(transfers)
                if response.status_code >= 400:
                    return tuple(transfers)
                try:
                    body = response.json()
                except ValueError:
                    return tuple(transfers)
                items = body if isinstance(body, list) else body.get("transfers", [])
                page = [item for item in items if isinstance(item, dict)]
                for item in page:
                    transfer_id = str(item.get("id") or "").strip()
                    if transfer_id and transfer_id in seen_ids:
                        continue
                    if transfer_id:
                        seen_ids.add(transfer_id)
                    transfers.append(item)
                if len(page) < 100:
                    break
        return tuple(transfers)

    def credentials(self, provider: ModelProvider) -> dict[str, str]:
        """Return only provider-scoped Broker credentials for one model account."""

        provider_name = provider.value.upper()
        aliases = {
            "ALPACA_BROKER_API_KEY": (
                f"ALPACA_{provider_name}_BROKER_API_KEY",
                f"{provider_name}_ALPACA_BROKER_API_KEY",
            ),
            "ALPACA_BROKER_SECRET_KEY": (
                f"ALPACA_{provider_name}_BROKER_API_SECRET",
                f"{provider_name}_ALPACA_BROKER_SECRET_KEY",
            ),
            "ALPACA_BROKER_ACCOUNT_ID": (
                f"ALPACA_{provider_name}_BROKER_ACCOUNT_ID",
                f"{provider_name}_ALPACA_BROKER_ACCOUNT_ID",
            ),
            "ALPACA_BROKER_ACH_RELATIONSHIP_ID": (
                f"ALPACA_{provider_name}_ACH_RELATIONSHIP_ID",
                f"{provider_name}_ALPACA_BROKER_ACH_RELATIONSHIP_ID",
            ),
            "ALPACA_BROKER_BASE_URL": (
                f"ALPACA_{provider_name}_BROKER_BASE_URL",
                f"{provider_name}_ALPACA_BROKER_BASE_URL",
            ),
        }
        return {
            logical_name: next(
                (
                    self.runtime_env.get(alias, "").strip()
                    for alias in provider_aliases
                    if self.runtime_env.get(alias, "").strip()
                ),
                "",
            )
            for logical_name, provider_aliases in aliases.items()
        }


__all__ = [
    "AlpacaBrokerFundingAdapter",
    "BROKER_POST_EVENT",
    "BrokerTransferResult",
]
