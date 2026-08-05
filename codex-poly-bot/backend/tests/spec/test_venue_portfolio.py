"""Spec tests for venue-confirmed portfolio reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
import httpx

from app.db import RepositoryRegistry
from app.domain import Environment, ModelProvider, Venue
from app.main import AppSettings, create_app
from app.services.venue_portfolio_service import (
    ProviderBackedVenuePortfolioSource,
    StaticVenuePortfolioSource,
    VenuePortfolioService,
)


class _FakePolymarketAccount:
    def balances(self) -> dict:
        return {
            "balances": [
                {
                    "currency": "USD",
                    "currentBalance": "100.00",
                    "buyingPower": "75.00",
                    "assetNotional": "30.00",
                }
            ]
        }


class _FakePolymarketPortfolio:
    def positions(self, _params: dict) -> dict:
        return {
            "positions": {
                "market-one": {
                    "netPosition": "2",
                    "netPositionDecimal": "2.5",
                    "cost": {"value": "20.00"},
                    "cashValue": {"value": "30.00"},
                    "realized": {"value": "4.00"},
                    "expired": False,
                    "marketMetadata": {"title": "Market one", "outcome": "Yes"},
                    "updateTime": "2026-07-13T12:00:00Z",
                }
            },
            "eof": True,
        }

    def activities(self, _params: dict) -> dict:
        return {
            "activities": [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "id": "pm-cleared",
                        "state": "CLEARED",
                        "marketSlug": "market-one",
                        "qty": "2",
                        "qtyDecimal": "2.5",
                        "price": {"value": "0.60"},
                        "costBasis": {"value": "9.99"},
                        "realizedPnl": {"value": "5.00"},
                        "updateTime": "2026-07-13T11:55:00Z",
                    },
                },
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "id": "pm-new",
                        "state": "TRADE_STATE_NEW",
                        "marketSlug": "market-one",
                        "qtyDecimal": "3",
                        "price": {"value": "0.80"},
                        "realizedPnl": {"value": "2.00"},
                    },
                },
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "id": "pm-busted",
                        "state": "BUSTED",
                        "marketSlug": "market-one",
                        "qtyDecimal": "50",
                        "price": {"value": "0.99"},
                        "realizedPnl": {"value": "99.00"},
                    },
                },
                {
                    "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
                    "positionResolution": {
                        "beforePosition": {"realized": {"value": "4.00"}},
                        "afterPosition": {"realized": {"value": "6.00"}},
                    },
                },
            ],
            "eof": True,
        }


class _FakePolymarketClient:
    def __init__(self) -> None:
        self.account = _FakePolymarketAccount()
        self.portfolio = _FakePolymarketPortfolio()

    def close(self) -> None:
        return None

    def get(self, path: str, *, authenticated: bool = False) -> dict:
        assert authenticated is True
        if path == "/v1/accounts":
            return {"accounts": ["firms/test/accounts/portfolio-one"]}
        return {}


def _ready_accounts() -> list[dict]:
    observed_at = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    polymarket = {
        "status": "ready",
        "venue": "polymarket_us",
        "provider": "openai",
        "accountRef": "polymarket-account-a",
        "accountMode": "live",
        "cashUsd": "100.00",
        "buyingPowerUsd": "75.00",
        "accountValueUsd": "130.00",
        "observedAt": observed_at,
        "positions": [
            {
                "instrumentId": "market-one",
                "title": "Will market one resolve yes?",
                "outcome": "Yes",
                "quantity": "20",
                "averageEntryPrice": "1.00",
                "currentPrice": "1.50",
                "costBasisUsd": "20.00",
                "marketValueUsd": "30.00",
                "unrealizedPnlUsd": "10.00",
                "state": "open",
                "updatedAt": observed_at,
            }
        ],
        "fills": [
            {
                "sourceTradeId": "pm-fill-1",
                "instrumentId": "market-one",
                "title": "Will market one resolve yes?",
                "side": "sell",
                "quantity": "5",
                "price": "1.20",
                "notionalUsd": "6.00",
                "realizedPnlUsd": "5.00",
                "state": "filled",
                "executedAt": observed_at - timedelta(minutes=5),
            }
        ],
    }
    shared_polymarket = {**polymarket, "provider": "claude"}
    alpaca = {
        "status": "ready",
        "venue": "alpaca",
        "provider": "openai",
        "_accountId": "alpaca-account-a",
        "_accountStatus": "ACTIVE",
        "_openOrderIds": [],
        "_marketClock": {
            "is_open": True,
            "timestamp": observed_at.isoformat(),
            "next_close": (observed_at + timedelta(hours=4)).isoformat(),
        },
        "accountRef": "alpaca-account-a",
        "accountMode": "paper",
        "cashUsd": "50.00",
        "buyingPowerUsd": "100.00",
        "accountValueUsd": "200.00",
        "realizedPnlUsd": "10.00",
        "totalPnlUsd": "20.00",
        "observedAt": observed_at,
        "positions": [
            {
                "instrumentId": "SPY",
                "title": "SPY",
                "outcome": None,
                "quantity": "1",
                "positionSide": "long",
                "averageEntryPrice": "100.00",
                "currentPrice": "110.00",
                "costBasisUsd": "100.00",
                "marketValueUsd": "110.00",
                "unrealizedPnlUsd": "10.00",
                "state": "open",
                "updatedAt": observed_at,
            }
        ],
        "fills": [
            {
                "sourceTradeId": "alpaca-fill-1",
                "instrumentId": "SPY",
                "title": "SPY",
                "side": "buy",
                "quantity": "2",
                "price": "100.00",
                "notionalUsd": "200.00",
                "realizedPnlUsd": None,
                "state": "filled",
                "executedAt": observed_at - timedelta(minutes=10),
            },
            {
                "sourceTradeId": "alpaca-fill-2",
                "instrumentId": "SPY",
                "title": "SPY",
                "side": "sell",
                "quantity": "1",
                "price": "110.00",
                "notionalUsd": "110.00",
                "realizedPnlUsd": None,
                "state": "filled",
                "executedAt": observed_at - timedelta(minutes=2),
            },
        ],
    }
    return [polymarket, shared_polymarket, alpaca]


def test_req_cmp_005_01_confirmed_portfolio_deduplicates_shared_accounts() -> None:
    """TST-REQ-CMP-005-01: confirmed venue data is aggregated once per account."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    source = StaticVenuePortfolioSource(_ready_accounts())
    service = VenuePortfolioService(app.state.services.registry, source=source)

    payload = service.refresh(Environment.DEVELOPMENT)

    assert payload["overall"] == {
        "status": "ready",
        "accountValueUsd": "330.00",
        "realizedPnlUsd": "15.00",
        "unrealizedPnlUsd": "20.00",
        "totalPnlUsd": "35.00",
        "openPositions": 2,
        "filledTrades": 3,
    }
    polymarket = next(row for row in payload["venues"] if row["venue"] == "polymarket_us")
    assert polymarket["accountValueUsd"] == "130.00"
    assert polymarket["accounts"][0]["providers"] == ["claude", "openai"]
    assert len(payload["positions"]) == 2
    assert len(payload["fills"]) == 3
    serialized = str(payload).lower()
    assert "secret" not in serialized
    assert "api-key" not in serialized
    assert "simulated" not in serialized


def test_req_db_008_01_reconciliation_persists_sanitized_venue_snapshots() -> None:
    """TST-REQ-DB-008-01: venue portfolio rows keep safe attribution fields."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    service = VenuePortfolioService(
        app.state.services.registry,
        source=StaticVenuePortfolioSource(_ready_accounts()),
    )

    service.refresh(Environment.DEVELOPMENT)

    state = app.state.services.registry.state
    snapshots = state.rows("shared.venue_portfolio_snapshots")
    positions = state.rows("shared.venue_position_snapshots")
    fills = state.rows("shared.venue_confirmed_fills")
    alpaca_registry = state.rows("shared.alpaca_account_registry")
    alpaca_positions = state.rows("shared.alpaca_historical_positions")
    alpaca_fills = state.rows("shared.alpaca_historical_fills")
    alpaca_reconciliation = state.rows("openai.alpaca_account_snapshots")
    assert len(snapshots) == 3
    assert len(positions) == 3
    assert len(fills) == 3
    assert {row["environment"] for row in snapshots} == {"development"}
    assert {row["venue"] for row in snapshots} == {"polymarket_us", "alpaca"}
    assert {row["model_provider"] for row in snapshots} == {"openai", "claude"}
    assert all(row["account_ref"] for row in snapshots)
    assert len(alpaca_registry) == 1
    assert alpaca_registry[0]["account_id"] == "alpaca-account-a"
    assert alpaca_positions[0]["quantity"] == 1
    assert {row["activity_id"] for row in alpaca_fills} == {
        "alpaca-fill-1",
        "alpaca-fill-2",
    }
    assert alpaca_reconciliation[0]["is_live_safe"] is False
    assert "broker and Postgres state mismatch" in alpaca_reconciliation[0]["mismatches"]
    assert alpaca_reconciliation[0]["broker_positions"] == {"SPY": "1"}
    assert alpaca_reconciliation[0]["postgres_positions"] == {"SPY": "1"}
    serialized = str(
        {
            "snapshots": snapshots,
            "positions": positions,
            "fills": fills,
            "alpaca_registry": alpaca_registry,
            "alpaca_positions": alpaca_positions,
            "alpaca_fills": alpaca_fills,
            "alpaca_reconciliation": alpaca_reconciliation,
        }
    ).lower()
    assert "secret" not in serialized
    assert "private_key" not in serialized


def test_req_db_008_02_account_refresh_rolls_back_partial_rows() -> None:
    """TST-REQ-DB-008-02: a failed account refresh is atomic."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    state = app.state.services.registry.state
    state.fail_on_tables.add("shared.venue_position_snapshots")
    service = VenuePortfolioService(
        app.state.services.registry,
        source=StaticVenuePortfolioSource([_ready_accounts()[0]]),
    )

    try:
        service.refresh(Environment.DEVELOPMENT)
    except Exception:
        pass
    else:
        raise AssertionError("portfolio refresh should fail when position persistence fails")

    assert state.rows("shared.venue_portfolio_snapshots") == []
    assert state.rows("shared.venue_confirmed_fills") == []


def test_req_ui_013_05_history_carries_forward_other_confirmed_accounts() -> None:
    """TST-REQ-UI-013-05: account history does not drop between refresh times."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    accounts = _ready_accounts()
    source = StaticVenuePortfolioSource([accounts[0]])
    service = VenuePortfolioService(app.state.services.registry, source=source)
    service.refresh(Environment.DEVELOPMENT)
    later_alpaca = {
        **accounts[2],
        "observedAt": accounts[2]["observedAt"] + timedelta(minutes=1),
    }
    source.accounts = [later_alpaca]

    payload = service.refresh(Environment.DEVELOPMENT)

    assert payload["history"][-1]["accountValueUsd"] == "330.00"
    assert payload["history"][-1]["totalPnlUsd"] == "35.00"


def test_req_ui_013_02_failed_refresh_keeps_last_confirmed_values_stale() -> None:
    """TST-REQ-UI-013-02: refresh failures retain prior confirmed account values."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    source = StaticVenuePortfolioSource([_ready_accounts()[0]])
    service = VenuePortfolioService(app.state.services.registry, source=source)
    service.refresh(Environment.DEVELOPMENT)
    source.accounts = [
        {
            "status": "error",
            "venue": "polymarket_us",
            "provider": "openai",
            "accountRef": "credential-fallback-ref",
            "accountMode": "live",
            "message": "Polymarket US portfolio request timed out.",
            "observedAt": datetime(2026, 7, 13, 12, 1, tzinfo=UTC),
            "positions": [],
            "fills": [],
        }
    ]

    payload = service.refresh(Environment.DEVELOPMENT)

    assert payload["overall"]["accountValueUsd"] == "130.00"
    assert payload["overall"]["status"] == "stale"
    assert payload["accounts"][0]["status"] == "stale"
    assert "timed out" in payload["accounts"][0]["message"]
    assert payload["freshness"]["refreshedAt"] == "2026-07-13T12:00:00+00:00"


def test_req_cmp_005_02_missing_portfolio_is_unavailable_not_zero() -> None:
    """TST-REQ-CMP-005-02: no confirmed account data produces unavailable metrics."""

    app = create_app(AppSettings(environment=Environment.DEVELOPMENT))
    service = VenuePortfolioService(
        app.state.services.registry,
        source=StaticVenuePortfolioSource([]),
    )

    payload = service.summary(Environment.DEVELOPMENT)

    assert payload["overall"]["status"] == "unavailable"
    assert payload["overall"]["accountValueUsd"] is None
    assert payload["overall"]["totalPnlUsd"] is None
    assert payload["overall"]["openPositions"] is None
    assert payload["overall"]["filledTrades"] is None


def test_req_ui_013_01_authenticated_portfolio_api_is_environment_scoped() -> None:
    """TST-REQ-UI-013-01: authenticated API returns only the selected environment."""

    settings = AppSettings(
        allowed_usernames=("yaw",),
        signing_secret="test-secret",
        environment=Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    app.state.services.runtime_status.venue_portfolio.source = StaticVenuePortfolioSource(
        [_ready_accounts()[0]]
    )
    app.state.services.runtime_status.refresh_venue_portfolio(Environment.DEVELOPMENT)
    token = app.state.services.auth.create_session_token(username="yaw")
    client = TestClient(app)

    denied = client.get("/api/portfolio")
    response = client.get(
        "/api/portfolio",
        headers={"Authorization": f"Bearer {token}", "X-Environment": "development"},
    )

    assert denied.status_code == 401
    assert response.status_code == 200
    assert response.json()["environment"] == "development"
    assert response.json()["venues"][0]["venue"] == "polymarket_us"


def test_req_ui_013_04_provider_source_normalizes_confirmed_venue_data() -> None:
    """TST-REQ-UI-013-04: source adapters use confirmed venue account data."""

    def alpaca_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["APCA-API-KEY-ID"] == "alpaca-openai-key"
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={
                    "id": "alpaca-account-one",
                    "status": "ACTIVE",
                    "cash": "50.00",
                    "buying_power": "100.00",
                    "portfolio_value": "200.00",
                    "created_at": "2025-07-13T12:00:00Z",
                },
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "SPY",
                        "side": "long",
                        "qty": "1.25",
                        "avg_entry_price": "100.00",
                        "current_price": "110.00",
                        "cost_basis": "125.00",
                        "market_value": "137.50",
                        "unrealized_pl": "12.50",
                    }
                ],
            )
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[])
        if request.url.path == "/v2/clock":
            return httpx.Response(
                200,
                json={
                    "is_open": True,
                    "timestamp": "2026-07-13T12:00:00Z",
                    "next_close": "2026-07-13T20:00:00Z",
                },
            )
        if request.url.path == "/v2/account/activities/FILL":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "alpaca-fill-one",
                        "order_id": "alpaca-order-one",
                        "symbol": "SPY",
                        "side": "buy",
                        "qty": "1.25",
                        "price": "100.00",
                        "transaction_time": "2026-07-13T11:50:00Z",
                    }
                ],
            )
        if request.url.path == "/v2/account/portfolio/history":
            assert request.url.params["timeframe"] == "1D"
            assert request.url.params["cashflow_types"] == "ALL"
            return httpx.Response(
                200,
                json={
                    "timestamp": [1752408000],
                    "equity": ["200.00"],
                    "profit_loss": ["20.00"],
                    "base_value": "180.00",
                },
            )
        return httpx.Response(404)

    source = ProviderBackedVenuePortfolioSource(
        {
            "POLYMARKET_OPENAI_KEY_ID": "pm-openai-key",
            "POLYMARKET_OPENAI_SECRET_KEY": "pm-openai-secret",
            "ALPACA_OPENAI_KEY_ID": "alpaca-openai-key",
            "ALPACA_OPENAI_SECRET_KEY": "alpaca-openai-secret",
            "TRADING_ACCOUNT_MODE": "paper",
        },
        polymarket_client_factory=lambda _env: _FakePolymarketClient(),
        alpaca_transport=httpx.MockTransport(alpaca_handler),
    )

    accounts = source.fetch_accounts(Environment.PRODUCTION)
    polymarket = next(
        row
        for row in accounts
        if row["venue"] == "polymarket_us" and row["provider"] == "openai"
    )
    alpaca = next(
        row
        for row in accounts
        if row["venue"] == "alpaca" and row["provider"] == "openai"
    )

    assert polymarket["accountValueUsd"] == 130
    assert polymarket["realizedPnlUsd"] == 7
    assert polymarket["positions"][0]["quantity"] == 2.5
    assert polymarket["fills"][0]["quantity"] == 2.5
    assert [fill["sourceTradeId"] for fill in polymarket["fills"]] == ["pm-cleared"]
    assert polymarket["fills"][0]["notionalUsd"] == 1.5
    assert alpaca["accountValueUsd"] == 200
    assert alpaca["realizedPnlUsd"] == 7.5
    assert alpaca["totalPnlUsd"] == 20
    assert alpaca["positions"][0]["quantity"] == 1.25
    assert alpaca["fills"][0]["sourceTradeId"] == "alpaca-fill-one"
    registry = RepositoryRegistry()
    alpaca["_orderStates"] = {"alpaca-canceled-order": "canceled"}
    alpaca["_openOrderIds"] = ["alpaca-partial-order"]
    alpaca["fills"].append(
        {
            "sourceTradeId": "alpaca-partial-fill",
            "venueOrderId": "alpaca-partial-order",
            "instrumentId": "SPY",
            "title": "SPY",
            "side": "sell",
            "quantity": Decimal("0.5"),
            "price": Decimal("110"),
            "notionalUsd": Decimal("55"),
            "realizedPnlUsd": None,
            "state": "filled",
            "executedAt": datetime.now(UTC),
        }
    )
    shared = registry.shared()
    for venue_order_id in (
        "alpaca-order-one",
        "alpaca-canceled-order",
        "alpaca-partial-order",
    ):
        shared.record_order_intent(
            environment=Environment.PRODUCTION,
            execution_run_id=f"execution-{venue_order_id}",
            pipeline_run_id=f"pipeline-{venue_order_id}",
            strategy_consensus_output_id=None,
            venue=Venue.ALPACA.value,
            instrument_id="alpaca:SPY",
            model_provider=ModelProvider.OPENAI,
            side="sell",
            order_type="market",
            status="submitted",
            notional_usd=Decimal("100"),
            size_multiplier=Decimal("1"),
            idempotency_key=f"client-{venue_order_id}",
            risk_payload={},
            source_payload={},
            venue_order_id=venue_order_id,
        )
    VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource(accounts),
    ).refresh(Environment.PRODUCTION)
    registrations = registry.state.rows("shared.alpaca_account_registry")
    execution_positions = registry.state.rows("shared.alpaca_historical_positions")
    execution_fills = registry.state.rows("shared.alpaca_historical_fills")
    reconciliation = registry.state.rows("openai.alpaca_account_snapshots")
    reconciled_intents = registry.state.rows("shared.order_intents")
    assert registrations[0]["account_id"] == "alpaca-account-one"
    assert execution_positions[0]["quantity"] == 1.25
    assert execution_fills[0]["activity_id"] == "alpaca-fill-one"
    assert {
        row["venue_order_id"]: row["status"] for row in reconciled_intents
    } == {
        "alpaca-order-one": "filled",
        "alpaca-canceled-order": "canceled",
        "alpaca-partial-order": "submitted",
    }
    assert reconciliation[0]["is_live_safe"] is True
    serialized = str(accounts)
    assert "pm-openai-secret" not in serialized
    assert "alpaca-openai-secret" not in serialized


def test_req_cmp_005_03_provider_source_uses_venue_account_identity() -> None:
    """TST-REQ-CMP-005-03: shared Polymarket credentials resolve to one account."""

    source = ProviderBackedVenuePortfolioSource(
        {
            "POLYMARKET_OPENAI_KEY_ID": "pm-openai-key",
            "POLYMARKET_OPENAI_SECRET_KEY": "pm-openai-secret",
            "POLYMARKET_CLAUDE_KEY_ID": "pm-claude-key",
            "POLYMARKET_CLAUDE_SECRET_KEY": "pm-claude-secret",
        },
        polymarket_client_factory=lambda _env: _FakePolymarketClient(),
    )

    accounts = [
        row
        for row in source.fetch_accounts(Environment.PRODUCTION)
        if row["venue"] == "polymarket_us"
    ]

    assert [row["status"] for row in accounts] == ["ready", "ready"]
    assert accounts[0]["accountRef"] == accounts[1]["accountRef"]


def test_req_obs_005_polymarket_identity_fallback_does_not_repeat_failed_probes() -> None:
    """TST-REQ-OBS-005-13: unsupported identity probes run once per credential ref."""

    class MissingIdentityEndpoints:
        def __init__(self) -> None:
            self.paths: list[str] = []

        def get(self, path: str, *, authenticated: bool = False) -> dict:
            assert authenticated is True
            self.paths.append(path)
            raise RuntimeError("endpoint unavailable")

    source = ProviderBackedVenuePortfolioSource({})
    client = MissingIdentityEndpoints()

    first = source._polymarket_account_ref(
        client,
        provider_env={},
        balances=[],
        fallback_ref="polymarket:fallback",
    )
    second = source._polymarket_account_ref(
        client,
        provider_env={},
        balances=[],
        fallback_ref="polymarket:fallback",
    )

    assert first == "polymarket:fallback"
    assert second == first
    assert client.paths == ["/v1/accounts", "/v1/whoami"]


def test_req_ui_013_07_polymarket_missing_buying_power_preserves_cash_fallback() -> None:
    """TST-REQ-UI-013-07: missing buying power remains absent so cash can be used."""

    class CashOnlyAccount:
        def balances(self) -> dict:
            return {
                "balances": [
                    {
                        "currency": "USD",
                        "currentBalance": "42.50",
                        "assetNotional": "30.00",
                    }
                ]
            }

    def client_factory(_env: dict) -> _FakePolymarketClient:
        client = _FakePolymarketClient()
        client.account = CashOnlyAccount()
        return client

    source = ProviderBackedVenuePortfolioSource(
        {
            "POLYMARKET_OPENAI_KEY_ID": "pm-openai-key",
            "POLYMARKET_OPENAI_SECRET_KEY": "pm-openai-secret",
        },
        polymarket_client_factory=client_factory,
    )

    account = next(
        row
        for row in source.fetch_accounts(Environment.PRODUCTION)
        if row["venue"] == "polymarket_us" and row["provider"] == "openai"
    )

    assert account["cashUsd"] == 42.5
    assert account["buyingPowerUsd"] is None
