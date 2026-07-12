"""Provider-backed market data ingestion helpers.

REQ: REQ-DAT-001, REQ-DAT-002, REQ-DAT-008, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import logging
import threading
import time
from typing import Any, Iterator, Protocol, Sequence

import httpx

from app.domain import Venue
from app.services.scanner_service import (
    DEFAULT_POLYMARKET_MARKET_DATA_LIMIT,
    MAX_POLYMARKET_MARKET_DATA_LIMIT,
)
from app.services.stock_universe import resolve_alpaca_symbol_universe


ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"
POLYMARKET_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_BASE_URL = "https://clob.polymarket.com"
DEFAULT_ALPACA_SYMBOL_CHUNK_SIZE = 50
DEFAULT_ALPACA_HISTORICAL_LOOKBACK_DAYS = 45
DEFAULT_ALPACA_PER_SYMBOL_FALLBACK_LIMIT = 25
DEFAULT_POLYMARKET_ORDER_BOOK_RETRIES = 2
DEFAULT_POLYMARKET_ORDER_BOOK_RETRY_BACKOFF_SECONDS = 0.25
DEFAULT_POLYMARKET_ORDER_BOOK_CONCURRENCY = 4
DEFAULT_POLYMARKET_ORDER_BOOK_CACHE_TTL_SECONDS = 300.0
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketDataProviderResult:
    """Dashboard-ready result from one venue data pull."""

    venue: str
    status: str
    source: str
    message: str
    candidates: list[dict[str, Any]]
    error_code: str | None = None


@dataclass(frozen=True)
class AlpacaSymbolPlan:
    symbols: list[str]
    requested_by_symbol: dict[str, str]
    normalized_count: int
    duplicate_count: int


@dataclass(frozen=True)
class CachedOrderBook:
    payload: dict[str, Any] | list[Any]
    cached_at: datetime


@dataclass(frozen=True)
class PolymarketBookRequest:
    index: int
    market: dict[str, Any]
    token_id: str
    outcome: str | None


@dataclass(frozen=True)
class PolymarketBookResult:
    request: PolymarketBookRequest
    book: dict[str, Any] | list[Any] | None
    stale: bool
    cached_at: datetime | None = None
    error: ProviderHttpError | None = None


class MarketDataProvider(Protocol):
    """Provider interface used by manual and scheduled dashboard pulls."""

    def fetch(
        self,
        *,
        venue: str,
        config_payload: dict[str, Any],
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        """Fetch market data for a configured venue."""


class ProviderHttpError(RuntimeError):
    """HTTP failure normalized for dashboard-safe status reporting."""

    def __init__(
        self,
        *,
        status: str,
        error_code: str,
        message: str,
        operation: str | None = None,
        status_code: int | None = None,
        exception_type: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message
        self.operation = operation
        self.status_code = status_code
        self.exception_type = exception_type
        self.duration_ms = duration_ms


class ProviderBackedMarketDataFetcher:
    """Fetch dashboard market data from Alpaca and Polymarket providers."""

    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        source = environ or {}
        self.environ = source
        self.transport = transport
        self.timeout_seconds = _float_setting(source.get("MARKET_DATA_HTTP_TIMEOUT_SECONDS"), 8.0)
        self._polymarket_order_book_cache: dict[str, CachedOrderBook] = {}
        self._polymarket_order_book_cache_lock = threading.Lock()
        self.alpaca_data_base_url = _base_url(
            source.get("ALPACA_DATA_BASE_URL") or source.get("ALPACA_MARKET_DATA_BASE_URL"),
            ALPACA_DATA_BASE_URL,
        )
        self.alpaca_data_feed = source.get("ALPACA_DATA_FEED", "iex").strip() or "iex"
        self.polymarket_gamma_base_url = _base_url(
            source.get("POLYMARKET_GAMMA_BASE_URL"),
            POLYMARKET_GAMMA_BASE_URL,
        )
        self.polymarket_clob_base_url = _base_url(
            source.get("POLYMARKET_CLOB_BASE_URL"),
            POLYMARKET_CLOB_BASE_URL,
        )
        self.polymarket_market_limit = _int_setting(
            source.get("POLYMARKET_MARKET_DATA_LIMIT"),
            DEFAULT_POLYMARKET_MARKET_DATA_LIMIT,
            minimum=1,
            maximum=MAX_POLYMARKET_MARKET_DATA_LIMIT,
        )
        self.alpaca_symbol_chunk_size = _int_setting(
            source.get("ALPACA_SYMBOL_CHUNK_SIZE"),
            DEFAULT_ALPACA_SYMBOL_CHUNK_SIZE,
            minimum=1,
            maximum=200,
        )
        self.alpaca_historical_bar_limit = _int_setting(
            source.get("ALPACA_HISTORICAL_BAR_LIMIT"),
            30,
            minimum=1,
            maximum=100,
        )
        self.alpaca_historical_lookback_days = _int_setting(
            source.get("ALPACA_HISTORICAL_LOOKBACK_DAYS"),
            DEFAULT_ALPACA_HISTORICAL_LOOKBACK_DAYS,
            minimum=2,
            maximum=365,
        )
        self.alpaca_per_symbol_fallback_enabled = _boolish(
            source.get("ALPACA_ENABLE_PER_SYMBOL_FALLBACK"),
            default=True,
        )
        self.alpaca_per_symbol_fallback_limit = _int_setting(
            source.get("ALPACA_PER_SYMBOL_FALLBACK_LIMIT"),
            DEFAULT_ALPACA_PER_SYMBOL_FALLBACK_LIMIT,
            minimum=1,
            maximum=100,
        )
        self.polymarket_order_book_retries = _int_setting(
            source.get("POLYMARKET_ORDER_BOOK_RETRIES"),
            DEFAULT_POLYMARKET_ORDER_BOOK_RETRIES,
            minimum=0,
            maximum=5,
        )
        self.polymarket_order_book_retry_backoff_seconds = _float_setting(
            source.get("POLYMARKET_ORDER_BOOK_RETRY_BACKOFF_SECONDS"),
            DEFAULT_POLYMARKET_ORDER_BOOK_RETRY_BACKOFF_SECONDS,
            minimum=0.0,
            maximum=5.0,
        )
        self.polymarket_order_book_concurrency = _int_setting(
            source.get("POLYMARKET_ORDER_BOOK_CONCURRENCY"),
            DEFAULT_POLYMARKET_ORDER_BOOK_CONCURRENCY,
            minimum=1,
            maximum=10,
        )
        self.polymarket_order_book_cache_ttl_seconds = _float_setting(
            source.get("POLYMARKET_ORDER_BOOK_CACHE_TTL_SECONDS"),
            DEFAULT_POLYMARKET_ORDER_BOOK_CACHE_TTL_SECONDS,
            minimum=0.0,
            maximum=3600.0,
        )

    def fetch(
        self,
        *,
        venue: str,
        config_payload: dict[str, Any],
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        if venue == Venue.ALPACA.value:
            return self._fetch_alpaca(config_payload=config_payload, pulled_at=pulled_at)
        if venue in {Venue.POLYMARKET_US.value, Venue.POLYMARKET_INTERNATIONAL.value}:
            return self._fetch_polymarket(
                venue=venue,
                config_payload=config_payload,
                pulled_at=pulled_at,
            )
        return MarketDataProviderResult(
            venue=venue,
            status="failed",
            source="provider market data",
            message=f"Unsupported market data venue: {venue}.",
            candidates=[],
            error_code="unsupported_venue",
        )

    def _fetch_alpaca(
        self,
        *,
        config_payload: dict[str, Any],
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        symbol_plan = _alpaca_symbol_plan(config_payload)
        symbols = symbol_plan.symbols
        if not symbols:
            return MarketDataProviderResult(
                venue=Venue.ALPACA.value,
                status="empty",
                source="alpaca market data api",
                message="No Alpaca symbols are configured for market data ingestion.",
                candidates=[],
            )

        key_id = self.environ.get("ALPACA_KEY_ID", "").strip()
        secret_key = self.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key_id or not secret_key:
            return MarketDataProviderResult(
                venue=Venue.ALPACA.value,
                status="failed",
                source="alpaca market data api",
                message="Alpaca market data credentials are missing.",
                candidates=[],
                error_code="alpaca_credentials_missing",
            )

        if symbol_plan.normalized_count or symbol_plan.duplicate_count:
            _log_provider_event(
                "provider_symbols_normalized",
                provider="alpaca",
                operation="alpaca symbol planning",
                symbol_count=len(symbols),
                normalized_count=symbol_plan.normalized_count,
                duplicate_count=symbol_plan.duplicate_count,
            )

        headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        params = {"feed": self.alpaca_data_feed} if self.alpaca_data_feed else {}
        candidates: list[dict[str, Any]] = []
        errors: list[ProviderHttpError] = []
        with self._client() as client:
            for chunk in _chunks(symbols, self.alpaca_symbol_chunk_size):
                chunk_candidates, chunk_errors = self._fetch_alpaca_chunk(
                    client=client,
                    symbols=chunk,
                    requested_by_symbol=symbol_plan.requested_by_symbol,
                    headers=headers,
                    params=params,
                    pulled_at=pulled_at,
                )
                candidates.extend(chunk_candidates)
                errors.extend(chunk_errors)

        return _venue_result(
            venue=Venue.ALPACA.value,
            provider_label="Alpaca",
            source="alpaca market data api",
            candidates=candidates,
            errors=errors,
        )

    def _fetch_alpaca_chunk(
        self,
        *,
        client: httpx.Client,
        symbols: list[str],
        requested_by_symbol: dict[str, str],
        headers: dict[str, str],
        params: dict[str, str],
        pulled_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[ProviderHttpError]]:
        request_params = {**params, "symbols": ",".join(symbols)}
        history_start = pulled_at - timedelta(days=self.alpaca_historical_lookback_days)
        history_params = {
            **request_params,
            "timeframe": "1Day",
            "limit": str(self.alpaca_historical_bar_limit),
            "start": _rfc3339_utc(history_start),
            "end": _rfc3339_utc(pulled_at),
        }
        errors: list[ProviderHttpError] = []
        snapshot_payload: dict[str, Any] | list[Any] | None = None
        bars_payload: dict[str, Any] | list[Any] | None = None
        try:
            snapshot_payload = self._get_json(
                client,
                f"{self.alpaca_data_base_url}/stocks/snapshots",
                headers=headers,
                params=request_params,
                operation="alpaca batch snapshots",
                provider="alpaca",
                log_context={"symbol_count": len(symbols)},
            )
        except ProviderHttpError as exc:
            errors.append(exc)
        try:
            bars_payload = self._get_json(
                client,
                f"{self.alpaca_data_base_url}/stocks/bars",
                headers=headers,
                params=history_params,
                operation="alpaca historical daily bars",
                provider="alpaca",
                log_context={"symbol_count": len(symbols)},
            )
        except ProviderHttpError as exc:
            errors.append(exc)

        snapshots = _snapshot_by_symbol(snapshot_payload)
        bars_by_symbol = _bars_by_symbol(bars_payload)
        if not snapshots and not bars_by_symbol and errors:
            if not self.alpaca_per_symbol_fallback_enabled or _dominant_error(errors).status == "rate_limited":
                return [], errors
            fallback_candidates: list[dict[str, Any]] = []
            fallback_errors: list[ProviderHttpError] = []
            for symbol in symbols[: self.alpaca_per_symbol_fallback_limit]:
                try:
                    fallback_candidates.append(
                        self._fetch_alpaca_symbol(
                            client=client,
                            symbol=symbol,
                            requested_symbol=requested_by_symbol.get(symbol, symbol),
                            headers=headers,
                            params=params,
                            pulled_at=pulled_at,
                        )
                    )
                except ProviderHttpError as exc:
                    fallback_errors.append(exc)
            skipped = len(symbols) - min(len(symbols), self.alpaca_per_symbol_fallback_limit)
            if skipped > 0:
                fallback_errors.append(
                    ProviderHttpError(
                        status="partial",
                        error_code="alpaca_fallback_limited",
                        message=(
                            "alpaca per-symbol fallback was capped after "
                            f"{self.alpaca_per_symbol_fallback_limit} symbols."
                        ),
                    )
                )
            if fallback_candidates:
                return fallback_candidates, [*errors, *fallback_errors]
            return [], errors

        candidates = []
        for symbol in symbols:
            candidate = _alpaca_candidate_from_snapshot(
                symbol=symbol,
                requested_symbol=requested_by_symbol.get(symbol, symbol),
                snapshot=snapshots.get(symbol),
                bars=bars_by_symbol.get(symbol, []),
                pulled_at=pulled_at,
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates, errors

    def _fetch_alpaca_symbol(
        self,
        *,
        client: httpx.Client,
        symbol: str,
        requested_symbol: str,
        headers: dict[str, str],
        params: dict[str, str],
        pulled_at: datetime,
    ) -> dict[str, Any]:
        quote_payload: dict[str, Any] | None = None
        bar_payload: dict[str, Any] | None = None
        errors: list[ProviderHttpError] = []
        try:
            quote_payload = self._get_json(
                client,
                f"{self.alpaca_data_base_url}/stocks/{symbol}/quotes/latest",
                headers=headers,
                params=params,
                operation="alpaca latest quote",
                provider="alpaca",
                log_context={"symbol_hash": _short_hash(symbol)},
            )
        except ProviderHttpError as exc:
            errors.append(exc)
        try:
            bar_payload = self._get_json(
                client,
                f"{self.alpaca_data_base_url}/stocks/{symbol}/bars/latest",
                headers=headers,
                params=params,
                operation="alpaca latest bar",
                provider="alpaca",
                log_context={"symbol_hash": _short_hash(symbol)},
            )
        except ProviderHttpError as exc:
            errors.append(exc)

        quote = (quote_payload or {}).get("quote") or {}
        bar = (bar_payload or {}).get("bar") or {}
        bid = _decimal_or_none(quote.get("bp"))
        ask = _decimal_or_none(quote.get("ap"))
        bar_close = _decimal_or_none(bar.get("c"))
        price = _midpoint(bid, ask) or ask or bid or bar_close
        if price is None and errors:
            raise _dominant_error(errors)

        bid_size = _decimal_or_none(quote.get("bs"))
        ask_size = _decimal_or_none(quote.get("as"))
        bar_volume = _decimal_or_none(bar.get("v"))
        spread = ask - bid if ask is not None and bid is not None else None
        liquidity = _sum_decimal([bid_size, ask_size]) or bar_volume
        candidate = {
            "id": f"{Venue.ALPACA.value}:{symbol}",
            "venue": Venue.ALPACA.value,
            "symbol": symbol,
            "price": _display_decimal(price),
            "liquidity": _display_decimal(liquidity),
            "spread": _display_decimal(spread),
            "state": "priced" if price is not None else "unpriced",
            "pulledAt": _timestamp(quote.get("t") or bar.get("t"), pulled_at),
            "dataSource": "quote+bar" if quote and bar else "quote" if quote else "bar",
        }
        if requested_symbol != symbol:
            candidate["requestedSymbol"] = requested_symbol
        return candidate

    def _fetch_polymarket(
        self,
        *,
        venue: str,
        config_payload: dict[str, Any],
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        errors: list[ProviderHttpError] = []
        candidates: list[dict[str, Any]] = []
        market_limit = _polymarket_market_data_limit(
            config_payload=config_payload,
            default=self.polymarket_market_limit,
        )
        with self._client() as client:
            try:
                market_payload = self._get_json(
                    client,
                    f"{self.polymarket_gamma_base_url}/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": str(market_limit),
                    },
                    operation="polymarket active markets",
                )
            except ProviderHttpError as exc:
                return MarketDataProviderResult(
                    venue=venue,
                    status=exc.status,
                    source="polymarket gamma and clob api",
                    message=exc.message,
                    candidates=[],
                    error_code=exc.error_code,
                )

            book_requests = _polymarket_book_requests(
                market_payload,
                request_limit=max(market_limit * 2, market_limit),
            )

        order_book_results = self._fetch_polymarket_order_books(book_requests)
        while len(candidates) < market_limit:
            try:
                result = next(order_book_results)
            except StopIteration:
                break
            if result.error is not None:
                errors.append(result.error)
            if result.book is None:
                continue
            candidate = _polymarket_candidate(
                venue=venue,
                market=result.request.market,
                token_id=result.request.token_id,
                outcome=result.request.outcome,
                book=result.book,
                pulled_at=pulled_at,
            )
            if candidate is None:
                continue
            if result.stale:
                candidate["orderBookStatus"] = "stale_cache"
                candidate["orderBookCachedAt"] = result.cached_at.isoformat() if result.cached_at else None
                candidate["orderBookErrorCode"] = result.error.error_code if result.error else None
            candidates.append(candidate)

        return _venue_result(
            venue=venue,
            provider_label="Polymarket",
            source="polymarket gamma and clob api",
            candidates=candidates,
            errors=errors,
            empty_message="No priced Polymarket candidates were found in active markets.",
        )

    def _fetch_polymarket_order_books(
        self,
        requests: list[PolymarketBookRequest],
    ) -> Iterator[PolymarketBookResult]:
        if not requests:
            return
        if self.polymarket_order_book_concurrency <= 1 or len(requests) == 1:
            for request in requests:
                yield self._fetch_polymarket_order_book(request)
            return

        batch_size = max(1, self.polymarket_order_book_concurrency)
        for start in range(0, len(requests), batch_size):
            batch = requests[start : start + batch_size]
            results: dict[int, PolymarketBookResult] = {}
            with ThreadPoolExecutor(max_workers=min(batch_size, len(batch))) as executor:
                future_by_index = {
                    executor.submit(self._fetch_polymarket_order_book, request): request.index
                    for request in batch
                }
                for future in as_completed(future_by_index):
                    index = future_by_index[future]
                    results[index] = future.result()
            for index in sorted(results):
                yield results[index]

    def _fetch_polymarket_order_book(
        self,
        request: PolymarketBookRequest,
    ) -> PolymarketBookResult:
        errors: list[ProviderHttpError] = []
        for attempt_index in range(self.polymarket_order_book_retries + 1):
            try:
                with self._client() as client:
                    book = self._get_json(
                        client,
                        f"{self.polymarket_clob_base_url}/book",
                        params={"token_id": request.token_id},
                        operation="polymarket order book",
                        provider="polymarket",
                        attempt=attempt_index + 1,
                        retry_count=self.polymarket_order_book_retries,
                        log_context={"token_hash": _short_hash(request.token_id)},
                    )
                with self._polymarket_order_book_cache_lock:
                    self._polymarket_order_book_cache[request.token_id] = CachedOrderBook(
                        payload=book,
                        cached_at=datetime.now(UTC),
                    )
                return PolymarketBookResult(request=request, book=book, stale=False)
            except ProviderHttpError as exc:
                errors.append(exc)
                if attempt_index < self.polymarket_order_book_retries and _retryable_provider_error(exc):
                    _log_provider_event(
                        "provider_request_retry",
                        provider="polymarket",
                        operation="polymarket order book",
                        error_code=exc.error_code,
                        exception_type=exc.exception_type,
                        attempt=attempt_index + 1,
                        retry_count=self.polymarket_order_book_retries,
                        token_hash=_short_hash(request.token_id),
                    )
                    time.sleep(
                        self.polymarket_order_book_retry_backoff_seconds * (2**attempt_index)
                    )
                    continue
                break

        error = errors[-1]
        cached = self._cached_polymarket_order_book(request.token_id)
        if cached is not None:
            _log_provider_event(
                "provider_stale_cache_used",
                provider="polymarket",
                operation="polymarket order book",
                error_code=error.error_code,
                exception_type=error.exception_type,
                token_hash=_short_hash(request.token_id),
                cache_age_seconds=int((datetime.now(UTC) - cached.cached_at).total_seconds()),
            )
            return PolymarketBookResult(
                request=request,
                book=cached.payload,
                stale=True,
                cached_at=cached.cached_at,
                error=error,
            )
        return PolymarketBookResult(request=request, book=None, stale=False, error=error)

    def _cached_polymarket_order_book(self, token_id: str) -> CachedOrderBook | None:
        with self._polymarket_order_book_cache_lock:
            cached = self._polymarket_order_book_cache.get(token_id)
        if cached is None:
            return None
        age_seconds = (datetime.now(UTC) - cached.cached_at).total_seconds()
        if age_seconds <= self.polymarket_order_book_cache_ttl_seconds:
            return cached
        with self._polymarket_order_book_cache_lock:
            self._polymarket_order_book_cache.pop(token_id, None)
        return None

    def _get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        operation: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        provider: str | None = None,
        log_context: dict[str, Any] | None = None,
        attempt: int = 1,
        retry_count: int = 0,
    ) -> dict[str, Any] | list[Any]:
        started = time.monotonic()
        try:
            response = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            duration_ms = _duration_ms(started)
            error = ProviderHttpError(
                status="failed",
                error_code="provider_http_error",
                message=f"{operation} failed: {type(exc).__name__}.",
                operation=operation,
                exception_type=type(exc).__name__,
                duration_ms=duration_ms,
            )
            _log_provider_error(
                error,
                provider=provider,
                attempt=attempt,
                retry_count=retry_count,
                context=log_context,
            )
            raise error from exc
        duration_ms = _duration_ms(started)
        if response.status_code == 429:
            error = ProviderHttpError(
                status="rate_limited",
                error_code="provider_rate_limited",
                message=f"{operation} was rate limited by the provider.",
                operation=operation,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            _log_provider_error(
                error,
                provider=provider,
                attempt=attempt,
                retry_count=retry_count,
                context=log_context,
            )
            raise error
        if response.status_code >= 400:
            error = ProviderHttpError(
                status="failed",
                error_code=f"provider_http_{response.status_code}",
                message=f"{operation} returned HTTP {response.status_code}.",
                operation=operation,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            _log_provider_error(
                error,
                provider=provider,
                attempt=attempt,
                retry_count=retry_count,
                context=log_context,
            )
            raise error
        try:
            payload = response.json()
        except ValueError as exc:
            error = ProviderHttpError(
                status="failed",
                error_code="provider_invalid_json",
                message=f"{operation} returned invalid JSON.",
                operation=operation,
                duration_ms=duration_ms,
            )
            _log_provider_error(
                error,
                provider=provider,
                attempt=attempt,
                retry_count=retry_count,
                context=log_context,
            )
            raise error from exc
        return payload

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


def _venue_result(
    *,
    venue: str,
    provider_label: str,
    source: str,
    candidates: list[dict[str, Any]],
    errors: list[ProviderHttpError],
    empty_message: str | None = None,
) -> MarketDataProviderResult:
    if candidates and errors:
        return MarketDataProviderResult(
            venue=venue,
            status="partial",
            source=source,
            message=(
                f"Fetched {len(candidates)} {provider_label} priced candidate"
                f"{'' if len(candidates) == 1 else 's'}; {len(errors)} provider call"
                f"{'' if len(errors) == 1 else 's'} failed. First error: {errors[0].message}"
            ),
            candidates=candidates,
            error_code=errors[0].error_code,
        )
    if candidates:
        return MarketDataProviderResult(
            venue=venue,
            status="pulled",
            source=source,
            message=(
                f"Fetched {len(candidates)} {provider_label} priced candidate"
                f"{'' if len(candidates) == 1 else 's'}."
            ),
            candidates=candidates,
        )
    if errors:
        dominant = _dominant_error(errors)
        return MarketDataProviderResult(
            venue=venue,
            status=dominant.status,
            source=source,
            message=dominant.message,
            candidates=[],
            error_code=dominant.error_code,
        )
    return MarketDataProviderResult(
        venue=venue,
        status="empty",
        source=source,
        message=empty_message or f"No priced {provider_label} candidates were fetched.",
        candidates=[],
    )


def _polymarket_market_data_limit(
    *,
    config_payload: dict[str, Any],
    default: int,
) -> int:
    scanner = config_payload.get("scanner") if isinstance(config_payload, dict) else {}
    polymarket = scanner.get("polymarket") if isinstance(scanner, dict) else {}
    configured = polymarket.get("market_data_limit") if isinstance(polymarket, dict) else None
    return _int_setting(
        configured,
        default,
        minimum=1,
        maximum=MAX_POLYMARKET_MARKET_DATA_LIMIT,
    )


def _dominant_error(errors: Sequence[ProviderHttpError]) -> ProviderHttpError:
    for error in errors:
        if error.status == "rate_limited":
            return error
    return errors[0]


def _retryable_provider_error(error: ProviderHttpError) -> bool:
    if error.error_code in {"provider_http_error", "provider_invalid_json"}:
        return True
    return error.error_code in {
        "provider_http_408",
        "provider_http_500",
        "provider_http_502",
        "provider_http_503",
        "provider_http_504",
    }


def _alpaca_symbol_plan(config_payload: dict[str, Any]) -> AlpacaSymbolPlan:
    requested_by_symbol: dict[str, str] = {}
    symbols: list[str] = []
    normalized_count = 0
    duplicate_count = 0
    for requested_symbol in resolve_alpaca_symbol_universe(config_payload):
        normalized = _normalize_alpaca_api_symbol(requested_symbol)
        if not normalized:
            continue
        if normalized != str(requested_symbol).strip().upper():
            normalized_count += 1
        if normalized in requested_by_symbol:
            duplicate_count += 1
            continue
        requested_by_symbol[normalized] = str(requested_symbol).strip().upper()
        symbols.append(normalized)
    return AlpacaSymbolPlan(
        symbols=symbols,
        requested_by_symbol=requested_by_symbol,
        normalized_count=normalized_count,
        duplicate_count=duplicate_count,
    )


def _normalize_alpaca_api_symbol(symbol: Any) -> str:
    text = str(symbol).strip().upper()
    if not text:
        return ""
    parts = text.split("-")
    if len(parts) == 2 and parts[0] and parts[1] and len(parts[1]) <= 2:
        return f"{parts[0]}.{parts[1]}"
    return text


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _polymarket_book_requests(
    payload: dict[str, Any] | list[Any],
    *,
    request_limit: int,
) -> list[PolymarketBookRequest]:
    requests: list[PolymarketBookRequest] = []
    for market in _market_items(payload):
        for token_id, outcome in _polymarket_tokens(market):
            requests.append(
                PolymarketBookRequest(
                    index=len(requests),
                    market=market,
                    token_id=token_id,
                    outcome=outcome,
                )
            )
            if len(requests) >= request_limit:
                return requests
    return requests


def _snapshot_by_symbol(payload: dict[str, Any] | list[Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("snapshots") if isinstance(payload.get("snapshots"), dict) else payload
    return {
        str(symbol).strip().upper(): snapshot
        for symbol, snapshot in raw.items()
        if str(symbol).strip() and isinstance(snapshot, dict)
    }


def _bars_by_symbol(payload: dict[str, Any] | list[Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("bars") if isinstance(payload.get("bars"), dict) else payload
    parsed: dict[str, list[dict[str, Any]]] = {}
    for symbol, bars in raw.items():
        if not isinstance(bars, list):
            continue
        parsed[str(symbol).strip().upper()] = [bar for bar in bars if isinstance(bar, dict)]
    return parsed


def _alpaca_candidate_from_snapshot(
    *,
    symbol: str,
    requested_symbol: str,
    snapshot: dict[str, Any] | None,
    bars: list[dict[str, Any]],
    pulled_at: datetime,
) -> dict[str, Any] | None:
    snapshot = snapshot or {}
    quote = _first_mapping(
        snapshot.get("latestQuote"),
        snapshot.get("latest_quote"),
        snapshot.get("quote"),
    )
    trade = _first_mapping(
        snapshot.get("latestTrade"),
        snapshot.get("latest_trade"),
        snapshot.get("trade"),
    )
    snapshot_bar = _first_mapping(
        snapshot.get("dailyBar"),
        snapshot.get("daily_bar"),
        snapshot.get("minuteBar"),
        snapshot.get("minute_bar"),
        snapshot.get("latestBar"),
        snapshot.get("latest_bar"),
        snapshot.get("bar"),
    )
    history_bars = bars
    latest_bar = history_bars[-1] if history_bars else snapshot_bar
    previous_bar = (
        history_bars[-2]
        if len(history_bars) >= 2
        else _first_mapping(snapshot.get("prevDailyBar"), snapshot.get("previousDailyBar"))
    )

    bid = _decimal_or_none(quote.get("bp"))
    ask = _decimal_or_none(quote.get("ap"))
    trade_price = _decimal_or_none(trade.get("p"))
    bar_close = _bar_close(latest_bar)
    previous_close = _bar_close(previous_bar)
    price = _midpoint(bid, ask) or ask or bid or trade_price or bar_close
    if price is None:
        return None

    bid_size = _decimal_or_none(quote.get("bs"))
    ask_size = _decimal_or_none(quote.get("as"))
    bar_volume = _decimal_or_none(latest_bar.get("v"))
    spread = ask - bid if ask is not None and bid is not None else None
    liquidity = _sum_decimal([bid_size, ask_size]) or bar_volume
    history_start = _timestamp(history_bars[0].get("t"), pulled_at) if history_bars else None
    history_end = _timestamp(history_bars[-1].get("t"), pulled_at) if history_bars else None
    average_volume = _average_decimal(
        [_decimal_or_none(bar.get("v")) for bar in history_bars[:-1]]
    )
    candidate = {
        "id": f"{Venue.ALPACA.value}:{symbol}",
        "venue": Venue.ALPACA.value,
        "symbol": symbol,
        "price": _display_decimal(price),
        "liquidity": _display_decimal(liquidity),
        "spread": _display_decimal(spread),
        "state": "priced",
        "pulledAt": _timestamp(quote.get("t") or trade.get("t") or latest_bar.get("t"), pulled_at),
        "dataSource": _alpaca_data_source(bool(snapshot), bool(history_bars)),
        "historyBarCount": len(history_bars),
        "previousClose": _display_decimal(previous_close),
        "latestOpen": _display_decimal(_decimal_or_none(latest_bar.get("o"))),
        "latestHigh": _display_decimal(_decimal_or_none(latest_bar.get("h"))),
        "latestLow": _display_decimal(_decimal_or_none(latest_bar.get("l"))),
        "latestClose": _display_decimal(_decimal_or_none(latest_bar.get("c"))),
        "latestVolume": _display_decimal(bar_volume),
        "averageVolume": _display_decimal(average_volume),
        "historyStart": history_start,
        "historyEnd": history_end,
    }
    if requested_symbol != symbol:
        candidate["requestedSymbol"] = requested_symbol
    return candidate


def _market_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "markets", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _polymarket_tokens(market: dict[str, Any]) -> list[tuple[str, str | None]]:
    token_rows = market.get("tokens")
    if isinstance(token_rows, list):
        parsed = []
        for token in token_rows:
            if not isinstance(token, dict):
                continue
            token_id = _first_string(
                token.get("token_id"),
                token.get("tokenId"),
                token.get("asset_id"),
                token.get("assetId"),
                token.get("id"),
            )
            if token_id:
                parsed.append((token_id, _first_string(token.get("outcome"), token.get("name"))))
        if parsed:
            return parsed

    token_ids = _coerce_list(
        market.get("clobTokenIds")
        or market.get("clob_token_ids")
        or market.get("tokenIds")
        or market.get("token_ids")
    )
    outcomes = _coerce_list(market.get("outcomes") or market.get("outcome_names"))
    parsed_tokens = []
    for index, raw_token_id in enumerate(token_ids):
        token_id = str(raw_token_id).strip()
        if not token_id:
            continue
        outcome = str(outcomes[index]).strip() if index < len(outcomes) and outcomes[index] is not None else None
        parsed_tokens.append((token_id, outcome or None))
    return parsed_tokens


def _polymarket_candidate(
    *,
    venue: str,
    market: dict[str, Any],
    token_id: str,
    outcome: str | None,
    book: dict[str, Any] | list[Any],
    pulled_at: datetime,
) -> dict[str, Any] | None:
    if not isinstance(book, dict):
        return None
    bids = book.get("bids") if isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book.get("asks"), list) else []
    best_bid = _best_price(bids, highest=True)
    best_ask = _best_price(asks, highest=False)
    last_trade = _decimal_or_none(book.get("last_trade_price"))
    price = _midpoint(best_bid, best_ask) or last_trade
    if price is None:
        return None
    spread = best_ask - best_bid if best_ask is not None and best_bid is not None else None
    bid_depth = _sum_order_sizes(bids)
    ask_depth = _sum_order_sizes(asks)
    liquidity = bid_depth + ask_depth
    market_id = _first_string(
        market.get("conditionId"),
        market.get("condition_id"),
        market.get("id"),
        book.get("market"),
    ) or token_id
    market_slug = _first_string(market.get("slug"), market.get("marketSlug"), market.get("market_slug"))
    title = _first_string(market.get("question"), market.get("title"), market_slug) or market_id
    display_title = f"{title} - {outcome}" if outcome else title
    end_date = _first_string(
        market.get("endDate"),
        market.get("end_date"),
        market.get("endDateIso"),
        market.get("end_date_iso"),
    )
    volume = _first_decimal(
        market.get("volume"),
        market.get("volumeNum"),
        market.get("volume_num"),
        market.get("volume24hr"),
        market.get("volume_24hr"),
    )
    return {
        "id": f"{venue}:{market_id}:{token_id}",
        "venue": venue,
        "market": display_title,
        "marketId": market_id,
        "marketSlug": market_slug,
        "price": _display_decimal(price),
        "midpoint": _display_decimal(price),
        "bestBid": _display_decimal(best_bid),
        "bestAsk": _display_decimal(best_ask),
        "bidDepth": _display_decimal(bid_depth),
        "askDepth": _display_decimal(ask_depth),
        "liquidity": _display_decimal(liquidity),
        "spread": _display_decimal(spread),
        "state": "priced",
        "pulledAt": _timestamp(book.get("timestamp"), pulled_at),
        "tokenId": token_id,
        "outcome": outcome,
        "category": _first_string(market.get("category"), market.get("categoryName")),
        "endDate": end_date,
        "volume": _display_decimal(volume),
        "active": _boolish(market.get("active"), default=True),
        "closed": _boolish(market.get("closed"), default=False),
    }


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except ValueError:
            return [stripped]
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    return [value]


def _best_price(orders: list[Any], *, highest: bool) -> Decimal | None:
    prices = [
        value
        for value in (_decimal_or_none(order.get("price")) for order in orders if isinstance(order, dict))
        if value is not None
    ]
    if not prices:
        return None
    return max(prices) if highest else min(prices)


def _sum_order_sizes(orders: list[Any]) -> Decimal:
    total = Decimal("0")
    for order in orders:
        if not isinstance(order, dict):
            continue
        size = _decimal_or_none(order.get("size"))
        if size is not None:
            total += size
    return total


def _sum_decimal(values: Sequence[Decimal | None]) -> Decimal | None:
    total = Decimal("0")
    found = False
    for value in values:
        if value is not None:
            total += value
            found = True
    return total if found else None


def _average_decimal(values: Sequence[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0")) / Decimal(len(present))


def _midpoint(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left + right) / Decimal("2")


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _display_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f").rstrip("0").rstrip(".")


def _timestamp(value: Any, fallback: datetime) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return fallback.isoformat()
        try:
            if stripped.isdigit():
                return _timestamp_from_number(Decimal(stripped), fallback)
        except InvalidOperation:
            pass
        return stripped
    if isinstance(value, (int, float, Decimal)):
        return _timestamp_from_number(Decimal(str(value)), fallback)
    return fallback.isoformat()


def _timestamp_from_number(value: Decimal, fallback: datetime) -> str:
    try:
        timestamp = float(value)
    except (ValueError, OverflowError):
        return fallback.isoformat()
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return fallback.isoformat()


def _rfc3339_utc(value: datetime) -> str:
    parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _first_string(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_decimal(*values: Any) -> Decimal | None:
    for value in values:
        parsed = _decimal_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _boolish(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _bar_close(bar: dict[str, Any]) -> Decimal | None:
    return _decimal_or_none(bar.get("c") or bar.get("close"))


def _alpaca_data_source(has_snapshot: bool, has_history: bool) -> str:
    if has_snapshot and has_history:
        return "snapshot+historical_bars"
    if has_snapshot:
        return "snapshot"
    if has_history:
        return "historical_bars"
    return "unknown"


def _base_url(raw: str | None, default: str) -> str:
    value = (raw or default).strip()
    return (value or default).rstrip("/")


def _float_setting(
    raw: str | None,
    default: float,
    *,
    minimum: float = 1.0,
    maximum: float | None = None,
) -> float:
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _int_setting(raw: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _log_provider_error(
    error: ProviderHttpError,
    *,
    provider: str | None,
    attempt: int,
    retry_count: int,
    context: dict[str, Any] | None,
) -> None:
    _log_provider_event(
        "provider_request_failed",
        provider=provider or "unknown",
        operation=error.operation or "provider request",
        status=error.status,
        status_code=error.status_code,
        error_code=error.error_code,
        exception_type=error.exception_type,
        duration_ms=error.duration_ms,
        attempt=attempt,
        retry_count=retry_count,
        **(context or {}),
    )


def _log_provider_event(event_name: str, **metadata: Any) -> None:
    payload = {
        "event": event_name,
        **{
            key: value
            for key, value in metadata.items()
            if value is not None and not _looks_secret_field(key)
        },
    }
    LOGGER.warning("provider_diagnostic %s", json.dumps(payload, sort_keys=True, default=str))


def _looks_secret_field(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("secret", "token", "key", "credential", "password")) and key not in {
        "token_hash",
        "symbol_hash",
    }
