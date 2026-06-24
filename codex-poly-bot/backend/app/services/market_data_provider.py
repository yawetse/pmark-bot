"""Provider-backed market data ingestion helpers.

REQ: REQ-DAT-001, REQ-DAT-002, REQ-DAT-008, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Protocol, Sequence

import httpx

from app.domain import Venue


ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"
POLYMARKET_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_BASE_URL = "https://clob.polymarket.com"


@dataclass(frozen=True)
class MarketDataProviderResult:
    """Dashboard-ready result from one venue data pull."""

    venue: str
    status: str
    source: str
    message: str
    candidates: list[dict[str, Any]]
    error_code: str | None = None


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

    def __init__(self, *, status: str, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message


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
            5,
            minimum=1,
            maximum=25,
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
            return self._fetch_polymarket(venue=venue, pulled_at=pulled_at)
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
        symbols = _alpaca_symbols(config_payload)
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

        headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }
        params = {"feed": self.alpaca_data_feed} if self.alpaca_data_feed else {}
        candidates: list[dict[str, Any]] = []
        errors: list[ProviderHttpError] = []
        with self._client() as client:
            for symbol in symbols:
                try:
                    candidates.append(
                        self._fetch_alpaca_symbol(
                            client=client,
                            symbol=symbol,
                            headers=headers,
                            params=params,
                            pulled_at=pulled_at,
                        )
                    )
                except ProviderHttpError as exc:
                    errors.append(exc)

        return _venue_result(
            venue=Venue.ALPACA.value,
            provider_label="Alpaca",
            source="alpaca market data api",
            candidates=candidates,
            errors=errors,
        )

    def _fetch_alpaca_symbol(
        self,
        *,
        client: httpx.Client,
        symbol: str,
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
                operation=f"alpaca latest quote {symbol}",
            )
        except ProviderHttpError as exc:
            errors.append(exc)
        try:
            bar_payload = self._get_json(
                client,
                f"{self.alpaca_data_base_url}/stocks/{symbol}/bars/latest",
                headers=headers,
                params=params,
                operation=f"alpaca latest bar {symbol}",
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
        return {
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

    def _fetch_polymarket(
        self,
        *,
        venue: str,
        pulled_at: datetime,
    ) -> MarketDataProviderResult:
        errors: list[ProviderHttpError] = []
        candidates: list[dict[str, Any]] = []
        with self._client() as client:
            try:
                market_payload = self._get_json(
                    client,
                    f"{self.polymarket_gamma_base_url}/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": str(self.polymarket_market_limit),
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

            for market in _market_items(market_payload):
                if len(candidates) >= self.polymarket_market_limit:
                    break
                for token_id, outcome in _polymarket_tokens(market):
                    if len(candidates) >= self.polymarket_market_limit:
                        break
                    try:
                        book = self._get_json(
                            client,
                            f"{self.polymarket_clob_base_url}/book",
                            params={"token_id": token_id},
                            operation=f"polymarket order book {token_id}",
                        )
                    except ProviderHttpError as exc:
                        errors.append(exc)
                        continue
                    candidate = _polymarket_candidate(
                        venue=venue,
                        market=market,
                        token_id=token_id,
                        outcome=outcome,
                        book=book,
                        pulled_at=pulled_at,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

        return _venue_result(
            venue=venue,
            provider_label="Polymarket",
            source="polymarket gamma and clob api",
            candidates=candidates,
            errors=errors,
            empty_message="No priced Polymarket candidates were found in active markets.",
        )

    def _get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        operation: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        try:
            response = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ProviderHttpError(
                status="failed",
                error_code="provider_http_error",
                message=f"{operation} failed: {type(exc).__name__}.",
            ) from exc
        if response.status_code == 429:
            raise ProviderHttpError(
                status="rate_limited",
                error_code="provider_rate_limited",
                message=f"{operation} was rate limited by the provider.",
            )
        if response.status_code >= 400:
            raise ProviderHttpError(
                status="failed",
                error_code=f"provider_http_{response.status_code}",
                message=f"{operation} returned HTTP {response.status_code}.",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderHttpError(
                status="failed",
                error_code="provider_invalid_json",
                message=f"{operation} returned invalid JSON.",
            ) from exc
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


def _dominant_error(errors: Sequence[ProviderHttpError]) -> ProviderHttpError:
    for error in errors:
        if error.status == "rate_limited":
            return error
    return errors[0]


def _alpaca_symbols(config_payload: dict[str, Any]) -> list[str]:
    alpaca_config = config_payload.get("alpaca", {})
    raw_symbols = alpaca_config.get("symbol_universe") if isinstance(alpaca_config, dict) else []
    return [str(symbol).strip().upper() for symbol in (raw_symbols or []) if str(symbol).strip()]


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
    liquidity = _sum_order_sizes(bids) + _sum_order_sizes(asks)
    market_id = _first_string(market.get("conditionId"), market.get("condition_id"), book.get("market")) or token_id
    title = _first_string(market.get("question"), market.get("title"), market.get("slug")) or market_id
    display_title = f"{title} - {outcome}" if outcome else title
    return {
        "id": f"{venue}:{market_id}:{token_id}",
        "venue": venue,
        "market": display_title,
        "price": _display_decimal(price),
        "liquidity": _display_decimal(liquidity),
        "spread": _display_decimal(spread),
        "state": "priced",
        "pulledAt": _timestamp(book.get("timestamp"), pulled_at),
        "tokenId": token_id,
        "outcome": outcome,
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


def _first_string(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _base_url(raw: str | None, default: str) -> str:
    value = (raw or default).strip()
    return (value or default).rstrip("/")


def _float_setting(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except ValueError:
        return default
    return max(1.0, value)


def _int_setting(raw: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
