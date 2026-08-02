"""Specification tests for the Kalshi venue integration.

REQ: REQ-KAL-001, REQ-KAL-002, REQ-KAL-003, REQ-KAL-004,
REQ-KAL-005, REQ-KAL-006, REQ-KAL-007, REQ-KAL-010
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import parse_qs

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import RepositoryRegistry
from app.domain import (
    Environment,
    ExitTrigger,
    ExitTriggerType,
    Instrument,
    InstrumentType,
    ModelProvider,
    Venue,
    supported_venues,
)
from app.main import AppSettings, create_app
from app.services.config_service import default_config_payload
from app.services.market_data_provider import (
    MarketDataProviderResult,
    ProviderBackedMarketDataFetcher,
)
from app.services.scanner_service import ScannerService
from app.services.venue_portfolio_service import (
    ProviderBackedVenuePortfolioSource,
    StaticVenuePortfolioSource,
    VenuePortfolioService,
)
from app.services.execution_service import KalshiExecutionRequest, execute_kalshi_order
from app.services.lifecycle_service import (
    PipelineLifecycleService,
    _kalshi_order_request,
    _kalshi_worst_case_fee,
)
from app.services.risk_engine import KalshiLiveOrderGateInput, evaluate_kalshi_live_order_gates
from app.venues.kalshi import (
    KALSHI_DEMO_API_BASE_URL,
    KALSHI_PRODUCTION_API_BASE_URL,
    KalshiAuthSigner,
    KalshiCredentials,
    KalshiLiveOrderAdapter,
    KalshiLiveOrderRequest,
    KalshiOrderOutcome,
    KalshiOrderResult,
    kalshi_live_order_adapter_from_env,
)
from app.venues.polymarket import VenueCallResult


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _test_credentials() -> tuple[KalshiCredentials, rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return KalshiCredentials(key_id="test-key-id", private_key_pem=pem), private_key


def test_req_kal_001_01_domain_config_and_settings_expose_disabled_kalshi(monkeypatch) -> None:
    """TST-REQ-KAL-001-01, TST-REQ-KAL-001-02: Kalshi is explicit and fail closed."""

    assert Venue.KALSHI in supported_venues()
    instrument = Instrument(
        venue=Venue.KALSHI,
        instrument_type=InstrumentType.PREDICTION_MARKET,
        display_name="Will the target be reached? - Yes",
        market_id="TEST-26",
        outcome_id="YES",
    )
    assert instrument.identifier == "TEST-26:YES"

    payload = default_config_payload()
    assert payload["venues"][Venue.KALSHI.value]["enabled"] is False
    assert payload["risk"][Venue.KALSHI.value]["max_position_usd"] == "25.00"
    assert payload["scanner"][Venue.KALSHI.value]["market_data_limit"] == 100

    monkeypatch.setenv("KALSHI_ENABLED", "true")
    monkeypatch.setenv("KALSHI_ENVIRONMENT", "demo")
    settings = AppSettings.from_env()
    assert settings.kalshi_enabled is True
    assert settings.kalshi_environment == "demo"


def test_req_kal_001_02_disabled_kalshi_quotes_do_not_reach_scoring() -> None:
    """TST-REQ-KAL-001-02: exit quotes bypass scanning while Kalshi is disabled."""

    now = datetime.now(UTC)
    registry = RepositoryRegistry()
    result = ScannerService(registry).run(
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="disabled-kalshi-scan",
        trigger="scheduled",
        market_data_pulls=[
            {
                "id": "disabled-kalshi-pull",
                "venue": Venue.KALSHI.value,
                "status": "pulled",
                "candidates": [
                    {
                        "id": "kalshi:HELD-26:YES",
                        "venue": Venue.KALSHI.value,
                        "marketId": "HELD-26",
                        "outcomeId": "YES",
                        "market": "Held position - YES",
                        "midpoint": "0.50",
                        "bestBid": "0.49",
                        "bestAsk": "0.51",
                        "bidDepth": "100",
                        "askDepth": "100",
                        "liquidity": "200",
                        "spread": "0.02",
                        "volume": "1000",
                        "endDate": "2026-08-10T12:00:00Z",
                        "active": True,
                    }
                ],
            }
        ],
        config_payload=default_config_payload(),
        started_at=now,
        completed_at=now,
    )

    assert result.payload["candidateCount"] == 0
    assert result.payload["acceptedCount"] == 0
    assert registry.state.rows("shared.scanner_candidates") == []


def test_req_kal_004_01_signature_uses_timestamp_method_and_path_without_query() -> None:
    """TST-REQ-KAL-004-01: signatures verify against the documented message."""

    credentials, private_key = _test_credentials()
    signer = KalshiAuthSigner(credentials)

    headers = signer.headers(
        "get",
        "/trade-api/v2/portfolio/orders?status=resting",
        timestamp_ms=1_786_000_000_123,
    )

    assert headers["KALSHI-ACCESS-KEY"] == "test-key-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1786000000123"
    signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
    private_key.public_key().verify(
        signature,
        b"1786000000123GET/trade-api/v2/portfolio/orders",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_req_kal_004_02_factory_isolates_demo_and_production_credentials() -> None:
    """TST-REQ-KAL-004-02, TST-REQ-KAL-004-03: factories isolate environments."""

    credentials, _ = _test_credentials()
    demo = kalshi_live_order_adapter_from_env(
        {
            "APP_ENV": Environment.DEVELOPMENT.value,
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_KEY_ID": credentials.key_id,
            "KALSHI_PRIVATE_KEY": credentials.private_key_pem,
        }
    )
    production = kalshi_live_order_adapter_from_env(
        {
            "APP_ENV": Environment.PRODUCTION.value,
            "KALSHI_ENVIRONMENT": "production",
            "KALSHI_KEY_ID": credentials.key_id,
            "KALSHI_PRIVATE_KEY": credentials.private_key_pem,
        }
    )

    assert demo.base_url == KALSHI_DEMO_API_BASE_URL
    assert production.base_url == KALSHI_PRODUCTION_API_BASE_URL

    try:
        kalshi_live_order_adapter_from_env(
            {
                "APP_ENV": Environment.PRODUCTION.value,
                "KALSHI_ENVIRONMENT": "demo",
                "KALSHI_KEY_ID": credentials.key_id,
                "KALSHI_PRIVATE_KEY": credentials.private_key_pem,
            }
        )
    except ValueError as exc:
        assert "environment" in str(exc).lower()
        assert credentials.private_key_pem not in str(exc)
    else:
        raise AssertionError("production must refuse demo Kalshi routing")


def test_req_kal_004_04_authenticated_credential_rejection_is_sanitized() -> None:
    """TST-REQ-KAL-004-04: timestamp skew blocks reads and mutations safely."""

    credentials, _ = _test_credentials()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(
            401,
            json={"detail": "timestamp outside allowed window: sensitive venue detail"},
        )

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    read_result = adapter.balance()
    submit_result = adapter.submit_order(
        KalshiLiveOrderRequest(
            ticker="TEST-26",
            side="bid",
            count=Decimal("1.00"),
            price=Decimal("0.5000"),
            client_order_id="timestamp-skew-intent",
            price_ranges=({"start": "0.0000", "end": "1.0000", "step": "0.0001"},),
        )
    )

    assert read_result.ok is False
    assert read_result.refusal_reason == "kalshi_credentials_rejected"
    assert submit_result.outcome == KalshiOrderOutcome.REFUSED
    assert submit_result.safe_error_code == "kalshi_credentials_rejected"
    assert methods == ["GET", "GET"]
    assert "sensitive venue detail" not in str(read_result)
    assert "sensitive venue detail" not in str(submit_result)


def test_req_kal_005_01_v2_submit_preserves_fixed_point_fields_and_client_id() -> None:
    """TST-REQ-KAL-005-01: one valid V2 mutation contains required fields."""

    credentials, _ = _test_credentials()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        return httpx.Response(
            201,
            json={
                "order_id": "order-1",
                "client_order_id": "intent-1",
                "fill_count": "2.50",
                "remaining_count": "0.00",
                "ts_ms": 1_786_000_000_123,
            },
        )

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = adapter.submit_order(
        KalshiLiveOrderRequest(
            ticker="TEST-26",
            side="bid",
            count=Decimal("2.50"),
            price=Decimal("0.4375"),
            client_order_id="intent-1",
            price_ranges=({"start": "0.0000", "end": "1.0000", "step": "0.0001"},),
        )
    )

    assert result.ok
    mutations = [request for request in seen if request.method == "POST"]
    assert len(mutations) == 1
    body = json.loads(mutations[0].content)
    assert body == {
        "cancel_order_on_pause": True,
        "client_order_id": "intent-1",
        "count": "2.50",
        "exchange_index": 0,
        "post_only": False,
        "price": "0.4375",
        "reduce_only": False,
        "self_trade_prevention_type": "taker_at_cross",
        "side": "bid",
        "ticker": "TEST-26",
        "time_in_force": "immediate_or_cancel",
        "subaccount": 0,
    }


def test_req_kal_006_02_malformed_success_is_unknown_and_unknown_cancel_state_is_safe() -> None:
    """TST-REQ-KAL-006-02: malformed mutation success never becomes confirmed state."""

    credentials, _ = _test_credentials()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if request.method == "POST":
            return httpx.Response(201, json={"order_id": "missing-required-v2-fields"})
        return httpx.Response(
            200,
            json={"order": {"order_id": "order-unknown-state", "status": "mystery"}},
        )

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    submit = adapter.submit_order(
        KalshiLiveOrderRequest(
            ticker="TEST-26",
            side="bid",
            count="1.00",
            price="0.45",
            client_order_id="malformed-success",
            price_ranges=({"start": "0.00", "end": "1.00", "step": "0.01"},),
        )
    )
    cancel = adapter.cancel_order("order-unknown-state")

    assert submit.outcome == KalshiOrderOutcome.UNKNOWN_SUBMIT
    assert submit.safe_error_code == "kalshi_submit_response_malformed"
    assert cancel.refusal_reason == "kalshi_order_not_cancelable"
    assert methods == ["GET", "POST", "GET"]


def test_req_kal_005_02_invalid_order_refuses_before_network() -> None:
    """TST-REQ-KAL-005-02: invalid fixed-point orders do not call Kalshi."""

    credentials, _ = _test_credentials()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = adapter.submit_order(
        KalshiLiveOrderRequest(
            ticker="TEST-26",
            side="bid",
            count=Decimal("0"),
            price=Decimal("1.01"),
            client_order_id="intent-2",
        )
    )

    assert not result.ok
    assert calls == 0


def test_req_kal_005_03_market_and_limit_translation_reserve_fees_and_align_steps() -> None:
    """TST-REQ-KAL-005-03: limit semantics, fee reserve, and side-safe steps are exact."""

    candidate = {
        "ticker": "TEST-26",
        "outcome": "YES",
        "bestBid": "0.44",
        "bestAsk": "0.45",
        "price": "0.445",
        "priceRanges": [{"start": "0.00", "end": "1.00", "step": "0.01"}],
        "feeType": "quadratic",
        "feeMultiplier": "1",
    }
    config = default_config_payload()
    market_order = _kalshi_order_request(
        candidate=candidate,
        idempotency_key="intent-market",
        notional=Decimal("10.00"),
        entering=True,
        order_type="market",
        config_payload=config,
    )
    limit_order = _kalshi_order_request(
        candidate=candidate,
        idempotency_key="intent-limit",
        notional=Decimal("10.00"),
        entering=True,
        order_type="limit",
        config_payload=config,
    )
    unsupported_fee = _kalshi_order_request(
        candidate={**candidate, "feeType": "flat"},
        idempotency_key="intent-unsupported-fee",
        notional=Decimal("10.00"),
        entering=True,
        order_type="market",
        config_payload=config,
    )

    assert isinstance(market_order, KalshiLiveOrderRequest)
    assert market_order.price == Decimal("0.47")
    assert market_order.time_in_force == "immediate_or_cancel"
    assert market_order.count == Decimal("20.06")
    assert (
        market_order.count * market_order.price
        + _kalshi_worst_case_fee(
            count=market_order.count,
            price=market_order.price,
            fee_multiplier=Decimal("1"),
        )
        <= Decimal("10.00")
    )
    assert isinstance(limit_order, KalshiLiveOrderRequest)
    assert limit_order.price == Decimal("0.44")
    assert limit_order.time_in_force == "good_till_canceled"
    assert limit_order.market_style is False
    assert unsupported_fee == "KALSHI_FEE_CONFIG_UNAVAILABLE"


def test_req_kal_006_01_submit_timeout_is_not_retried_and_preserves_client_id() -> None:
    """TST-REQ-KAL-006-01: an ambiguous POST is sent once and remains reconcilable."""

    credentials, _ = _test_credentials()
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        post_calls += 1
        raise httpx.ReadTimeout("private material must not be echoed", request=request)

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = adapter.submit_order(
        KalshiLiveOrderRequest(
            ticker="TEST-26",
            side="ask",
            count="1",
            price="0.51",
            client_order_id="intent-ambiguous",
            price_ranges=({"start": "0.00", "end": "1.00", "step": "0.01"},),
        )
    )

    assert not result.ok
    assert post_calls == 1
    assert result.payload["outcome"] == "unknown_submit"
    assert result.payload["client_order_id"] == "intent-ambiguous"
    assert "private material" not in str(result)


def test_req_kal_006_03_unknown_client_id_reconciles_through_historical_orders() -> None:
    """TST-REQ-KAL-006-03: client IDs resolve uniquely across live and historical orders."""

    credentials, _ = _test_credentials()
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert parse_qs(request.url.query.decode())["subaccount"] == ["0"]
        if request.url.path.endswith("/portfolio/orders"):
            return httpx.Response(200, json={"orders": [], "cursor": ""})
        return httpx.Response(
            200,
            json={
                "orders": [
                    {
                        "order_id": "historical-order-1",
                        "client_order_id": "intent-reconcile",
                        "ticker": "TEST-26",
                        "status": "executed",
                    }
                ],
                "cursor": "",
            },
        )

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    result = adapter.find_order_by_client_order_id(
        "intent-reconcile",
        ticker="TEST-26",
    )

    assert result.ok
    assert result.payload["order"]["order_id"] == "historical-order-1"
    assert paths == [
        "/trade-api/v2/portfolio/orders",
        "/trade-api/v2/historical/orders",
    ]


def test_req_kal_011_02_ambiguous_cancel_requires_a_new_read_before_later_delete() -> None:
    """TST-REQ-KAL-011-02: each bounded DELETE is preceded by a fresh GET."""

    credentials, _ = _test_credentials()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"order": {"order_id": "order-cancel", "status": "resting"}},
            )
        raise httpx.ReadTimeout("ambiguous delete", request=request)

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    first = adapter.cancel_order("order-cancel")
    second = adapter.cancel_order("order-cancel")

    assert first.refusal_reason == "kalshi_cancel_unknown"
    assert second.refusal_reason == "kalshi_cancel_unknown"
    assert methods == ["GET", "DELETE", "GET", "DELETE"]


def test_req_kal_011_02_malformed_cancel_success_remains_unknown() -> None:
    """TST-REQ-KAL-011-02: malformed V2 DELETE success is not confirmed."""

    credentials, _ = _test_credentials()
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"order": {"order_id": "order-cancel", "status": "resting"}},
            )
        return httpx.Response(200, json={"order_id": "order-cancel"})

    result = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ).cancel_order("order-cancel")

    assert result.refusal_reason == "kalshi_cancel_unknown"
    assert result.payload["unknown"] is True
    assert methods == ["GET", "DELETE"]


def test_req_kal_002_01_market_ingestion_paginates_and_batches_books() -> None:
    """TST-REQ-KAL-002-01, TST-REQ-KAL-002-02: binary markets normalize exactly."""

    market_calls = 0
    book_batches: list[list[str]] = []
    credentials, _ = _test_credentials()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal market_calls
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if request.url.path.endswith("/markets/orderbooks"):
            query = parse_qs(request.url.query.decode())
            tickers = query["tickers"]
            book_batches.append(tickers)
            return httpx.Response(
                200,
                json={
                    "orderbooks": [
                        {
                            "ticker": ticker,
                            "orderbook_fp": {
                                "yes_dollars": [["0.4375", "12.50"]],
                                "no_dollars": [["0.5500", "9.25"]],
                            },
                        }
                        for ticker in tickers
                    ]
                },
            )
        if "/events/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "event": {
                        "event_ticker": request.url.path.rsplit("/", 1)[-1],
                        "series_ticker": "TEST-SERIES",
                        "fee_type_override": None,
                        "fee_multiplier_override": None,
                    }
                },
            )
        if "/series/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "series": {
                        "ticker": "TEST-SERIES",
                        "fee_type": "quadratic",
                        "fee_multiplier": 1,
                    }
                },
            )
        market_calls += 1
        cursor = parse_qs(request.url.query.decode()).get("cursor", [""])[0]
        ticker = "TEST-A" if not cursor else "TEST-B"
        return httpx.Response(
            200,
            json={
                "markets": [
                    {
                        "ticker": ticker,
                        "event_ticker": f"EVENT-{ticker}",
                        "title": f"{ticker} question",
                        "market_type": "binary",
                        "status": "active",
                        "yes_bid_dollars": "0.1000",
                        "yes_ask_dollars": "0.9000",
                        "no_bid_dollars": "0.1000",
                        "no_ask_dollars": "0.9000",
                        "volume_fp": "21.75",
                        "open_interest_fp": "18.25",
                        "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0001"}],
                        "close_time": "2026-08-10T12:00:00Z",
                    }
                ],
                "cursor": "next" if not cursor else "",
            },
        )

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_MARKET_DATA_LIMIT": "100",
            "KALSHI_MARKET_PAGE_SIZE": "1",
            "KALSHI_MARKET_DATA_KEY_ID": credentials.key_id,
            "KALSHI_MARKET_DATA_PRIVATE_KEY": credentials.private_key_pem,
        },
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    assert result.status == "pulled"
    assert market_calls == 2
    assert book_batches == [["TEST-A", "TEST-B"]]
    assert len(result.candidates) == 4
    yes = next(item for item in result.candidates if item["id"] == "kalshi:TEST-A:YES")
    no = next(item for item in result.candidates if item["id"] == "kalshi:TEST-A:NO")
    assert yes["price"] == "0.44375"
    assert yes["bestBid"] == "0.4375"
    assert yes["bestAsk"] == "0.4500"
    assert yes["bidDepth"] == "5.468750"
    assert no["price"] == "0.55625"
    assert no["bestBid"] == "0.5500"
    assert yes["feeType"] == "quadratic"
    assert yes["feeMultiplier"] == "1"


def test_req_kal_002_03_public_summaries_without_auth_are_not_live_eligible() -> None:
    """TST-REQ-KAL-002-03: missing read credentials never trigger unsigned book reads."""

    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        return httpx.Response(
            200,
            json={
                "markets": [
                    {
                        "ticker": "TEST-A",
                        "title": "Test question",
                        "market_type": "binary",
                        "status": "active",
                    }
                ],
                "cursor": "",
            },
        )

    fetcher = ProviderBackedMarketDataFetcher(
        environ={"KALSHI_ENVIRONMENT": "demo"},
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    assert paths == ["/trade-api/v2/exchange/status", "/trade-api/v2/markets"]
    assert result.status == "partial"
    assert result.error_code == "kalshi_market_data_credentials_missing"
    assert result.candidates == []


def test_req_kal_001_02_disabled_position_pull_fetches_exact_held_ticker() -> None:
    """TST-REQ-KAL-001-02: disabled reconciliation targets confirmed exposure."""

    credentials, _ = _test_credentials()
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        paths.append(path)
        if path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if path.endswith("/markets/HELD-26"):
            return httpx.Response(
                200,
                json={
                    "market": {
                        "ticker": "HELD-26",
                        "event_ticker": "HELD-EVENT",
                        "title": "Held question",
                        "market_type": "binary",
                        "status": "active",
                        "price_ranges": [
                            {"start": "0.0000", "end": "1.0000", "step": "0.0001"}
                        ],
                    }
                },
            )
        if path.endswith("/markets/orderbooks"):
            assert parse_qs(request.url.query.decode())["tickers"] == ["HELD-26"]
            return httpx.Response(
                200,
                json={
                    "orderbooks": [
                        {
                            "ticker": "HELD-26",
                            "orderbook_fp": {
                                "yes_dollars": [["0.4900", "10.00"]],
                                "no_dollars": [["0.4900", "10.00"]],
                            },
                        }
                    ]
                },
            )
        if "/events/" in path:
            return httpx.Response(
                200,
                json={"event": {"event_ticker": "HELD-EVENT", "series_ticker": "HELD-SERIES"}},
            )
        if "/series/" in path:
            return httpx.Response(
                200,
                json={
                    "series": {
                        "ticker": "HELD-SERIES",
                        "fee_type": "quadratic",
                        "fee_multiplier": 1,
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    config = default_config_payload()
    config["_kalshi_required_tickers"] = ["HELD-26"]
    result = ProviderBackedMarketDataFetcher(
        environ={
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_MARKET_DATA_KEY_ID": credentials.key_id,
            "KALSHI_MARKET_DATA_PRIVATE_KEY": credentials.private_key_pem,
        },
        transport=httpx.MockTransport(handler),
    ).fetch(
        venue=Venue.KALSHI.value,
        config_payload=config,
        pulled_at=datetime.now(UTC),
    )

    assert result.status == "pulled"
    assert {candidate["ticker"] for candidate in result.candidates} == {"HELD-26"}
    assert "/trade-api/v2/markets" not in paths


def test_req_kal_003_02_empty_required_market_data_has_stable_code() -> None:
    """TST-REQ-KAL-003-02: an empty required market result fails closed explicitly."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        return httpx.Response(200, json={"markets": [], "cursor": ""})

    result = ProviderBackedMarketDataFetcher(
        environ={"KALSHI_ENVIRONMENT": "demo"},
        transport=httpx.MockTransport(handler),
    ).fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=datetime.now(UTC),
    )

    assert result.status == "empty"
    assert result.error_code == "kalshi_required_market_data_empty"
    assert result.candidates == []


def test_req_kal_003_02_missing_batch_book_row_fails_closed() -> None:
    """TST-REQ-KAL-003-02: every requested market must have an authenticated book."""

    credentials, _ = _test_credentials()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if request.url.path.endswith("/markets/orderbooks"):
            return httpx.Response(200, json={"orderbooks": []})
        return httpx.Response(
            200,
            json={
                "markets": [
                    {
                        "ticker": "TEST-A",
                        "event_ticker": "EVENT-TEST-A",
                        "market_type": "binary",
                        "status": "active",
                    }
                ],
                "cursor": "",
            },
        )

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_MARKET_DATA_KEY_ID": credentials.key_id,
            "KALSHI_MARKET_DATA_PRIVATE_KEY": credentials.private_key_pem,
        },
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    assert result.status == "failed"
    assert result.error_code == "provider_invalid_payload"
    assert result.candidates == []


def test_req_kal_003_02_empty_authenticated_book_row_is_not_live_eligible() -> None:
    """TST-REQ-KAL-003-02: an empty authenticated book row fails closed."""

    credentials, _ = _test_credentials()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/exchange/status"):
            return httpx.Response(200, json={"exchange_active": True, "trading_active": True})
        if path.endswith("/markets/orderbooks"):
            return httpx.Response(
                200,
                json={
                    "orderbooks": [
                        {
                            "ticker": "TEST-A",
                            "orderbook_fp": {"yes_dollars": [], "no_dollars": []},
                        }
                    ]
                },
            )
        if "/events/" in path:
            return httpx.Response(
                200,
                json={"event": {"event_ticker": "EVENT-A", "series_ticker": "SERIES-A"}},
            )
        if "/series/" in path:
            return httpx.Response(
                200,
                json={
                    "series": {
                        "ticker": "SERIES-A",
                        "fee_type": "quadratic",
                        "fee_multiplier": 1,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "markets": [
                    {
                        "ticker": "TEST-A",
                        "event_ticker": "EVENT-A",
                        "market_type": "binary",
                        "status": "active",
                        "price_ranges": [
                            {"start": "0.0000", "end": "1.0000", "step": "0.0001"}
                        ],
                    }
                ],
                "cursor": "",
            },
        )

    result = ProviderBackedMarketDataFetcher(
        environ={
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_MARKET_DATA_KEY_ID": credentials.key_id,
            "KALSHI_MARKET_DATA_PRIVATE_KEY": credentials.private_key_pem,
        },
        transport=httpx.MockTransport(handler),
    ).fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=datetime.now(UTC),
    )

    assert result.status == "empty"
    assert result.error_code == "kalshi_required_order_book_empty"
    assert result.candidates == []


def test_req_kal_004_02_market_data_environment_mismatch_fails_before_network() -> None:
    """TST-REQ-KAL-004-02: environment crossover fails before a provider call."""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    fetcher = ProviderBackedMarketDataFetcher(
        environ={"APP_ENV": "production", "KALSHI_ENVIRONMENT": "demo"},
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    assert calls == 0
    assert result.status == "failed"
    assert result.error_code == "kalshi_environment_invalid"


def test_req_kal_008_13_14_account_reconciliation_normalizes_units_and_history() -> None:
    """TST-REQ-KAL-008-01, TST-REQ-KAL-013-01, TST-REQ-KAL-013-02, TST-REQ-KAL-014-01."""

    openai_credentials, _ = _test_credentials()
    claude_credentials, _ = _test_credentials()
    credentials_by_id = {
        "openai-key": openai_credentials.private_key_pem,
        "claude-key": claude_credentials.private_key_pem,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        key_id = request.headers["KALSHI-ACCESS-KEY"]
        path = request.url.path
        if path.endswith("/api_keys"):
            return httpx.Response(
                200,
                json={
                    "api_keys": [
                        {"api_key_id": key_id, "name": key_id, "scopes": ["read", "write"]}
                    ]
                },
            )
        if path.endswith("/portfolio/balance"):
            assert parse_qs(request.url.query.decode()) == {"subaccount": ["0"]}
            return httpx.Response(
                200,
                json={"balance": 1234, "portfolio_value": 5678, "updated_ts": 1_786_000_000},
            )
        if path.endswith("/portfolio/positions"):
            return httpx.Response(
                200,
                json={
                    "market_positions": [
                        {
                            "ticker": "TEST-A",
                            "position_fp": "2.00",
                            "market_exposure_dollars": "1.20",
                            "realized_pnl_dollars": "0.25",
                            "fees_paid_dollars": "0.05",
                        }
                    ],
                    "cursor": "",
                },
            )
        if path.endswith("/portfolio/fills"):
            return httpx.Response(
                200,
                json={"fills": [_kalshi_fill_fixture("fill-1", "YES")], "cursor": ""},
            )
        if path.endswith("/historical/fills"):
            return httpx.Response(
                200,
                json={
                    "fills": [
                        _kalshi_fill_fixture("fill-1", "YES"),
                        _kalshi_fill_fixture("fill-2", "NO"),
                    ],
                    "cursor": "",
                },
            )
        if path.endswith("/portfolio/settlements"):
            return httpx.Response(
                200,
                json={
                    "settlements": [
                        {
                            "ticker": "SETTLED-A",
                            "market_result": "yes",
                            "yes_count_fp": "10.00",
                            "yes_total_cost_dollars": "6.00",
                            "no_count_fp": "2.00",
                            "no_total_cost_dollars": "1.00",
                            "revenue": 1000,
                            "fee_cost": "0.10",
                        }
                    ],
                    "cursor": "",
                },
            )
        if path.endswith("/portfolio/orders"):
            return httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "order_id": f"open-{key_id}",
                            "client_order_id": f"intent-{key_id}",
                            "status": "resting",
                        }
                    ],
                    "cursor": "",
                },
            )
        if path.endswith("/historical/orders"):
            return httpx.Response(200, json={"orders": [], "cursor": ""})
        if path.endswith("/historical/cutoff"):
            return httpx.Response(
                200,
                json={
                    "market_settled_ts": "2026-01-01T00:00:00Z",
                    "trades_created_ts": "2026-01-01T00:00:00Z",
                    "orders_updated_ts": "2026-01-01T00:00:00Z",
                },
            )
        raise AssertionError(f"unexpected Kalshi path: {path}")

    source = ProviderBackedVenuePortfolioSource(
        {
            "APP_ENV": "development",
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_OPENAI_KEY_ID": "openai-key",
            "KALSHI_OPENAI_PRIVATE_KEY": credentials_by_id["openai-key"],
            "KALSHI_CLAUDE_KEY_ID": "claude-key",
            "KALSHI_CLAUDE_PRIVATE_KEY": credentials_by_id["claude-key"],
        },
        kalshi_transport=httpx.MockTransport(handler),
    )
    kalshi_accounts = [
        account
        for account in source.fetch_accounts(Environment.DEVELOPMENT)
        if account["venue"] == Venue.KALSHI.value
    ]

    assert len(kalshi_accounts) == 2
    assert all(account["status"] == "ready" for account in kalshi_accounts)
    assert kalshi_accounts[0]["accountRef"] != kalshi_accounts[1]["accountRef"]
    account = next(row for row in kalshi_accounts if row["provider"] == "openai")
    assert account["cashUsd"] == Decimal("12.34")
    assert account["accountValueUsd"] == Decimal("56.78")
    assert account["realizedPnlUsd"] == Decimal("3.10")
    assert account["totalPnlUsd"] is None
    assert account["positions"][0]["outcomeSide"] == "YES"
    assert account["positions"][0]["quantity"] == Decimal("2.00")
    assert {fill["sourceTradeId"] for fill in account["fills"]} == {"fill-1", "fill-2"}
    assert {fill["outcomeSide"] for fill in account["fills"]} == {"YES", "NO"}
    assert account["_writeScopeReady"] is True
    registry = RepositoryRegistry()
    VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource(kalshi_accounts),
    ).refresh(Environment.DEVELOPMENT)
    checkpoints = registry.shared().historical_import_checkpoints(
        environment=Environment.DEVELOPMENT
    )
    assert {row["source"] for row in checkpoints} == {
        "kalshi:openai:historical_fills",
        "kalshi:openai:historical_orders",
        "kalshi:claude:historical_fills",
        "kalshi:claude:historical_orders",
    }
    assert all(row["status"] == "completed" for row in checkpoints)


def test_req_kal_009_01_dashboard_sources_expose_kalshi_controls_and_outcomes() -> None:
    """TST-REQ-KAL-009-01: protected dashboard sources include Kalshi parity fields."""

    controls = (PROJECT_ROOT / "frontend" / "components" / "dashboard" / "config-controls.tsx").read_text()
    portfolio = (
        PROJECT_ROOT / "frontend" / "components" / "dashboard" / "venue-portfolio-panel.tsx"
    ).read_text()
    paths = (PROJECT_ROOT / "frontend" / "lib" / "config-paths.ts").read_text()

    assert 'value: "kalshi"' in controls
    assert "venues.kalshi.enabled" in paths
    assert "scanner.kalshi.market_data_limit" in paths
    assert "risk.kalshi.max_position_usd" in paths
    assert "outcomeSide" in portfolio
    assert "kalshiPnlUsd" in portfolio


def _kalshi_fill_fixture(fill_id: str, outcome_side: str) -> dict[str, object]:
    return {
        "fill_id": fill_id,
        "order_id": f"order-{fill_id}",
        "ticker": "TEST-A",
        "outcome_side": outcome_side.lower(),
        "count_fp": "1.25",
        "yes_price_dollars": "0.4375",
        "no_price_dollars": "0.5625",
        "fee_cost": "0.01",
        "created_time": "2026-08-01T12:00:00Z",
        "subaccount_number": 0,
    }


def test_req_kal_003_01_safe_reads_retry_but_fail_closed_after_exhaustion() -> None:
    """TST-REQ-KAL-003-01, TST-REQ-KAL-003-02: GET retries are bounded and safe."""

    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"detail": "request with private details"})

    fetcher = ProviderBackedMarketDataFetcher(
        environ={
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_READ_RETRIES": "2",
            "KALSHI_RETRY_BACKOFF_SECONDS": "0",
        },
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch(
        venue=Venue.KALSHI.value,
        config_payload=default_config_payload(),
        pulled_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )

    assert calls == 3
    assert result.status == "rate_limited"
    assert result.error_code == "provider_rate_limited"
    assert result.candidates == []
    assert "private details" not in result.message


def test_req_kal_003_02_valid_empty_account_collections_succeed() -> None:
    """TST-REQ-KAL-003-02: valid empty account collections are not failures."""

    credentials, _ = _test_credentials()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        collection_key = {
            "/trade-api/v2/portfolio/positions": "market_positions",
            "/trade-api/v2/portfolio/fills": "fills",
            "/trade-api/v2/portfolio/settlements": "settlements",
            "/trade-api/v2/portfolio/orders": "orders",
        }[request.url.path]
        return httpx.Response(200, json={collection_key: [], "cursor": ""})

    adapter = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    results = (
        (adapter.positions(), "market_positions"),
        (adapter.fills(), "fills"),
        (adapter.settlements(), "settlements"),
        (adapter.orders(), "orders"),
    )

    assert len(seen) == 4
    assert all(result.ok and result.payload[key] == [] for result, key in results)


def test_req_kal_007_02_dry_run_makes_zero_kalshi_adapter_calls() -> None:
    """TST-REQ-KAL-007-02: dry-run persists simulation without venue transport."""

    class Submitter:
        calls = 0

        def submit_order(self, request):
            self.calls += 1
            raise AssertionError("dry-run must not call the Kalshi adapter")

    submitter = Submitter()
    result = execute_kalshi_order(
        KalshiExecutionRequest(
            global_execution_mode="dry_run",
            risk_approved=True,
            order=KalshiLiveOrderRequest(
                ticker="TEST-26",
                side="bid",
                count="1.00",
                price="0.45",
                client_order_id="intent-dry-run",
                price_ranges=({"start": "0.00", "end": "1.00", "step": "0.01"},),
            ),
        ),
        submitter=submitter,
    )

    assert result.status == "simulated"
    assert result.order_recorded is True
    assert result.broker_submitted is False
    assert submitter.calls == 0


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("venue_enabled", "KALSHI_VENUE_DISABLED"),
        ("credentials_present", "KALSHI_CREDENTIAL_MISSING"),
        ("write_scope_ready", "KALSHI_WRITE_SCOPE_MISSING"),
        ("binary_market_supported", "KALSHI_MARKET_UNSUPPORTED"),
        ("market_active", "KALSHI_MARKET_INACTIVE"),
        ("exchange_active", "KALSHI_EXCHANGE_INACTIVE"),
        ("market_data_fresh", "KALSHI_MARKET_DATA_STALE"),
        ("account_state_fresh", "KALSHI_ACCOUNT_STATE_STALE"),
        ("no_unknown_or_conflicting_order", "KALSHI_ORDER_RECONCILIATION_REQUIRED"),
        ("provider_account_distinct", "KALSHI_PROVIDER_ACCOUNT_COLLISION"),
        ("account_reservation_available", "KALSHI_ACCOUNT_RESERVATION_BUSY"),
        ("risk_approved", "RISK_CHECK_FAILED"),
    ],
)
def test_req_kal_007_01_each_live_gate_has_an_exact_refusal(field: str, code: str) -> None:
    """TST-REQ-KAL-003-03, TST-REQ-KAL-007-01: live gates are independently testable."""

    values = {
        "live_enabled": True,
        "venue_enabled": True,
        "credentials_present": True,
        "write_scope_ready": True,
        "binary_market_supported": True,
        "market_active": True,
        "exchange_active": True,
        "market_data_fresh": True,
        "account_state_fresh": True,
        "no_unknown_or_conflicting_order": True,
        "provider_account_distinct": True,
        "account_reservation_available": True,
        "risk_approved": True,
    }
    values[field] = False
    result = evaluate_kalshi_live_order_gates(KalshiLiveOrderGateInput(**values))

    assert result.approved is False
    assert result.refusal_reasons == (code,)


@pytest.mark.parametrize(
    ("outcome", "quantity", "expected_side"),
    [("YES", "3.25", "ask"), ("NO", "-2.50", "bid")],
)
def test_req_kal_005_04_exit_uses_exact_contracts_reduce_only_and_persists_submitting(
    outcome: str,
    quantity: str,
    expected_side: str,
) -> None:
    """TST-REQ-KAL-005-01, TST-REQ-KAL-006-01: exits are exact and durable."""

    registry = RepositoryRegistry()
    submitted: list[KalshiLiveOrderRequest] = []

    class Submitter:
        def submit_order(self, request: KalshiLiveOrderRequest) -> KalshiOrderResult:
            rows = registry.state.rows("shared.exit_intents")
            assert rows[-1]["status"] == "submitting"
            submitted.append(request)
            return KalshiOrderResult(
                outcome=KalshiOrderOutcome.SUBMITTED,
                client_order_id=request.client_order_id,
                venue_order_id=f"order-{outcome.lower()}",
                send_started=True,
                remaining_count=request.count,
            )

    now = datetime.now(UTC)
    service = PipelineLifecycleService(
        registry,
        kalshi_submitters={ModelProvider.OPENAI: Submitter()},
    )
    position = {
        "position_id": f"position-{outcome.lower()}",
        "venue": Venue.KALSHI.value,
        "instrument_id": f"TEST-26:{outcome}",
        "ticker": "TEST-26",
        "outcome": outcome,
        "outcome_id": outcome,
        "quantity": abs(Decimal(quantity)),
        "model_provider": ModelProvider.OPENAI,
        "entry_price": Decimal("0.40"),
        "current_price": Decimal("0.55"),
        "market_candidate": {
            "ticker": "TEST-26",
            "outcome": outcome,
            "bestBid": "0.55",
            "bestAsk": "0.56",
            "price": "0.555",
            "priceRanges": [{"start": "0.00", "end": "1.00", "step": "0.01"}],
            "feeType": "quadratic",
            "feeMultiplier": "1",
        },
    }
    config = default_config_payload()
    config["live_enabled"] = True
    intent = service._record_exit_intent(  # noqa: SLF001 - specification boundary
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-kalshi-exit",
        exit_run_id="exit-run-kalshi",
        position=position,
        exit_trigger=ExitTrigger(
            trigger_type=ExitTriggerType.PROFIT_TARGET,
            position_id=position["position_id"],
            threshold=Decimal("0.25"),
            observed_value=Decimal("0.30"),
            reason="test target reached",
        ),
        config_payload=config,
        kill_switch_active=False,
        created_at=now,
    )

    assert intent["status"] == "submitted"
    assert submitted[0].side == expected_side
    assert submitted[0].count == abs(Decimal(quantity))
    assert submitted[0].reduce_only is True
    assert submitted[0].time_in_force == "immediate_or_cancel"


def test_req_kal_006_03_unknown_exit_is_not_resubmitted_and_can_be_canceled() -> None:
    """TST-REQ-KAL-006-03, TST-REQ-KAL-011-01: exits reconcile before reuse or cancel."""

    registry = RepositoryRegistry()

    class Submitter:
        submit_calls = 0
        calls: list[str] = []

        def submit_order(self, request: KalshiLiveOrderRequest) -> KalshiOrderResult:
            self.submit_calls += 1
            return KalshiOrderResult(
                outcome=KalshiOrderOutcome.UNKNOWN_SUBMIT,
                client_order_id=request.client_order_id,
                send_started=True,
                safe_error_code="kalshi_submit_unknown",
            )

        def find_order_by_client_order_id(self, client_order_id: str, *, ticker: str | None = None):
            self.calls.append(f"find:{client_order_id}:{ticker}")
            return VenueCallResult(
                ok=True,
                payload={
                    "order": {
                        "order_id": "venue-exit-order",
                        "client_order_id": client_order_id,
                        "ticker": ticker,
                        "status": "resting",
                    }
                },
            )

        def cancel_order(self, order_id: str):
            self.calls.append(f"cancel:{order_id}")
            return VenueCallResult(
                ok=True,
                payload={"order_id": order_id, "status": "canceled"},
            )

    submitter = Submitter()
    service = PipelineLifecycleService(
        registry,
        kalshi_submitters={ModelProvider.OPENAI: submitter},
    )
    now = datetime.now(UTC)
    position = {
        "position_id": "position-unknown-exit",
        "venue": Venue.KALSHI.value,
        "instrument_id": "TEST-26:YES",
        "ticker": "TEST-26",
        "outcome": "YES",
        "outcome_id": "YES",
        "quantity": Decimal("2.00"),
        "signed_quantity": Decimal("2.00"),
        "model_provider": ModelProvider.OPENAI,
        "safe_account_ref": "kalshi:safe-account-fingerprint",
        "market_candidate": {
            "ticker": "TEST-26",
            "outcome": "YES",
            "bestBid": "0.55",
            "bestAsk": "0.56",
            "price": "0.555",
            "priceRanges": [{"start": "0.00", "end": "1.00", "step": "0.01"}],
            "feeType": "quadratic",
            "feeMultiplier": "1",
        },
    }
    trigger = ExitTrigger(
        trigger_type=ExitTriggerType.PROFIT_TARGET,
        position_id=position["position_id"],
        threshold=Decimal("0.25"),
        observed_value=Decimal("0.30"),
        reason="test target reached",
    )
    config = default_config_payload()
    config["live_enabled"] = True

    first = service._record_exit_intent(  # noqa: SLF001 - specification boundary
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-exit-1",
        exit_run_id="exit-run-1",
        position=position,
        exit_trigger=trigger,
        config_payload=config,
        kill_switch_active=True,
        created_at=now,
    )
    first_status = first["status"]
    second = service._record_exit_intent(  # noqa: SLF001 - specification boundary
        environment=Environment.DEVELOPMENT,
        pipeline_run_id="pipeline-exit-2",
        exit_run_id="exit-run-2",
        position=position,
        exit_trigger=trigger,
        config_payload=config,
        kill_switch_active=True,
        created_at=now,
    )

    assert first_status == "unknown_submit"
    assert second["status"] == "reconcile_first"
    assert first["model_provider"] == ModelProvider.OPENAI.value
    assert submitter.submit_calls == 1

    service._cancel_known_kalshi_orders(  # noqa: SLF001 - specification boundary
        environment=Environment.DEVELOPMENT,
        now=now,
    )
    row = registry.state.rows("shared.exit_intents")[0]
    assert row["status"] == "canceled"
    assert submitter.calls[0].startswith("find:")
    assert submitter.calls[1] == "cancel:venue-exit-order"


def test_req_kal_008_02_latest_confirmed_snapshot_drives_stable_exit_position() -> None:
    """TST-REQ-KAL-008-01: only the latest confirmed nonzero holding can exit."""

    registry = RepositoryRegistry()
    for observed_at, quantity, state in (
        (datetime(2026, 8, 1, tzinfo=UTC), Decimal("1.00"), "open"),
        (datetime(2026, 8, 2, tzinfo=UTC), Decimal("2.50"), "open"),
    ):
        registry.state.insert(
            "shared.venue_position_snapshots",
            {
                "id": f"snapshot-{quantity}",
                "environment": Environment.DEVELOPMENT.value,
                "venue": Venue.KALSHI.value,
                "model_provider": ModelProvider.OPENAI.value,
                "account_ref": "kalshi:account-safe",
                "instrument_id": "TEST-26",
                "outcome": "YES",
                "quantity": quantity,
                "average_entry_price": Decimal("0.40"),
                "current_price": Decimal("0.55"),
                "unrealized_pnl_usd": Decimal("0.375"),
                "state": state,
                "observed_at": observed_at,
            },
        )

    service = PipelineLifecycleService(registry)
    first = service._open_kalshi_positions(Environment.DEVELOPMENT)  # noqa: SLF001
    second = service._open_kalshi_positions(Environment.DEVELOPMENT)  # noqa: SLF001

    assert len(first) == 1
    assert first[0]["quantity"] == Decimal("2.50")
    assert first[0]["instrument_id"] == "TEST-26:YES"
    assert first[0]["position_id"] == second[0]["position_id"]


def test_req_kal_013_01_missing_kalshi_mark_remains_unavailable_after_persistence() -> None:
    """TST-REQ-KAL-013-01: a missing mark cannot become a fabricated loss."""

    registry = RepositoryRegistry()
    now = datetime.now(UTC)
    account = {
        "status": "ready",
        "venue": Venue.KALSHI.value,
        "provider": ModelProvider.OPENAI.value,
        "accountRef": "kalshi:safe-account",
        "accountMode": "demo",
        "cashUsd": Decimal("10.00"),
        "buyingPowerUsd": Decimal("10.00"),
        "accountValueUsd": Decimal("14.00"),
        "realizedPnlUsd": Decimal("1.00"),
        "unrealizedPnlUsd": None,
        "totalPnlUsd": None,
        "observedAt": now,
        "positions": [
            {
                "instrumentId": "TEST-26",
                "title": "TEST-26",
                "outcome": "YES",
                "quantity": Decimal("10.00"),
                "averageEntryPrice": Decimal("0.40"),
                "currentPrice": None,
                "costBasisUsd": Decimal("4.00"),
                "marketValueUsd": None,
                "realizedPnlUsd": Decimal("1.00"),
                "unrealizedPnlUsd": None,
                "state": "open",
                "updatedAt": now,
            }
        ],
        "fills": [],
        "cashFlows": [],
        "_orderStates": {},
        "_openOrderIds": [],
        "_historicalCutoff": {
            "trades_created_ts": "2026-01-01T00:00:00Z",
            "orders_updated_ts": "2026-01-01T00:00:00Z",
        },
    }

    VenuePortfolioService(
        registry,
        source=StaticVenuePortfolioSource([account]),
    ).refresh(Environment.DEVELOPMENT)

    snapshot = registry.state.rows("shared.venue_portfolio_snapshots")[0]
    position = registry.state.rows("shared.venue_position_snapshots")[0]
    assert snapshot["market_value_usd"] is None
    assert snapshot["unrealized_pnl_usd"] is None
    assert snapshot["total_pnl_usd"] is None
    assert position["market_value_usd"] is None
    assert position["unrealized_pnl_usd"] is None
    assert position["total_pnl_usd"] is None


def test_req_kal_008_02_failed_refresh_keeps_confirmed_kalshi_values_degraded() -> None:
    """TST-REQ-KAL-008-02: a failed Kalshi refresh cannot replace confirmed values."""

    registry = RepositoryRegistry()
    observed_at = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    source = StaticVenuePortfolioSource(
        [
            {
                "status": "ready",
                "venue": Venue.KALSHI.value,
                "provider": ModelProvider.OPENAI.value,
                "accountRef": "kalshi:confirmed-account",
                "accountMode": "demo",
                "cashUsd": Decimal("12.00"),
                "buyingPowerUsd": Decimal("12.00"),
                "accountValueUsd": Decimal("15.00"),
                "realizedPnlUsd": Decimal("1.00"),
                "unrealizedPnlUsd": Decimal("0.00"),
                "totalPnlUsd": Decimal("1.00"),
                "observedAt": observed_at,
                "positions": [],
                "fills": [],
                "cashFlows": [],
                "_orderStates": {},
                "_openOrderIds": [],
                "_historicalCutoff": {
                    "trades_created_ts": "2026-01-01T00:00:00Z",
                    "orders_updated_ts": "2026-01-01T00:00:00Z",
                },
            }
        ]
    )
    service = VenuePortfolioService(registry, source=source)
    service.refresh(Environment.DEVELOPMENT)
    source.accounts = [
        {
            "status": "error",
            "venue": Venue.KALSHI.value,
            "provider": ModelProvider.OPENAI.value,
            "accountRef": "kalshi:confirmed-account",
            "accountMode": "demo",
            "message": "Kalshi portfolio refresh failed: TimeoutError.",
            "observedAt": observed_at.replace(minute=1),
            "positions": [],
            "fills": [],
        }
    ]

    payload = service.refresh(Environment.DEVELOPMENT)

    assert payload["overall"]["accountValueUsd"] == "15.00"
    assert payload["overall"]["status"] == "stale"
    assert payload["accounts"][0]["status"] == "stale"


def test_req_kal_009_02_unauthorized_portfolio_and_credentials_are_denied() -> None:
    """TST-REQ-KAL-009-02: protected Kalshi data requires dashboard authorization."""

    app = create_app(
        AppSettings(
            environment=Environment.DEVELOPMENT,
            allowed_usernames=("yaw",),
            signing_secret="test-signing-secret",
            csrf_token="test-csrf-token",
        )
    )
    client = TestClient(app)

    assert client.get("/api/portfolio").status_code == 401
    assert client.get("/api/wallets/status").status_code == 401


def test_req_kal_014_02_repeated_historical_cursor_fails_closed() -> None:
    """TST-REQ-KAL-014-02: historical pagination stops on a repeated cursor."""

    credentials, _ = _test_credentials()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"fills": [], "cursor": "repeat"})

    result = KalshiLiveOrderAdapter(
        base_url=KALSHI_DEMO_API_BASE_URL,
        credentials=credentials,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ).historical_fills()

    assert result.ok is False
    assert result.refusal_reason == "kalshi_repeated_cursor"
    assert calls == 2


def test_req_kal_012_01_shared_account_fingerprint_blocks_both_providers() -> None:
    """TST-REQ-KAL-012-01: distinct keys on one account cannot allocate twice."""

    class CollisionSource(ProviderBackedVenuePortfolioSource):
        def _polymarket_account(self, environment, provider):
            return {"status": "unavailable", "venue": Venue.POLYMARKET_US.value, "provider": provider.value}

        def _alpaca_account(self, environment, provider):
            return {"status": "unavailable", "venue": Venue.ALPACA.value, "provider": provider.value}

        def _kalshi_account(self, environment, provider):
            return {
                "status": "ready",
                "venue": Venue.KALSHI.value,
                "provider": provider.value,
                "accountRef": "kalshi:same-membership-fingerprint",
                "_accountReadReady": True,
                "_providerAccountDistinct": True,
                "_writeScopeReady": True,
                "observedAt": datetime.now(UTC),
            }

    source = CollisionSource({})
    accounts = [
        row
        for row in source.fetch_accounts(Environment.DEVELOPMENT)
        if row["venue"] == Venue.KALSHI.value
    ]

    assert [row["status"] for row in accounts] == ["error", "error"]
    assert all(
        source.kalshi_readiness(Environment.DEVELOPMENT, provider)["account_distinct"]
        is False
        for provider in (ModelProvider.OPENAI, ModelProvider.CLAUDE)
    )


def test_req_kal_012_02_reservation_key_uses_account_fingerprint_not_provider() -> None:
    """TST-REQ-KAL-012-02: credentials on one account contend on one lock."""

    registry = RepositoryRegistry()
    now = datetime.now(UTC)
    for provider in (ModelProvider.OPENAI, ModelProvider.CLAUDE):
        registry.state.insert(
            "shared.venue_portfolio_snapshots",
            {
                "id": f"snapshot-{provider.value}",
                "environment": Environment.DEVELOPMENT.value,
                "venue": Venue.KALSHI.value,
                "model_provider": provider.value,
                "account_ref": "kalshi:shared-safe-fingerprint",
                "observed_at": now,
            },
        )
    service = PipelineLifecycleService(registry)

    keys = {
        service._kalshi_account_lock_key(  # noqa: SLF001 - specification boundary
            environment=Environment.DEVELOPMENT,
            provider=provider,
        )
        for provider in (ModelProvider.OPENAI, ModelProvider.CLAUDE)
    }

    assert keys == {"kalshi-account:development:kalshi:shared-safe-fingerprint"}


@pytest.mark.parametrize(
    ("scopes", "expected_status", "expected_write_scope"),
    [
        (["write::trade"], "error", False),
        (["read"], "ready", False),
        (["read", "write::trade"], "ready", True),
    ],
)
def test_req_kal_012_02_scope_readiness_is_exact(
    monkeypatch,
    scopes: list[str],
    expected_status: str,
    expected_write_scope: bool,
) -> None:
    """TST-REQ-KAL-012-02: broad read and trade-write scopes gate readiness."""

    class ScopedAdapter:
        def api_keys(self):
            return VenueCallResult(
                ok=True,
                payload={
                    "api_keys": [
                        {"api_key_id": "openai-key", "scopes": list(scopes)}
                    ]
                },
            )

        def balance(self):
            return VenueCallResult(ok=True, payload={"balance": 100, "portfolio_value": 100})

        def positions(self):
            return VenueCallResult(ok=True, payload={"market_positions": []})

        def fills(self):
            return VenueCallResult(ok=True, payload={"fills": []})

        def settlements(self):
            return VenueCallResult(ok=True, payload={"settlements": []})

        def orders(self):
            return VenueCallResult(ok=True, payload={"orders": []})

        def historical_cutoff(self):
            return VenueCallResult(
                ok=True,
                payload={
                    "market_settled_ts": "2026-01-01T00:00:00Z",
                    "trades_created_ts": "2026-01-01T00:00:00Z",
                    "orders_updated_ts": "2026-01-01T00:00:00Z",
                },
            )

        def historical_fills(self):
            return VenueCallResult(ok=True, payload={"fills": []})

        def historical_orders(self):
            return VenueCallResult(ok=True, payload={"orders": []})

    monkeypatch.setattr(
        "app.services.venue_portfolio_service.kalshi_live_order_adapter_from_env",
        lambda *_args, **_kwargs: ScopedAdapter(),
    )
    source = ProviderBackedVenuePortfolioSource(
        {
            "APP_ENV": "development",
            "KALSHI_ENVIRONMENT": "demo",
            "KALSHI_OPENAI_KEY_ID": "openai-key",
            "KALSHI_OPENAI_PRIVATE_KEY": "generated-test-key-placeholder",
        }
    )

    account = source._kalshi_account(  # noqa: SLF001 - specification boundary
        Environment.DEVELOPMENT,
        ModelProvider.OPENAI,
    )

    assert account["status"] == expected_status
    assert bool(account.get("_writeScopeReady", False)) is expected_write_scope


def test_req_kal_011_01_disablement_reconciles_then_cancels_known_order() -> None:
    """TST-REQ-KAL-011-01: disablement cancels only a confirmed open venue order."""

    registry = RepositoryRegistry()
    now = datetime.now(UTC)
    registry.shared().record_order_intent(
        environment=Environment.DEVELOPMENT,
        execution_run_id="execution-kalshi",
        pipeline_run_id="pipeline-kalshi",
        strategy_consensus_output_id="output-kalshi",
        venue=Venue.KALSHI.value,
        instrument_id="kalshi:TEST-26:YES",
        model_provider=ModelProvider.OPENAI,
        side="buy",
        order_type="market",
        status="unknown_submit",
        notional_usd=Decimal("10.00"),
        size_multiplier=Decimal("0.50"),
        idempotency_key="intent-cancel",
        risk_payload={},
        source_payload={"marketCandidate": {"ticker": "TEST-26"}},
        created_at=now,
        updated_at=now,
    )

    class Submitter:
        calls: list[str] = []

        def find_order_by_client_order_id(self, client_order_id: str, *, ticker: str | None = None):
            self.calls.append(f"find:{client_order_id}:{ticker}")
            return VenueCallResult(
                ok=True,
                payload={
                    "order": {
                        "order_id": "venue-order-1",
                        "client_order_id": client_order_id,
                        "ticker": ticker,
                        "status": "resting",
                    }
                },
            )

        def cancel_order(self, order_id: str):
            self.calls.append(f"cancel:{order_id}")
            return VenueCallResult(
                ok=True,
                payload={"order_id": order_id, "status": "canceled"},
            )

    submitter = Submitter()
    service = PipelineLifecycleService(
        registry,
        kalshi_submitters={ModelProvider.OPENAI: submitter},
    )
    service._cancel_known_kalshi_orders(  # noqa: SLF001 - specification boundary
        environment=Environment.DEVELOPMENT,
        now=now,
    )

    row = registry.state.rows("shared.order_intents")[0]
    assert submitter.calls == ["find:intent-cancel:TEST-26", "cancel:venue-order-1"]
    assert row["status"] == "canceled"
    assert row["venue_order_id"] == "venue-order-1"


def test_req_kal_010_01_infrastructure_injects_environment_scoped_kalshi_secrets() -> None:
    """TST-REQ-KAL-010-01: deploy config is complete and contains no credential values."""

    template = (PROJECT_ROOT / "infra" / "cloudformation.yml").read_text()
    deploy = (PROJECT_ROOT / "scripts" / "deploy-stack.sh").read_text()
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    release_verifier = (PROJECT_ROOT / "scripts" / "verify-kalshi-release.py").read_text()
    for variable in (
        "KALSHI_MARKET_DATA_KEY_ID",
        "KALSHI_MARKET_DATA_PRIVATE_KEY",
        "KALSHI_OPENAI_KEY_ID",
        "KALSHI_OPENAI_PRIVATE_KEY",
        "KALSHI_CLAUDE_KEY_ID",
        "KALSHI_CLAUDE_PRIVATE_KEY",
    ):
        assert f"Name: {variable}" in template
        assert f"{variable}=" in (PROJECT_ROOT / ".env.example").read_text()
    assert "/kalshi/market-data/private-key" in deploy
    assert "/kalshi/openai/private-key" in deploy
    assert "/kalshi/claude/private-key" in deploy
    assert 'kalshi_environment="demo"' in deploy
    assert 'kalshi_environment="production"' in deploy
    assert "Verify Kalshi read-only release guardrails" in workflow
    assert "verify-kalshi-release.py" in workflow
    assert "markets/orderbooks" in release_verifier
    assert "providerBalances" in release_verifier
    assert "credentialMode" in release_verifier
    assert "Kalshi secret configuration is incomplete" in release_verifier
    assert "if not fills.ok or not orders.ok" in release_verifier
    assert "kalshiMutationEvents" in release_verifier
    assert "realOrderSmokeTest" in release_verifier
    assert "KALSHI_ENABLED: ${{ vars.KALSHI_ENABLED }}" in workflow
