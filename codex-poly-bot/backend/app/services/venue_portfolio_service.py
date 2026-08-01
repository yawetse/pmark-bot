"""Venue-confirmed account portfolio reconciliation and dashboard summaries.

REQ: REQ-DB-008, REQ-UI-013, REQ-CMP-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Callable, Protocol
from uuid import uuid4

import httpx

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.db.schema import SHARED_SCHEMA
from app.domain import Environment, ModelProvider, Venue, VenueCashFlow
from app.services.funding_service import (
    FundingRepository,
    normalize_alpaca_funding_activity,
    normalize_polymarket_funding_activity,
)
from app.venues.polymarket import (
    POLYMARKET_US_API_BASE_URL,
    POLYMARKET_US_GATEWAY_BASE_URL,
)


PORTFOLIO_SNAPSHOTS_TABLE = f"{SHARED_SCHEMA}.venue_portfolio_snapshots"
POSITION_SNAPSHOTS_TABLE = f"{SHARED_SCHEMA}.venue_position_snapshots"
CONFIRMED_FILLS_TABLE = f"{SHARED_SCHEMA}.venue_confirmed_fills"
PORTFOLIO_HISTORY_ROW_LIMIT = 2_000
PORTFOLIO_FILL_ROW_LIMIT = 2_000
PORTFOLIO_RECENT_FILL_LIMIT = 50
PORTFOLIO_HISTORY_BUCKET_LIMIT = 60
PORTFOLIO_PAGE_SIZE = 100


class VenuePortfolioSource(Protocol):
    """Read normalized account data from configured venue credentials."""

    def fetch_accounts(self, environment: Environment) -> list[dict[str, Any]]:
        ...


@dataclass
class StaticVenuePortfolioSource:
    """Mutable source used by deterministic portfolio tests."""

    accounts: list[dict[str, Any]]

    def fetch_accounts(self, environment: Environment) -> list[dict[str, Any]]:
        del environment
        return [dict(account) for account in self.accounts]


class ProviderBackedVenuePortfolioSource:
    """Read balances, positions, and confirmed fills from venue account APIs."""

    def __init__(
        self,
        runtime_env: dict[str, str],
        *,
        polymarket_client_factory: Callable[[dict[str, str]], Any] | None = None,
        alpaca_transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
        registry: RepositoryRegistry | None = None,
    ) -> None:
        self.runtime_env = dict(runtime_env)
        self.polymarket_client_factory = polymarket_client_factory
        self.alpaca_transport = alpaca_transport
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.funding_repository = FundingRepository(registry) if registry is not None else None
        self._funding_sync_metadata: dict[tuple[str, str, str], dict[str, Any]] = {}

    def fetch_accounts(self, environment: Environment) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        for provider in (ModelProvider.OPENAI, ModelProvider.CLAUDE):
            accounts.append(self._polymarket_account(environment, provider))
            accounts.append(self._alpaca_account(environment, provider))
        return accounts

    def _polymarket_account(
        self,
        environment: Environment,
        provider: ModelProvider,
    ) -> dict[str, Any]:
        provider_env = _provider_env(self.runtime_env, Venue.POLYMARKET_US, provider)
        key_id = provider_env.get("POLYMARKET_KEY_ID", "").strip()
        secret_key = (
            provider_env.get("POLYMARKET_SECRET_KEY", "").strip()
            or provider_env.get("POLYMARKET_PRIVATE_KEY", "").strip()
        )
        fallback_ref = _account_ref(Venue.POLYMARKET_US, key_id or provider.value)
        observed_at = datetime.now(UTC)
        if not key_id or not secret_key:
            return _unavailable_account(
                venue=Venue.POLYMARKET_US,
                provider=provider,
                account_ref=fallback_ref,
                account_mode="live",
                observed_at=observed_at,
                message="Polymarket US credentials are not configured for this model provider.",
            )

        client = None
        try:
            client = self._new_polymarket_client(provider_env)
            balances_response = client.account.balances()
            positions = self._polymarket_positions(client)
            fills, realized_pnl = self._polymarket_activity(client)
            balances = _items(_field(balances_response, "balances"))
            account_ref = self._polymarket_account_ref(
                client,
                provider_env=provider_env,
                balances=balances,
                fallback_ref=fallback_ref,
            )
            cash_flows, funding_status = self._polymarket_funding_activity(
                client,
                environment=environment,
                provider=provider,
                account_ref=account_ref,
                observed_at=observed_at,
            )
            funding_sync = self._funding_sync_metadata.get(
                (environment.value, Venue.POLYMARKET_US.value, account_ref),
                {},
            )
            usd_balances = [
                row for row in balances if str(_field(row, "currency") or "USD").upper() == "USD"
            ]
            cash = sum(
                (_decimal_or_zero(_field(row, "currentBalance")) for row in usd_balances),
                Decimal("0"),
            )
            buying_power_values = [
                value
                for row in usd_balances
                if (value := _decimal_or_none(_field(row, "buyingPower"))) is not None
            ]
            buying_power = (
                sum(buying_power_values, Decimal("0")) if buying_power_values else None
            )
            position_value = sum(
                (_decimal_or_zero(row.get("marketValueUsd")) for row in positions), Decimal("0")
            )
            asset_values = [_decimal_or_none(_field(row, "assetNotional")) for row in usd_balances]
            available_asset_values = [value for value in asset_values if value is not None]
            asset_value = (
                sum(available_asset_values, Decimal("0"))
                if available_asset_values
                else position_value
            )
            return {
                "status": "ready",
                "venue": Venue.POLYMARKET_US.value,
                "provider": provider.value,
                "accountRef": account_ref,
                "accountMode": "live",
                "cashUsd": cash,
                "buyingPowerUsd": buying_power,
                "accountValueUsd": cash + asset_value,
                "realizedPnlUsd": realized_pnl,
                "positions": positions,
                "fills": fills,
                "cashFlows": [flow.model_dump(mode="json") for flow in cash_flows],
                "fundingStatus": funding_status,
                "fundingSync": funding_sync,
                "observedAt": observed_at,
                "message": "Confirmed from the Polymarket US portfolio API.",
            }
        except Exception as exc:  # pragma: no cover - exact SDK exceptions vary by version.
            return _unavailable_account(
                venue=Venue.POLYMARKET_US,
                provider=provider,
                account_ref=fallback_ref,
                account_mode="live",
                observed_at=observed_at,
                message=f"Polymarket US portfolio refresh failed: {type(exc).__name__}.",
                status="error",
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _polymarket_funding_activity(
        self,
        client: Any,
        *,
        environment: Environment,
        provider: ModelProvider,
        account_ref: str,
        observed_at: datetime,
    ) -> tuple[list[VenueCashFlow], str]:
        """Read bounded Polymarket US deposit and withdrawal activity.

        REQ: REQ-FND-001, REQ-FND-004, REQ-FND-020
        """

        flows: list[VenueCashFlow] = []
        seen_ids: set[str] = set()
        stored_sync = self._stored_sync_state(
            environment=environment,
            venue=Venue.POLYMARKET_US,
            account_ref=account_ref,
        )
        stored_cursor = str((stored_sync or {}).get("backfill_cursor") or "").strip() or None
        stored_head = str((stored_sync or {}).get("head_transaction_id") or "").strip() or None
        cursor: str | None = None
        seen_cursors: set[str] = set()
        complete = False
        phase = "head" if stored_head or stored_cursor else "history"
        observed_head: str | None = None
        next_head = stored_head
        try:
            for page_index in range(20):
                params: dict[str, Any] = {
                    "limit": PORTFOLIO_PAGE_SIZE,
                    "sortOrder": "SORT_ORDER_DESCENDING",
                    "types": [
                        "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
                        "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
                        "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
                    ],
                }
                if cursor:
                    params["cursor"] = cursor
                response = client.portfolio.activities(params)
                activities = _items(_field(response, "activities"))
                activity_ids = [
                    str(_field(activity, "id") or "").strip()
                    for activity in activities
                ]
                if page_index == 0 and activity_ids and activity_ids[0]:
                    observed_head = activity_ids[0]
                    if phase == "history":
                        next_head = observed_head
                for activity in activities:
                    activity_type = str(_field(activity, "type") or "").replace(
                        "ACTIVITY_TYPE_", ""
                    )
                    nested_name = {
                        "ACCOUNT_DEPOSIT": "accountDeposit",
                        "ACCOUNT_ADVANCED_DEPOSIT": "accountAdvancedDeposit",
                        "ACCOUNT_WITHDRAWAL": "accountWithdrawal",
                    }.get(activity_type)
                    nested = _field(activity, nested_name) if nested_name else None
                    raw = dict(activity) if isinstance(activity, dict) else {}
                    raw.update(nested if isinstance(nested, dict) else {})
                    raw["type"] = activity_type
                    balance_change = _field(activity, "accountBalanceChange")
                    if isinstance(balance_change, dict):
                        raw["accountBalanceChange"] = balance_change
                    for key in ("id", "amount", "cashValue", "updateTime", "createTime", "status"):
                        if key not in raw and _field(activity, key) is not None:
                            raw[key] = _field(activity, key)
                    normalized = normalize_polymarket_funding_activity(
                        raw,
                        environment=environment,
                        provider=provider,
                        account_ref=account_ref,
                        observed_at=observed_at,
                    )
                    if normalized is None or normalized.venue_transaction_id in seen_ids:
                        continue
                    seen_ids.add(normalized.venue_transaction_id)
                    flows.append(normalized)
                next_cursor = _text_or_none(_field(response, "nextCursor"))
                exhausted = bool(_field(response, "eof")) or not next_cursor
                reached_stored_head = bool(stored_head and stored_head in activity_ids)
                if phase == "head" and (
                    reached_stored_head or exhausted or not stored_head
                ):
                    if observed_head:
                        next_head = observed_head
                    if stored_cursor:
                        phase = "history"
                        cursor = stored_cursor
                        continue
                    complete = True
                    cursor = None
                    break
                if exhausted:
                    complete = True
                    cursor = None
                    break
                if next_cursor in seen_cursors:
                    cursor = next_cursor
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except Exception:
            self._record_funding_sync_metadata(
                environment=environment,
                venue=Venue.POLYMARKET_US,
                account_ref=account_ref,
                backfill_cursor=stored_cursor,
                backfill_complete=False,
                last_error_code="polymarket_funding_read_failed",
                head_transaction_id=stored_head,
            )
            return [], "error"
        self._record_funding_sync_metadata(
            environment=environment,
            venue=Venue.POLYMARKET_US,
            account_ref=account_ref,
            backfill_cursor=None if complete else cursor,
            backfill_complete=complete,
            last_error_code=None,
            head_transaction_id=next_head,
        )
        return flows, "ready" if complete else "partial"

    def _new_polymarket_client(self, provider_env: dict[str, str]) -> Any:
        if self.polymarket_client_factory is not None:
            return self.polymarket_client_factory(provider_env)
        from polymarket_us import PolymarketUS

        return PolymarketUS(
            key_id=provider_env["POLYMARKET_KEY_ID"],
            secret_key=(
                provider_env.get("POLYMARKET_SECRET_KEY")
                or provider_env.get("POLYMARKET_PRIVATE_KEY")
            ),
            gateway_base_url=provider_env.get(
                "POLYMARKET_GATEWAY_BASE_URL",
                POLYMARKET_US_GATEWAY_BASE_URL,
            ),
            api_base_url=provider_env.get(
                "POLYMARKET_API_BASE_URL",
                POLYMARKET_US_API_BASE_URL,
            ),
            timeout=self.timeout_seconds,
        )

    def _polymarket_positions(self, client: Any) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {"limit": PORTFOLIO_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            response = client.portfolio.positions(params)
            raw_positions = _field(response, "positions") or {}
            if isinstance(raw_positions, dict):
                items = raw_positions.items()
            else:
                items = ()
            for market_slug, raw in items:
                quantity = _decimal_or_zero(
                    _field(raw, "netPositionDecimal") or _field(raw, "netPosition")
                )
                expired = bool(_field(raw, "expired"))
                if quantity == 0 or expired:
                    continue
                cost_basis = _amount(_field(raw, "cost"))
                market_value = _amount(_field(raw, "cashValue"))
                realized = _amount(_field(raw, "realized"))
                metadata = _field(raw, "marketMetadata") or {}
                absolute_quantity = abs(quantity)
                positions.append(
                    {
                        "instrumentId": str(market_slug),
                        "title": str(_field(metadata, "title") or market_slug),
                        "outcome": _text_or_none(_field(metadata, "outcome")),
                        "quantity": quantity,
                        "averageEntryPrice": _divide_or_none(cost_basis, absolute_quantity),
                        "currentPrice": _divide_or_none(market_value, absolute_quantity),
                        "costBasisUsd": cost_basis,
                        "marketValueUsd": market_value,
                        "realizedPnlUsd": realized,
                        "unrealizedPnlUsd": market_value - cost_basis,
                        "state": "open",
                        "updatedAt": _datetime_or_now(_field(raw, "updateTime")),
                    }
                )
            cursor = _text_or_none(_field(response, "nextCursor"))
            if bool(_field(response, "eof")) or not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        return positions

    def _polymarket_activity(self, client: Any) -> tuple[list[dict[str, Any]], Decimal]:
        fills: list[dict[str, Any]] = []
        realized_pnl = Decimal("0")
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "limit": PORTFOLIO_PAGE_SIZE,
                "sortOrder": "SORT_ORDER_DESCENDING",
                "types": [
                    "ACTIVITY_TYPE_TRADE",
                    "ACTIVITY_TYPE_POSITION_RESOLUTION",
                ],
            }
            if cursor:
                params["cursor"] = cursor
            response = client.portfolio.activities(params)
            activities = _items(_field(response, "activities"))
            for activity in activities:
                activity_type = str(_field(activity, "type") or "")
                if activity_type == "ACTIVITY_TYPE_POSITION_RESOLUTION":
                    resolution = _field(activity, "positionResolution") or {}
                    before = _field(resolution, "beforePosition") or {}
                    after = _field(resolution, "afterPosition") or {}
                    realized_pnl += _amount(_field(after, "realized")) - _amount(
                        _field(before, "realized")
                    )
                    continue
                if activity_type != "ACTIVITY_TYPE_TRADE":
                    continue
                trade = _field(activity, "trade") or {}
                trade_id = str(_field(trade, "id") or "").strip()
                if not trade_id or trade_id in seen_ids:
                    continue
                trade_state = str(_field(trade, "state") or "").strip().upper()
                if trade_state not in {"CLEARED", "TRADE_STATE_CLEARED"}:
                    continue
                seen_ids.add(trade_id)
                quantity = _decimal_or_zero(
                    _field(trade, "qtyDecimal") or _field(trade, "qty")
                )
                price = _amount(_field(trade, "price"))
                trade_realized = _amount_or_none(_field(trade, "realizedPnl"))
                realized_pnl += trade_realized or Decimal("0")
                fills.append(
                    {
                        "sourceTradeId": trade_id,
                        "venueOrderId": None,
                        "instrumentId": str(_field(trade, "marketSlug") or "unknown"),
                        "title": str(_field(trade, "marketSlug") or "Unknown market"),
                        "side": "sell" if quantity < 0 else "buy",
                        "quantity": abs(quantity),
                        "price": price,
                        "notionalUsd": abs(quantity * price),
                        "realizedPnlUsd": trade_realized,
                        "feeUsd": None,
                        "state": "filled",
                        "executedAt": _datetime_or_now(
                            _field(trade, "updateTime") or _field(trade, "createTime")
                        ),
                    }
                )
            cursor = _text_or_none(_field(response, "nextCursor"))
            if bool(_field(response, "eof")) or not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        return fills, realized_pnl

    def _polymarket_account_ref(
        self,
        client: Any,
        *,
        provider_env: dict[str, str],
        balances: list[Any],
        fallback_ref: str,
    ) -> str:
        """Resolve stable account identity without exposing venue identifiers."""

        configured = str(provider_env.get("POLYMARKET_ACCOUNT_ID") or "").strip()
        if configured:
            return _account_ref(Venue.POLYMARKET_US, configured)
        balance_ids = sorted(
            {
                str(_field(row, field)).strip()
                for row in balances
                for field in ("accountId", "account", "bankId")
                if str(_field(row, field) or "").strip()
            }
        )
        if balance_ids:
            return _account_ref(Venue.POLYMARKET_US, "|".join(balance_ids))
        get = getattr(client, "get", None)
        if not callable(get):
            return fallback_ref
        for path in ("/v1/accounts", "/v1/whoami"):
            try:
                response = get(path, authenticated=True)
            except Exception:
                continue
            identities = _polymarket_identity_values(response)
            if identities:
                return _account_ref(Venue.POLYMARKET_US, "|".join(identities))
        return fallback_ref

    def _alpaca_account(
        self,
        environment: Environment,
        provider: ModelProvider,
    ) -> dict[str, Any]:
        provider_env = _provider_env(self.runtime_env, Venue.ALPACA, provider)
        key_id = provider_env.get("ALPACA_KEY_ID", "").strip()
        secret_key = provider_env.get("ALPACA_SECRET_KEY", "").strip()
        fallback_ref = _account_ref(Venue.ALPACA, key_id or provider.value)
        account_mode = str(provider_env.get("TRADING_ACCOUNT_MODE", "paper")).strip().lower()
        observed_at = datetime.now(UTC)
        if not key_id or not secret_key:
            return _unavailable_account(
                venue=Venue.ALPACA,
                provider=provider,
                account_ref=fallback_ref,
                account_mode=account_mode,
                observed_at=observed_at,
                message="Alpaca credentials are not configured for this model provider.",
            )

        headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        base_url = _alpaca_base_url(provider_env, account_mode)
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.alpaca_transport) as client:
                account = _response_json(
                    client.get(f"{base_url}/v2/account", headers=headers),
                    "Alpaca account",
                )
                raw_positions = _items(
                    _response_json(
                        client.get(f"{base_url}/v2/positions", headers=headers),
                        "Alpaca positions",
                    )
                )
                raw_fills = self._alpaca_fills(client, base_url=base_url, headers=headers)
                portfolio_history = self._alpaca_portfolio_history(
                    client,
                    base_url=base_url,
                    headers=headers,
                    account=account,
                )
            account_id = str(_field(account, "id") or key_id)
            account_ref = _account_ref(Venue.ALPACA, account_id)
            cash_flows, funding_status = self._alpaca_funding_activity(
                base_url=base_url,
                headers=headers,
                environment=environment,
                provider=provider,
                account_ref=account_ref,
                observed_at=observed_at,
            )
            funding_sync = self._funding_sync_metadata.get(
                (environment.value, Venue.ALPACA.value, account_ref),
                {},
            )
            positions = [_normalize_alpaca_position(row, observed_at) for row in raw_positions]
            fills = [_normalize_alpaca_fill(row, observed_at) for row in raw_fills]
            unrealized_pnl = sum(
                (_decimal_or_zero(row.get("unrealizedPnlUsd")) for row in positions),
                Decimal("0"),
            )
            total_pnl = _latest_alpaca_profit_loss(portfolio_history)
            if total_pnl is None:
                raise ValueError("Alpaca portfolio history did not include profit and loss")
            return {
                "status": "ready",
                "venue": Venue.ALPACA.value,
                "provider": provider.value,
                "accountRef": account_ref,
                "accountMode": account_mode,
                "cashUsd": _decimal_or_none(_field(account, "cash")),
                "buyingPowerUsd": _decimal_or_none(_field(account, "buying_power")),
                "accountValueUsd": _decimal_or_none(
                    _field(account, "portfolio_value") or _field(account, "equity")
                ),
                "realizedPnlUsd": total_pnl - unrealized_pnl,
                "totalPnlUsd": total_pnl,
                "positions": positions,
                "fills": fills,
                "cashFlows": [flow.model_dump(mode="json") for flow in cash_flows],
                "fundingStatus": funding_status,
                "fundingSync": funding_sync,
                "observedAt": observed_at,
                "message": "Confirmed from the Alpaca Trading API.",
            }
        except Exception as exc:
            return _unavailable_account(
                venue=Venue.ALPACA,
                provider=provider,
                account_ref=fallback_ref,
                account_mode=account_mode,
                observed_at=observed_at,
                message=f"Alpaca portfolio refresh failed: {type(exc).__name__}.",
                status="error",
            )

    def _alpaca_funding_activity(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        environment: Environment,
        provider: ModelProvider,
        account_ref: str,
        observed_at: datetime,
    ) -> tuple[list[VenueCashFlow], str]:
        """Read bounded pages for each documented Alpaca cash activity type.

        REQ: REQ-FND-001, REQ-FND-003, REQ-FND-004
        """

        flows: list[VenueCashFlow] = []
        seen_ids: set[str] = set()
        stored_cursor_raw = self._stored_backfill_cursor(
            environment=environment,
            venue=Venue.ALPACA,
            account_ref=account_ref,
        )
        try:
            stored_payload = json.loads(stored_cursor_raw) if stored_cursor_raw else {}
        except (TypeError, ValueError):
            stored_payload = {}
        if not isinstance(stored_payload, dict):
            stored_payload = {}
        stored_cursors = stored_payload.get("cursors", stored_payload)
        stored_heads = stored_payload.get("heads", {})
        if not isinstance(stored_cursors, dict):
            stored_cursors = {}
        if not isinstance(stored_heads, dict):
            stored_heads = {}
        next_cursors: dict[str, str] = {}
        next_heads: dict[str, str] = {
            str(key): str(value)
            for key, value in stored_heads.items()
            if str(value).strip()
        }
        backfill_complete = True
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.alpaca_transport,
            ) as client:
                for activity_type in ("CSD", "CSW", "TRANS"):
                    page_token: str | None = None
                    stored_page_token = str(stored_cursors.get(activity_type) or "").strip()
                    stored_head = str(stored_heads.get(activity_type) or "").strip()
                    phase = "head" if stored_head or stored_page_token else "history"
                    type_complete = False
                    observed_head: str | None = None
                    seen_tokens: set[str] = set()
                    for page_index in range(20):
                        params = {
                            "direction": "desc",
                            "page_size": str(PORTFOLIO_PAGE_SIZE),
                        }
                        if page_token:
                            params["page_token"] = page_token
                        page = _items(
                            _response_json(
                                client.get(
                                    f"{base_url}/v2/account/activities/{activity_type}",
                                    headers=headers,
                                    params=params,
                                ),
                                f"Alpaca {activity_type} activity",
                            )
                        )
                        page_ids = [
                            str(_field(raw, "id") or "").strip()
                            for raw in page[:PORTFOLIO_PAGE_SIZE]
                        ]
                        if page_index == 0 and page_ids and page_ids[0]:
                            observed_head = page_ids[0]
                            if phase == "history":
                                next_heads[activity_type] = observed_head
                        for raw in page[:PORTFOLIO_PAGE_SIZE]:
                            normalized = normalize_alpaca_funding_activity(
                                raw,
                                environment=environment,
                                provider=provider,
                                account_ref=account_ref,
                                observed_at=observed_at,
                            )
                            if (
                                normalized is None
                                or normalized.venue_transaction_id in seen_ids
                            ):
                                continue
                            seen_ids.add(normalized.venue_transaction_id)
                            flows.append(normalized)
                        short_page = len(page) < PORTFOLIO_PAGE_SIZE
                        reached_stored_head = bool(
                            stored_head and stored_head in page_ids
                        )
                        if phase == "head" and (
                            reached_stored_head or short_page or not stored_head
                        ):
                            if observed_head:
                                next_heads[activity_type] = observed_head
                            if stored_page_token:
                                phase = "history"
                                page_token = stored_page_token
                                continue
                            type_complete = True
                            page_token = None
                            break
                        if short_page:
                            type_complete = True
                            page_token = None
                            break
                        next_token = str(_field(page[-1], "id") or "").strip()
                        if not next_token or next_token in seen_tokens:
                            if next_token:
                                page_token = next_token
                            break
                        seen_tokens.add(next_token)
                        page_token = next_token
                    if not type_complete:
                        backfill_complete = False
                        if phase == "head" and stored_page_token:
                            next_cursors[activity_type] = stored_page_token
                        elif page_token:
                            next_cursors[activity_type] = page_token
        except Exception:
            self._record_funding_sync_metadata(
                environment=environment,
                venue=Venue.ALPACA,
                account_ref=account_ref,
                backfill_cursor=stored_cursor_raw,
                backfill_complete=False,
                last_error_code="alpaca_funding_read_failed",
            )
            return [], "error"
        cursor_payload = json.dumps(
            {"cursors": next_cursors, "heads": next_heads},
            sort_keys=True,
            separators=(",", ":"),
        )
        self._record_funding_sync_metadata(
            environment=environment,
            venue=Venue.ALPACA,
            account_ref=account_ref,
            backfill_cursor=cursor_payload,
            backfill_complete=backfill_complete,
            last_error_code=None,
        )
        return flows, "ready" if backfill_complete else "partial"

    def _stored_backfill_cursor(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
    ) -> str | None:
        state = self._stored_sync_state(
            environment=environment,
            venue=venue,
            account_ref=account_ref,
        )
        return str((state or {}).get("backfill_cursor") or "").strip() or None

    def _stored_sync_state(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
    ) -> dict[str, Any] | None:
        if self.funding_repository is None:
            return None
        return self.funding_repository.sync_state(
            environment=environment,
            venue=venue,
            account_ref=account_ref,
        )

    def _record_funding_sync_metadata(
        self,
        *,
        environment: Environment,
        venue: Venue,
        account_ref: str,
        backfill_cursor: str | None,
        backfill_complete: bool,
        last_error_code: str | None,
        head_transaction_id: str | None = None,
    ) -> None:
        self._funding_sync_metadata[(environment.value, venue.value, account_ref)] = {
            "backfillCursor": backfill_cursor,
            "backfillComplete": backfill_complete,
            "lastErrorCode": last_error_code,
            "headTransactionId": head_transaction_id,
        }

    def _alpaca_fills(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        fills: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_ids: set[str] = set()
        while True:
            params = {"direction": "desc", "page_size": str(PORTFOLIO_PAGE_SIZE)}
            if page_token:
                params["page_token"] = page_token
            page = _items(
                _response_json(
                    client.get(
                        f"{base_url}/v2/account/activities/FILL",
                        headers=headers,
                        params=params,
                    ),
                    "Alpaca fills",
                )
            )
            if not page:
                break
            for fill in page:
                fill_id = str(_field(fill, "id") or "").strip()
                if fill_id and fill_id not in seen_ids:
                    seen_ids.add(fill_id)
                    fills.append(fill)
            if len(page) < PORTFOLIO_PAGE_SIZE:
                break
            next_token = str(_field(page[-1], "id") or "").strip()
            if not next_token or next_token == page_token:
                break
            page_token = next_token
        return fills

    def _alpaca_portfolio_history(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        headers: dict[str, str],
        account: Any,
    ) -> dict[str, Any]:
        created_at = _text_or_none(_field(account, "created_at"))
        if created_at is None:
            raise ValueError("Alpaca account creation time is unavailable")
        response = _response_json(
            client.get(
                f"{base_url}/v2/account/portfolio/history",
                headers=headers,
                params={
                    "start": created_at,
                    "timeframe": "1D",
                    "cashflow_types": "ALL",
                },
            ),
            "Alpaca portfolio history",
        )
        if not isinstance(response, dict):
            raise ValueError("Alpaca portfolio history response is invalid")
        return response


class VenuePortfolioService:
    """Persist sanitized venue snapshots and calculate actual account performance."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        source: VenuePortfolioSource,
    ) -> None:
        self.registry = registry
        self.source = source
        self.funding_repository = FundingRepository(registry)

    def refresh(self, environment: Environment) -> dict[str, Any]:
        """Refresh all configured accounts without using order-intent or simulation rows."""

        accounts = self.source.fetch_accounts(environment)
        for account in accounts:
            self._persist_account(environment, account)
        return self.summary(environment)

    def summary(self, environment: Environment) -> dict[str, Any]:
        """Return deduplicated venue and account performance for the main dashboard."""

        now = datetime.now(UTC)
        try:
            snapshots = self.registry.state.rows(
                PORTFOLIO_SNAPSHOTS_TABLE,
                limit=PORTFOLIO_HISTORY_ROW_LIMIT,
                newest_first=True,
                filters={"environment": environment.value},
            )
            position_rows = self.registry.state.rows(
                POSITION_SNAPSHOTS_TABLE,
                limit=PORTFOLIO_HISTORY_ROW_LIMIT,
                newest_first=True,
                filters={"environment": environment.value},
            )
            fill_rows = self.registry.state.rows(
                CONFIRMED_FILLS_TABLE,
                limit=PORTFOLIO_FILL_ROW_LIMIT,
                newest_first=True,
                filters={"environment": environment.value},
            )
        except PersistenceUnavailableError:
            return _empty_summary(environment, now, "Portfolio persistence is unavailable.")

        accounts = _account_views(snapshots, position_rows)
        venues = [
            _aggregate_accounts(
                [account for account in accounts if account["venue"] == venue.value],
                venue=venue.value,
            )
            for venue in (Venue.POLYMARKET_US, Venue.ALPACA)
        ]
        overall = _aggregate_accounts(accounts)
        selected_account_refs = {account["accountRef"] for account in accounts}
        fills = [
            _fill_payload(row)
            for row in sorted(
                (
                    row
                    for row in fill_rows
                    if row.get("account_ref") in selected_account_refs
                ),
                key=lambda row: (_datetime_or_min(row.get("executed_at")), str(row.get("id"))),
                reverse=True,
            )[:PORTFOLIO_RECENT_FILL_LIMIT]
        ]
        latest_observed = max(
            (
                _datetime_or_min(row.get("observed_at"))
                for row in snapshots
                if row.get("status") == "ready"
            ),
            default=None,
        )
        age_seconds = (
            max(0, int((now - latest_observed).total_seconds()))
            if latest_observed is not None
            else None
        )
        positions = [
            position
            for account in accounts
            for position in account.get("_positions", [])
        ]
        public_accounts = [
            {key: value for key, value in account.items() if key != "_positions"}
            for account in accounts
        ]
        return {
            "environment": environment.value,
            "generatedAt": now.isoformat(),
            "overall": overall,
            "venues": venues,
            "accounts": public_accounts,
            "positions": positions,
            "fills": fills,
            "history": _portfolio_history(snapshots),
            "freshness": {
                "status": overall["status"],
                "refreshedAt": latest_observed.isoformat() if latest_observed else None,
                "ageSeconds": age_seconds,
                "message": _freshness_message(overall["status"], age_seconds),
            },
            "source": "venue-confirmed account APIs",
        }

    def _persist_account(self, environment: Environment, account: dict[str, Any]) -> None:
        transaction = self.registry.state.begin_transaction()
        try:
            self._persist_account_rows(environment, account)
            self.registry.state.commit_transaction(transaction)
        except Exception:
            self.registry.state.rollback_transaction(transaction)
            raise

    def _persist_account_rows(self, environment: Environment, account: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        venue = str(account.get("venue") or "unknown")
        provider = str(account.get("provider") or "unknown")
        account_ref = str(account.get("accountRef") or _account_ref_text(venue, provider))
        observed_at = _datetime_or_now(account.get("observedAt"))
        status = str(account.get("status") or "error")
        if status != "ready":
            self.registry.state.insert(
                PORTFOLIO_SNAPSHOTS_TABLE,
                {
                    "id": str(uuid4()),
                    "environment": environment.value,
                    "venue": venue,
                    "model_provider": provider,
                    "account_ref": account_ref,
                    "account_mode": str(account.get("accountMode") or "unknown"),
                    "status": status,
                    "cash_usd": None,
                    "buying_power_usd": None,
                    "account_value_usd": None,
                    "cost_basis_usd": None,
                    "market_value_usd": None,
                    "realized_pnl_usd": None,
                    "unrealized_pnl_usd": None,
                    "total_pnl_usd": None,
                    "open_position_count": 0,
                    "filled_trade_count": 0,
                    "message": str(account.get("message") or "Venue portfolio is unavailable."),
                    "observed_at": observed_at,
                    "created_at": now,
                },
            )
            return

        cash_flows: list[VenueCashFlow] = []
        for raw_cash_flow in account.get("cashFlows") or []:
            try:
                cash_flow = VenueCashFlow.model_validate(raw_cash_flow)
            except (TypeError, ValueError):
                continue
            if (
                cash_flow.environment != environment
                or cash_flow.venue.value != venue
                or cash_flow.account_ref != account_ref
            ):
                continue
            cash_flows.append(cash_flow)
            self.funding_repository.upsert_cash_flow(cash_flow)
        funding_status = str(account.get("fundingStatus") or "unavailable")
        funding_sync = account.get("fundingSync") or {}
        if funding_status in {"ready", "partial", "error"}:
            prior_sync = self.funding_repository.sync_state(
                environment=environment,
                venue=Venue(venue),
                account_ref=account_ref,
            ) or {}
            self.funding_repository.set_sync_state(
                environment=environment,
                venue=Venue(venue),
                account_ref=account_ref,
                coverage_through_at=(
                    observed_at
                    if funding_status == "ready"
                    else prior_sync.get("coverage_through_at")
                ),
                head_transaction_id=(
                    funding_sync.get("headTransactionId")
                    or (
                        cash_flows[0].venue_transaction_id
                        if cash_flows
                        else prior_sync.get("head_transaction_id")
                    )
                ),
                backfill_cursor=funding_sync.get("backfillCursor"),
                backfill_complete=bool(funding_sync.get("backfillComplete")),
                last_error_code=funding_sync.get("lastErrorCode"),
            )

        for fill in account.get("fills") or []:
            self._upsert_fill(
                environment=environment,
                venue=venue,
                provider=provider,
                account_ref=account_ref,
                fill=fill,
                now=now,
            )
        positions = [dict(position) for position in account.get("positions") or []]
        account_fills = self._account_fills(environment, venue, account_ref)
        if venue == Venue.ALPACA.value:
            realized = _decimal_or_none(account.get("realizedPnlUsd"))
        else:
            realized = _decimal_or_none(account.get("realizedPnlUsd"))
            if realized is None:
                realized = sum(
                    (_decimal_or_zero(row.get("realized_pnl_usd")) for row in account_fills),
                    Decimal("0"),
                )
        cost_basis = sum(
            (_decimal_or_zero(position.get("costBasisUsd")) for position in positions),
            Decimal("0"),
        )
        market_value = sum(
            (_decimal_or_zero(position.get("marketValueUsd")) for position in positions),
            Decimal("0"),
        )
        unrealized = sum(
            (
                _decimal_or_zero(
                    position.get("unrealizedPnlUsd"),
                    default=(
                        _decimal_or_zero(position.get("marketValueUsd"))
                        - _decimal_or_zero(position.get("costBasisUsd"))
                    ),
                )
                for position in positions
            ),
            Decimal("0"),
        )
        supplied_total = _decimal_or_none(account.get("totalPnlUsd"))
        total_pnl = supplied_total
        if total_pnl is None and realized is not None:
            total_pnl = realized + unrealized
        snapshot_id = str(uuid4())
        self.registry.state.insert(
            PORTFOLIO_SNAPSHOTS_TABLE,
            {
                "id": snapshot_id,
                "environment": environment.value,
                "venue": venue,
                "model_provider": provider,
                "account_ref": account_ref,
                "account_mode": str(account.get("accountMode") or "unknown"),
                "status": "ready",
                "cash_usd": _decimal_or_none(account.get("cashUsd")),
                "buying_power_usd": _decimal_or_none(account.get("buyingPowerUsd")),
                "account_value_usd": _decimal_or_none(account.get("accountValueUsd")),
                "cost_basis_usd": cost_basis,
                "market_value_usd": market_value,
                "realized_pnl_usd": realized,
                "unrealized_pnl_usd": unrealized,
                "total_pnl_usd": total_pnl,
                "open_position_count": sum(
                    1
                    for position in positions
                    if str(position.get("state") or "open") == "open"
                    and _decimal_or_zero(position.get("quantity")) != 0
                ),
                "filled_trade_count": len(account_fills),
                "message": str(account.get("message") or "Confirmed from venue account API."),
                "observed_at": observed_at,
                "created_at": now,
            },
        )
        for position in positions:
            self.registry.state.insert(
                POSITION_SNAPSHOTS_TABLE,
                {
                    "id": str(uuid4()),
                    "portfolio_snapshot_id": snapshot_id,
                    "environment": environment.value,
                    "venue": venue,
                    "model_provider": provider,
                    "account_ref": account_ref,
                    "instrument_id": str(position.get("instrumentId") or "unknown"),
                    "title": str(position.get("title") or position.get("instrumentId") or "Unknown"),
                    "outcome": _text_or_none(position.get("outcome")),
                    "quantity": _decimal_or_zero(position.get("quantity")),
                    "average_entry_price": _decimal_or_none(position.get("averageEntryPrice")),
                    "current_price": _decimal_or_none(position.get("currentPrice")),
                    "cost_basis_usd": _decimal_or_none(position.get("costBasisUsd")),
                    "market_value_usd": _decimal_or_none(position.get("marketValueUsd")),
                    "realized_pnl_usd": _decimal_or_none(position.get("realizedPnlUsd")),
                    "unrealized_pnl_usd": _decimal_or_none(position.get("unrealizedPnlUsd")),
                    "total_pnl_usd": (
                        _decimal_or_zero(position.get("realizedPnlUsd"))
                        + _decimal_or_zero(position.get("unrealizedPnlUsd"))
                    ),
                    "state": str(position.get("state") or "open"),
                    "observed_at": _datetime_or_now(position.get("updatedAt") or observed_at),
                    "created_at": now,
                },
            )

    def _upsert_fill(
        self,
        *,
        environment: Environment,
        venue: str,
        provider: str,
        account_ref: str,
        fill: dict[str, Any],
        now: datetime,
    ) -> None:
        source_trade_id = str(fill.get("sourceTradeId") or "").strip()
        state = str(fill.get("state") or "").strip().lower()
        if not source_trade_id or state not in {"filled", "trade", "settled"}:
            return
        row_id = _fill_id(environment.value, venue, account_ref, source_trade_id)
        self.registry.state.lock_transaction_key(row_id)
        existing = self.registry.state.rows(
            CONFIRMED_FILLS_TABLE,
            limit=1,
            filters={"id": row_id},
        )
        providers = sorted(
            set((existing[0].get("providers") if existing else []) or []) | {provider}
        )
        values = {
            "environment": environment.value,
            "venue": venue,
            "providers": providers,
            "account_ref": account_ref,
            "source_trade_id": source_trade_id,
            "venue_order_id": _text_or_none(fill.get("venueOrderId")),
            "instrument_id": str(fill.get("instrumentId") or "unknown"),
            "title": str(fill.get("title") or fill.get("instrumentId") or "Unknown"),
            "side": str(fill.get("side") or "unknown").lower(),
            "quantity": abs(_decimal_or_zero(fill.get("quantity"))),
            "price": _decimal_or_zero(fill.get("price")),
            "notional_usd": abs(_decimal_or_zero(fill.get("notionalUsd"))),
            "realized_pnl_usd": _decimal_or_none(fill.get("realizedPnlUsd")),
            "fee_usd": _decimal_or_none(fill.get("feeUsd")),
            "state": "filled",
            "executed_at": _datetime_or_now(fill.get("executedAt")),
            "created_at": existing[0].get("created_at") if existing else now,
            "updated_at": now,
        }
        self.registry.state.upsert_by_id(CONFIRMED_FILLS_TABLE, row_id, values)

    def _account_fills(
        self,
        environment: Environment,
        venue: str,
        account_ref: str,
    ) -> list[dict[str, Any]]:
        return self.registry.state.rows(
            CONFIRMED_FILLS_TABLE,
            limit=PORTFOLIO_FILL_ROW_LIMIT,
            filters={
                "environment": environment.value,
                "venue": venue,
                "account_ref": account_ref,
            },
        )


def _account_views(
    snapshots: list[dict[str, Any]],
    position_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest_by_provider: dict[tuple[str, str], dict[str, Any]] = {}
    for row in snapshots:
        key = (str(row.get("venue")), str(row.get("model_provider")))
        if key not in latest_by_provider:
            latest_by_provider[key] = row

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in latest_by_provider.values():
        venue = str(row.get("venue"))
        account_ref = str(row.get("account_ref"))
        if row.get("status") != "ready":
            prior_success = next(
                (
                    candidate
                    for candidate in snapshots
                    if candidate.get("venue") == row.get("venue")
                    and candidate.get("model_provider") == row.get("model_provider")
                    and candidate.get("status") == "ready"
                ),
                None,
            )
            if prior_success is not None:
                account_ref = str(prior_success.get("account_ref"))
        grouped.setdefault((venue, account_ref), []).append(row)

    accounts: list[dict[str, Any]] = []
    for (venue, account_ref), latest_rows in grouped.items():
        providers = sorted({str(row.get("model_provider")) for row in latest_rows})
        all_account_rows = [
            row
            for row in snapshots
            if row.get("venue") == venue and row.get("account_ref") == account_ref
        ]
        successful = next((row for row in all_account_rows if row.get("status") == "ready"), None)
        latest_error = next((row for row in latest_rows if row.get("status") != "ready"), None)
        if successful is None:
            newest = latest_rows[0]
            accounts.append(
                {
                    "venue": venue,
                    "accountRef": account_ref,
                    "accountMode": str(newest.get("account_mode") or "unknown"),
                    "providers": providers,
                    "status": "unavailable",
                    "cashUsd": None,
                    "buyingPowerUsd": None,
                    "accountValueUsd": None,
                    "realizedPnlUsd": None,
                    "unrealizedPnlUsd": None,
                    "totalPnlUsd": None,
                    "openPositions": None,
                    "filledTrades": None,
                    "lastUpdatedAt": _isoformat(newest.get("observed_at")),
                    "message": str(newest.get("message") or "Venue account is unavailable."),
                    "_positions": [],
                }
            )
            continue
        stale = latest_error is not None and _datetime_or_min(latest_error.get("observed_at")) > _datetime_or_min(
            successful.get("observed_at")
        )
        positions = [
            _position_payload(row, providers)
            for row in position_rows
            if row.get("portfolio_snapshot_id") == successful.get("id")
        ]
        accounts.append(
            {
                "venue": venue,
                "accountRef": account_ref,
                "accountMode": str(successful.get("account_mode") or "unknown"),
                "providers": providers,
                "status": "stale" if stale else "ready",
                "cashUsd": _money_or_none(successful.get("cash_usd")),
                "buyingPowerUsd": _money_or_none(successful.get("buying_power_usd")),
                "accountValueUsd": _money_or_none(successful.get("account_value_usd")),
                "realizedPnlUsd": _money_or_none(successful.get("realized_pnl_usd")),
                "unrealizedPnlUsd": _money_or_none(successful.get("unrealized_pnl_usd")),
                "totalPnlUsd": _money_or_none(successful.get("total_pnl_usd")),
                "openPositions": int(successful.get("open_position_count") or 0),
                "filledTrades": int(successful.get("filled_trade_count") or 0),
                "lastUpdatedAt": _isoformat(successful.get("observed_at")),
                "message": str(
                    latest_error.get("message")
                    if stale and latest_error is not None
                    else successful.get("message") or "Confirmed from venue account API."
                ),
                "_positions": positions,
            }
        )
    accounts.sort(key=lambda row: (str(row["venue"]), str(row["accountRef"])))
    return accounts


def _aggregate_accounts(
    accounts: list[dict[str, Any]],
    *,
    venue: str | None = None,
) -> dict[str, Any]:
    available = [account for account in accounts if account["status"] in {"ready", "stale"}]
    if not available:
        payload: dict[str, Any] = {
            "status": "unavailable",
            "accountValueUsd": None,
            "realizedPnlUsd": None,
            "unrealizedPnlUsd": None,
            "totalPnlUsd": None,
            "openPositions": None,
            "filledTrades": None,
        }
    else:
        status = (
            "stale"
            if len(available) != len(accounts)
            or any(account["status"] == "stale" for account in available)
            else "ready"
        )
        payload = {
            "status": status,
            "accountValueUsd": _sum_money(available, "accountValueUsd"),
            "realizedPnlUsd": _sum_money(available, "realizedPnlUsd"),
            "unrealizedPnlUsd": _sum_money(available, "unrealizedPnlUsd"),
            "totalPnlUsd": _sum_money(available, "totalPnlUsd"),
            "openPositions": sum(int(account["openPositions"]) for account in available),
            "filledTrades": sum(int(account["filledTrades"]) for account in available),
        }
    if venue is not None:
        payload = {
            "venue": venue,
            "label": "Polymarket US" if venue == Venue.POLYMARKET_US.value else "Alpaca",
            **payload,
            "accounts": [{key: value for key, value in account.items() if key != "_positions"} for account in accounts],
        }
    return payload


def _portfolio_history(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(snapshots, key=lambda item: _datetime_or_min(item.get("observed_at"))):
        if row.get("status") == "ready":
            bucket_at = _datetime_or_min(row.get("observed_at")).replace(second=0, microsecond=0)
            buckets.setdefault(bucket_at.isoformat(), []).append(row)
    latest_by_account: dict[tuple[str, str], dict[str, Any]] = {}
    history: list[dict[str, Any]] = []
    for timestamp, bucket_rows in sorted(buckets.items()):
        for row in bucket_rows:
            account_key = (str(row.get("venue")), str(row.get("account_ref")))
            current = latest_by_account.get(account_key)
            if current is None or _datetime_or_min(row.get("observed_at")) >= _datetime_or_min(
                current.get("observed_at")
            ):
                latest_by_account[account_key] = row
        rows = list(latest_by_account.values())
        polymarket_rows = [row for row in rows if row.get("venue") == Venue.POLYMARKET_US.value]
        alpaca_rows = [row for row in rows if row.get("venue") == Venue.ALPACA.value]
        history.append(
            {
                "asOf": timestamp,
                "accountValueUsd": _sum_row_money(rows, "account_value_usd"),
                "totalPnlUsd": _sum_row_money(rows, "total_pnl_usd"),
                "polymarketUsPnlUsd": _sum_row_money(polymarket_rows, "total_pnl_usd"),
                "alpacaPnlUsd": _sum_row_money(alpaca_rows, "total_pnl_usd"),
            }
        )
    return history[-PORTFOLIO_HISTORY_BUCKET_LIMIT:]


def _position_payload(row: dict[str, Any], providers: list[str]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "venue": str(row.get("venue")),
        "providers": providers,
        "accountRef": str(row.get("account_ref")),
        "instrumentId": str(row.get("instrument_id")),
        "title": str(row.get("title")),
        "outcome": row.get("outcome"),
        "quantity": _decimal_text(row.get("quantity")),
        "averageEntryPrice": _money_or_none(row.get("average_entry_price")),
        "currentPrice": _money_or_none(row.get("current_price")),
        "costBasisUsd": _money_or_none(row.get("cost_basis_usd")),
        "marketValueUsd": _money_or_none(row.get("market_value_usd")),
        "realizedPnlUsd": _money_or_none(row.get("realized_pnl_usd")),
        "unrealizedPnlUsd": _money_or_none(row.get("unrealized_pnl_usd")),
        "totalPnlUsd": _money_or_none(row.get("total_pnl_usd")),
        "state": str(row.get("state")),
        "updatedAt": _isoformat(row.get("observed_at")),
    }


def _fill_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id")),
        "venue": str(row.get("venue")),
        "providers": sorted(str(provider) for provider in (row.get("providers") or [])),
        "accountRef": str(row.get("account_ref")),
        "sourceTradeId": str(row.get("source_trade_id")),
        "venueOrderId": row.get("venue_order_id"),
        "instrumentId": str(row.get("instrument_id")),
        "title": str(row.get("title")),
        "side": str(row.get("side")),
        "quantity": _decimal_text(row.get("quantity")),
        "price": _money(row.get("price")),
        "notionalUsd": _money(row.get("notional_usd")),
        "realizedPnlUsd": _money_or_none(row.get("realized_pnl_usd")),
        "feeUsd": _money_or_none(row.get("fee_usd")),
        "state": "filled",
        "executedAt": _isoformat(row.get("executed_at")),
    }


def _normalize_alpaca_position(row: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    return {
        "instrumentId": str(_field(row, "symbol") or "unknown").upper(),
        "title": str(_field(row, "symbol") or "Unknown").upper(),
        "outcome": None,
        "quantity": _decimal_or_zero(_field(row, "qty")),
        "averageEntryPrice": _decimal_or_none(_field(row, "avg_entry_price")),
        "currentPrice": _decimal_or_none(_field(row, "current_price")),
        "costBasisUsd": _decimal_or_none(_field(row, "cost_basis")),
        "marketValueUsd": _decimal_or_none(_field(row, "market_value")),
        "realizedPnlUsd": None,
        "unrealizedPnlUsd": _decimal_or_none(_field(row, "unrealized_pl")),
        "state": "open",
        "updatedAt": observed_at,
    }


def _normalize_alpaca_fill(row: dict[str, Any], observed_at: datetime) -> dict[str, Any]:
    quantity = abs(_decimal_or_zero(_field(row, "qty")))
    price = _decimal_or_zero(_field(row, "price"))
    return {
        "sourceTradeId": str(_field(row, "id") or ""),
        "venueOrderId": _text_or_none(_field(row, "order_id")),
        "instrumentId": str(_field(row, "symbol") or "unknown").upper(),
        "title": str(_field(row, "symbol") or "Unknown").upper(),
        "side": str(_field(row, "side") or "unknown").lower(),
        "quantity": quantity,
        "price": price,
        "notionalUsd": quantity * price,
        "realizedPnlUsd": None,
        "feeUsd": _decimal_or_none(_field(row, "fee")),
        "state": "filled",
        "executedAt": _datetime_or_now(_field(row, "transaction_time") or observed_at),
    }


def _latest_alpaca_profit_loss(history: dict[str, Any]) -> Decimal | None:
    values = _field(history, "profit_loss") or _field(history, "profitLoss") or []
    if isinstance(values, (list, tuple)):
        for value in reversed(values):
            parsed = _decimal_or_none(value)
            if parsed is not None:
                return parsed
    equity_values = _field(history, "equity") or []
    base_value = _decimal_or_none(
        _field(history, "base_value") or _field(history, "baseValue")
    )
    if isinstance(equity_values, (list, tuple)) and base_value is not None:
        for value in reversed(equity_values):
            equity = _decimal_or_none(value)
            if equity is not None:
                return equity - base_value
    return None


def _polymarket_identity_values(response: Any) -> list[str]:
    identities: set[str] = set()
    raw_accounts = _field(response, "accounts")
    if isinstance(raw_accounts, (list, tuple)):
        for account in raw_accounts:
            if isinstance(account, str) and account.strip():
                identities.add(account.strip())
                continue
            for field in ("accountId", "account_id", "account", "id"):
                value = str(_field(account, field) or "").strip()
                if value:
                    identities.add(value)
                    break
    if identities:
        return sorted(identities)
    for field in ("accountId", "account_id", "account", "user", "userId", "subject"):
        value = str(_field(response, field) or "").strip()
        if value:
            identities.add(value)
    return sorted(identities)


def _provider_env(
    runtime_env: dict[str, str],
    venue: Venue,
    provider: ModelProvider,
) -> dict[str, str]:
    result = dict(runtime_env)
    provider_key = provider.value.upper()
    if venue == Venue.POLYMARKET_US:
        result["POLYMARKET_KEY_ID"] = runtime_env.get(
            f"POLYMARKET_{provider_key}_KEY_ID", ""
        ).strip()
        result["POLYMARKET_SECRET_KEY"] = runtime_env.get(
            f"POLYMARKET_{provider_key}_SECRET_KEY", ""
        ).strip()
        result["POLYMARKET_PRIVATE_KEY"] = runtime_env.get(
            f"POLYMARKET_{provider_key}_PRIVATE_KEY", ""
        ).strip()
        result["POLYMARKET_ACCOUNT_ID"] = (
            runtime_env.get(f"POLYMARKET_{provider_key}_ACCOUNT_ID", "").strip()
            or runtime_env.get("POLYMARKET_ACCOUNT_ID", "").strip()
        )
    else:
        result["ALPACA_KEY_ID"] = runtime_env.get(f"ALPACA_{provider_key}_KEY_ID", "").strip()
        result["ALPACA_SECRET_KEY"] = runtime_env.get(
            f"ALPACA_{provider_key}_SECRET_KEY", ""
        ).strip()
    return result


def _unavailable_account(
    *,
    venue: Venue,
    provider: ModelProvider,
    account_ref: str,
    account_mode: str,
    observed_at: datetime,
    message: str,
    status: str = "unavailable",
) -> dict[str, Any]:
    return {
        "status": status,
        "venue": venue.value,
        "provider": provider.value,
        "accountRef": account_ref,
        "accountMode": account_mode,
        "positions": [],
        "fills": [],
        "observedAt": observed_at,
        "message": message,
    }


def _empty_summary(environment: Environment, now: datetime, message: str) -> dict[str, Any]:
    empty = _aggregate_accounts([])
    return {
        "environment": environment.value,
        "generatedAt": now.isoformat(),
        "overall": empty,
        "venues": [
            _aggregate_accounts([], venue=Venue.POLYMARKET_US.value),
            _aggregate_accounts([], venue=Venue.ALPACA.value),
        ],
        "accounts": [],
        "positions": [],
        "fills": [],
        "history": [],
        "freshness": {
            "status": "unavailable",
            "refreshedAt": None,
            "ageSeconds": None,
            "message": message,
        },
        "source": "venue-confirmed account APIs",
    }


def _freshness_message(status: str, age_seconds: int | None) -> str:
    if status == "unavailable":
        return "No confirmed venue portfolio snapshot is available yet."
    if status == "stale":
        return "One or more venue accounts could not be refreshed; confirmed values remain visible."
    if age_seconds is None:
        return "Venue portfolio freshness is unavailable."
    return f"Confirmed from venue account APIs {age_seconds} seconds ago."


def _fill_id(environment: str, venue: str, account_ref: str, source_trade_id: str) -> str:
    value = f"{environment}|{venue}|{account_ref}|{source_trade_id}"
    return sha256(value.encode("utf-8")).hexdigest()


def _account_ref(venue: Venue, public_identifier: str) -> str:
    return _account_ref_text(venue.value, public_identifier)


def _account_ref_text(venue: str, public_identifier: str) -> str:
    digest = sha256(f"{venue}|{public_identifier}".encode("utf-8")).hexdigest()
    return f"{venue}-{digest[:12]}"


def _alpaca_base_url(runtime_env: dict[str, str], account_mode: str) -> str:
    if account_mode == "live":
        value = runtime_env.get("ALPACA_LIVE_TRADING_BASE_URL", "https://api.alpaca.markets")
    else:
        value = runtime_env.get(
            "ALPACA_PAPER_TRADING_BASE_URL",
            "https://paper-api.alpaca.markets",
        )
    return str(runtime_env.get("ALPACA_TRADING_BASE_URL") or value).strip().rstrip("/")


def _response_json(response: httpx.Response, operation: str) -> Any:
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned invalid JSON") from exc


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, tuple):
        return [row for row in value if isinstance(row, dict)]
    return []


def _amount(value: Any) -> Decimal:
    return _amount_or_none(value) or Decimal("0")


def _amount_or_none(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        return _decimal_or_none(value.get("value"))
    return _decimal_or_none(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_or_zero(value: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    parsed = _decimal_or_none(value)
    return default if parsed is None else parsed


def _divide_or_none(value: Decimal, divisor: Decimal) -> Decimal | None:
    return value / divisor if divisor != 0 else None


def _datetime_or_now(value: Any) -> datetime:
    parsed = _datetime_or_none(value)
    return parsed or datetime.now(UTC)


def _datetime_or_min(value: Any) -> datetime:
    parsed = _datetime_or_none(value)
    return parsed or datetime.min.replace(tzinfo=UTC)


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _isoformat(value: Any) -> str | None:
    parsed = _datetime_or_none(value)
    return parsed.isoformat() if parsed else None


def _money(value: Any) -> str:
    return f"{_decimal_or_zero(value):.2f}"


def _money_or_none(value: Any) -> str | None:
    parsed = _decimal_or_none(value)
    return f"{parsed:.2f}" if parsed is not None else None


def _decimal_text(value: Any) -> str:
    parsed = _decimal_or_zero(value)
    return format(parsed.normalize(), "f") if parsed != 0 else "0"


def _sum_money(rows: list[dict[str, Any]], key: str) -> str | None:
    values = [_decimal_or_none(row.get(key)) for row in rows]
    available = [value for value in values if value is not None]
    return _money(sum(available, Decimal("0"))) if available else None


def _sum_row_money(rows: list[dict[str, Any]], key: str) -> str | None:
    values = [_decimal_or_none(row.get(key)) for row in rows]
    available = [value for value in values if value is not None]
    return _money(sum(available, Decimal("0"))) if available else None


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
