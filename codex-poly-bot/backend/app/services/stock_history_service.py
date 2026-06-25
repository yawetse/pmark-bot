"""Alpaca stock broker history and bar import helpers.

REQ: REQ-ALP-003, REQ-ALP-017, REQ-DAT-001, REQ-DAT-002, REQ-DAT-008,
REQ-DB-003, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services.stock_universe import resolve_alpaca_symbol_universe


ALPACA_LIVE_TRADING_BASE_URL = "https://api.alpaca.markets"
ALPACA_PAPER_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets/v2"
ALPACA_BROKER_HISTORY_SOURCE_PREFIX = "alpaca_broker_history"
ALPACA_STOCK_BARS_SOURCE_PREFIX = "alpaca_stock_bars"


@dataclass(frozen=True)
class AlpacaHistoricalImportSummary:
    """Summary of records written by one Alpaca history import slice."""

    environment: Environment
    account_mode: str
    account_id: str | None = None
    order_count: int = 0
    fill_count: int = 0
    position_count: int = 0
    account_snapshot_count: int = 0
    bar_count: int = 0
    pnl_count: int = 0
    checkpoint_id: str | None = None
    status: str = "stored"
    message: str = ""
    error_code: str | None = None
    source: str | None = None
    next_cursor: str | None = None


class AlpacaHistoryImportError(RuntimeError):
    """Provider failure normalized for broker history status rows."""

    def __init__(self, *, status: str, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message


class AlpacaStockHistoryImporter:
    """Persist Alpaca broker history and reconstruct stock P&L."""

    def __init__(self, registry: RepositoryRegistry) -> None:
        self.registry = registry

    def record_order(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        payload: dict[str, Any],
        imported_at: datetime | None = None,
    ) -> dict:
        """Persist a historical Alpaca order payload."""

        order_id = _required_text(payload.get("id"), "order id")
        return self.registry.shared().record_alpaca_historical_order(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
            order_id=order_id,
            client_order_id=_first_text(payload.get("client_order_id")),
            symbol=_required_text(payload.get("symbol"), "order symbol"),
            side=_required_text(payload.get("side"), "order side"),
            order_type=_first_text(payload.get("type"), payload.get("order_type")),
            status=_first_text(payload.get("status")) or "unknown",
            quantity=_decimal_or_none(payload.get("qty")),
            filled_quantity=_decimal_or_none(payload.get("filled_qty")),
            filled_avg_price=_decimal_or_none(payload.get("filled_avg_price")),
            notional=_decimal_or_none(payload.get("notional")),
            submitted_at=_parse_datetime(payload.get("submitted_at")),
            filled_at=_parse_datetime(payload.get("filled_at")),
            canceled_at=_parse_datetime(payload.get("canceled_at")),
            raw_payload=payload,
            imported_at=imported_at,
        )

    def record_fill(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        payload: dict[str, Any],
        imported_at: datetime | None = None,
    ) -> dict:
        """Persist a historical Alpaca fill activity."""

        activity_id = _required_text(payload.get("id"), "fill activity id")
        filled_at = _parse_datetime(
            payload.get("transaction_time")
            or payload.get("filled_at")
            or payload.get("timestamp")
        )
        if filled_at is None:
            raise ValueError("fill timestamp is required")
        return self.registry.shared().record_alpaca_historical_fill(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
            activity_id=activity_id,
            order_id=_first_text(payload.get("order_id")),
            symbol=_required_text(payload.get("symbol"), "fill symbol"),
            side=_required_text(payload.get("side"), "fill side"),
            quantity=_decimal(payload.get("qty"), "fill quantity"),
            price=_decimal(payload.get("price"), "fill price"),
            filled_at=filled_at,
            raw_payload=payload,
            imported_at=imported_at,
        )

    def record_position(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        payload: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> dict:
        """Persist a current Alpaca open position snapshot."""

        return self.registry.shared().record_alpaca_historical_position(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
            symbol=_required_text(payload.get("symbol"), "position symbol"),
            quantity=_decimal(payload.get("qty"), "position quantity"),
            average_entry_price=_decimal_or_none(payload.get("avg_entry_price")),
            cost_basis=_decimal_or_none(payload.get("cost_basis")),
            market_value=_decimal_or_none(payload.get("market_value")),
            current_price=_decimal_or_none(payload.get("current_price")),
            unrealized_pnl_usd=_decimal_or_none(
                payload.get("unrealized_pl") or payload.get("unrealized_pnl")
            ),
            raw_payload=payload,
            observed_at=observed_at,
        )

    def record_account_snapshot(
        self,
        *,
        environment: Environment,
        account_mode: str,
        payload: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> dict:
        """Persist a broker account snapshot for stock reconciliation."""

        account_id = _required_text(
            payload.get("id") or payload.get("account_id") or payload.get("account_number"),
            "account id",
        )
        return self.registry.shared().record_alpaca_broker_account_snapshot(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
            account_status=_first_text(payload.get("status")) or "unknown",
            buying_power=_decimal_or_none(payload.get("buying_power")),
            cash=_decimal_or_none(payload.get("cash")),
            portfolio_value=_decimal_or_none(payload.get("portfolio_value")),
            equity=_decimal_or_none(payload.get("equity")),
            raw_payload=payload,
            observed_at=observed_at,
        )

    def record_stock_bar(
        self,
        *,
        environment: Environment,
        symbol: str,
        timeframe: str,
        payload: dict[str, Any],
        source: str = "alpaca market data api",
        imported_at: datetime | None = None,
    ) -> dict:
        """Persist one historical stock bar used by scanner backtests."""

        bar_start_at = _parse_datetime(payload.get("t") or payload.get("timestamp"))
        if bar_start_at is None:
            raise ValueError("bar timestamp is required")
        return self.registry.shared().record_stock_bar(
            environment=environment,
            symbol=symbol,
            timeframe=timeframe,
            bar_start_at=bar_start_at,
            open_price=_decimal(payload.get("o"), "bar open"),
            high_price=_decimal(payload.get("h"), "bar high"),
            low_price=_decimal(payload.get("l"), "bar low"),
            close_price=_decimal(payload.get("c"), "bar close"),
            volume=_decimal(payload.get("v"), "bar volume"),
            trade_count=_int_or_none(payload.get("n")),
            vwap=_decimal_or_none(payload.get("vw")),
            source=source,
            raw_payload=payload,
            imported_at=imported_at,
        )

    def record_import_checkpoint(
        self,
        *,
        environment: Environment,
        source: str,
        cursor_type: str,
        cursor_value: str,
        status: str,
        metadata: dict[str, Any] | None = None,
        last_success_at: datetime | None = None,
    ) -> dict:
        """Persist a resumable stock importer cursor."""

        return self.registry.shared().upsert_historical_import_checkpoint(
            environment=environment,
            source=source,
            cursor_type=cursor_type,
            cursor_value=cursor_value,
            status=status,
            metadata=metadata,
            last_success_at=last_success_at,
        )

    def rebuild_position_pnl(
        self,
        *,
        environment: Environment,
        account_mode: str,
        account_id: str,
        calculated_at: datetime | None = None,
    ) -> list[dict]:
        """Reconstruct realized and unrealized stock P&L from fills and positions."""

        fills = self.registry.shared().alpaca_historical_fills(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
        )
        positions = self.registry.shared().alpaca_historical_positions(
            environment=environment,
            account_mode=account_mode,
            account_id=account_id,
        )
        latest_positions: dict[str, dict] = {}
        for position in positions:
            current = latest_positions.get(position["symbol"])
            if current is None or position["observed_at"] >= current["observed_at"]:
                latest_positions[position["symbol"]] = position

        grouped: dict[str, list[dict]] = {}
        for fill in fills:
            grouped.setdefault(fill["symbol"], []).append(fill)
        symbols = sorted(set(grouped) | set(latest_positions))
        observed_at = calculated_at or datetime.now(UTC)
        snapshots = []
        for symbol in symbols:
            state = _reconstruct_long_only_cost_basis(grouped.get(symbol, []))
            position = latest_positions.get(symbol)
            if position is not None:
                open_quantity = Decimal(str(position["quantity"]))
                cost_basis = _decimal_or_none(position.get("cost_basis")) or state["cost_basis"]
                average_entry_price = (
                    _decimal_or_none(position.get("average_entry_price"))
                    or _safe_average(cost_basis, open_quantity)
                )
                market_value = _decimal_or_none(position.get("market_value"))
                unrealized = _decimal_or_none(position.get("unrealized_pnl_usd"))
                if unrealized is None and market_value is not None:
                    unrealized = market_value - cost_basis
            else:
                open_quantity = state["open_quantity"]
                cost_basis = state["cost_basis"]
                average_entry_price = _safe_average(cost_basis, open_quantity)
                market_value = None
                unrealized = Decimal("0")

            realized = state["realized_pnl_usd"]
            unrealized = unrealized or Decimal("0")
            snapshots.append(
                self.registry.shared().record_alpaca_symbol_pnl_snapshot(
                    environment=environment,
                    account_mode=account_mode,
                    account_id=account_id,
                    symbol=symbol,
                    open_quantity=open_quantity,
                    average_entry_price=average_entry_price,
                    realized_pnl_usd=realized,
                    unrealized_pnl_usd=unrealized,
                    total_pnl_usd=realized + unrealized,
                    cost_basis=cost_basis,
                    market_value=market_value,
                    fill_ids=[fill["id"] for fill in grouped.get(symbol, [])],
                    position_id=position["id"] if position else None,
                    calculated_at=observed_at,
                )
            )
        return snapshots


class AlpacaBrokerHistoryBackfiller:
    """Fetch Alpaca orders, fills, positions, account snapshots, and bars."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        account_mode: str,
        environ: dict[str, str] | None = None,
        trading_base_url: str | None = None,
        data_base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.registry = registry
        self.importer = AlpacaStockHistoryImporter(registry)
        self.account_mode = _account_mode(account_mode)
        source = environ or {}
        self.environ = source
        self.trading_base_url = _base_url(
            trading_base_url
            or source.get("ALPACA_TRADING_BASE_URL")
            or (
                source.get("ALPACA_PAPER_TRADING_BASE_URL")
                if self.account_mode == "paper"
                else source.get("ALPACA_LIVE_TRADING_BASE_URL")
            ),
            ALPACA_PAPER_TRADING_BASE_URL
            if self.account_mode == "paper"
            else ALPACA_LIVE_TRADING_BASE_URL,
        )
        self.data_base_url = _base_url(
            data_base_url or source.get("ALPACA_DATA_BASE_URL"),
            ALPACA_DATA_BASE_URL,
        )
        self.data_feed = source.get("ALPACA_DATA_FEED", "iex").strip() or "iex"
        self.transport = transport
        self.timeout_seconds = max(0.5, float(timeout_seconds))

    def backfill(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        account_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        timeframe: str = "1Day",
        max_symbols: int = 100,
        imported_at: datetime | None = None,
    ) -> AlpacaHistoricalImportSummary:
        """Fetch and persist one broker-history slice."""

        observed_at = imported_at or datetime.now(UTC)
        source = _broker_history_source(self.account_mode)
        after = start_at or _checkpoint_datetime(self.registry, environment=environment, source=source)
        until = end_at or observed_at
        headers = self._headers()
        if headers is None:
            checkpoint = self.importer.record_import_checkpoint(
                environment=environment,
                source=source,
                cursor_type="timestamp",
                cursor_value=after.isoformat() if after else "",
                status="failed",
                metadata={"errorCode": "alpaca_credentials_missing"},
            )
            return AlpacaHistoricalImportSummary(
                environment=environment,
                account_mode=self.account_mode,
                checkpoint_id=checkpoint["id"],
                status="failed",
                message="Alpaca broker history credentials are missing.",
                error_code="alpaca_credentials_missing",
                source=source,
                next_cursor=after.isoformat() if after else None,
            )

        try:
            with self._client() as client:
                account_payload = self._get_json(
                    client,
                    f"{self.trading_base_url}/v2/account",
                    headers=headers,
                    operation="alpaca account snapshot",
                )
                if not isinstance(account_payload, dict):
                    raise AlpacaHistoryImportError(
                        status="failed",
                        error_code="provider_invalid_account",
                        message="Alpaca account snapshot returned an unexpected payload.",
                    )
                account = self.importer.record_account_snapshot(
                    environment=environment,
                    account_mode=self.account_mode,
                    payload=account_payload,
                    observed_at=observed_at,
                )
                resolved_account_id = account_id or account["account_id"]

                orders = self._orders(client, headers=headers, after=after, until=until)
                order_rows = [
                    self.importer.record_order(
                        environment=environment,
                        account_mode=self.account_mode,
                        account_id=resolved_account_id,
                        payload=order,
                        imported_at=observed_at,
                    )
                    for order in orders
                ]

                fills = self._fills(client, headers=headers, after=after, until=until)
                fill_rows = [
                    self.importer.record_fill(
                        environment=environment,
                        account_mode=self.account_mode,
                        account_id=resolved_account_id,
                        payload=fill,
                        imported_at=observed_at,
                    )
                    for fill in fills
                ]

                positions = self._positions(client, headers=headers)
                position_rows = [
                    self.importer.record_position(
                        environment=environment,
                        account_mode=self.account_mode,
                        account_id=resolved_account_id,
                        payload=position,
                        observed_at=observed_at,
                    )
                    for position in positions
                ]

                bar_rows = self._backfill_bars(
                    client=client,
                    headers=headers,
                    environment=environment,
                    config_payload=config_payload,
                    start_at=after or (until - timedelta(days=30)),
                    end_at=until,
                    timeframe=timeframe,
                    max_symbols=max_symbols,
                    imported_at=observed_at,
                )
        except AlpacaHistoryImportError as exc:
            checkpoint = self.importer.record_import_checkpoint(
                environment=environment,
                source=source,
                cursor_type="timestamp",
                cursor_value=after.isoformat() if after else "",
                status=exc.status,
                metadata={"errorCode": exc.error_code, "message": exc.message},
            )
            return AlpacaHistoricalImportSummary(
                environment=environment,
                account_mode=self.account_mode,
                checkpoint_id=checkpoint["id"],
                status=exc.status,
                message=exc.message,
                error_code=exc.error_code,
                source=source,
                next_cursor=after.isoformat() if after else None,
            )

        pnl_rows = self.importer.rebuild_position_pnl(
            environment=environment,
            account_mode=self.account_mode,
            account_id=resolved_account_id,
            calculated_at=observed_at,
        )
        checkpoint = self.importer.record_import_checkpoint(
            environment=environment,
            source=source,
            cursor_type="timestamp",
            cursor_value=until.isoformat(),
            status="stored",
            metadata={
                "orders": len(order_rows),
                "fills": len(fill_rows),
                "positions": len(position_rows),
                "bars": len(bar_rows),
                "pnl": len(pnl_rows),
                "accountMode": self.account_mode,
            },
            last_success_at=observed_at,
        )
        return AlpacaHistoricalImportSummary(
            environment=environment,
            account_mode=self.account_mode,
            account_id=resolved_account_id,
            order_count=len(order_rows),
            fill_count=len(fill_rows),
            position_count=len(position_rows),
            account_snapshot_count=1,
            bar_count=len(bar_rows),
            pnl_count=len(pnl_rows),
            checkpoint_id=checkpoint["id"],
            status="stored",
            message=(
                f"Stored {len(order_rows)} orders, {len(fill_rows)} fills, "
                f"{len(position_rows)} positions, and {len(bar_rows)} stock bars."
            ),
            source=source,
            next_cursor=until.isoformat(),
        )

    def _orders(
        self,
        client: httpx.Client,
        *,
        headers: dict[str, str],
        after: datetime | None,
        until: datetime,
    ) -> list[dict[str, Any]]:
        params = {
            "status": "all",
            "limit": "500",
            "direction": "asc",
            "until": until.isoformat(),
        }
        if after is not None:
            params["after"] = after.isoformat()
        payload = self._get_json(
            client,
            f"{self.trading_base_url}/v2/orders",
            headers=headers,
            params=params,
            operation="alpaca historical orders",
        )
        return _items(payload)

    def _fills(
        self,
        client: httpx.Client,
        *,
        headers: dict[str, str],
        after: datetime | None,
        until: datetime,
    ) -> list[dict[str, Any]]:
        params = {
            "direction": "asc",
            "page_size": "100",
            "until": until.isoformat(),
        }
        if after is not None:
            params["after"] = after.isoformat()
        payload = self._get_json(
            client,
            f"{self.trading_base_url}/v2/account/activities/FILL",
            headers=headers,
            params=params,
            operation="alpaca historical fills",
        )
        return _items(payload)

    def _positions(self, client: httpx.Client, *, headers: dict[str, str]) -> list[dict[str, Any]]:
        payload = self._get_json(
            client,
            f"{self.trading_base_url}/v2/positions",
            headers=headers,
            operation="alpaca open positions",
        )
        return _items(payload)

    def _backfill_bars(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        environment: Environment,
        config_payload: dict[str, Any],
        start_at: datetime,
        end_at: datetime,
        timeframe: str,
        max_symbols: int,
        imported_at: datetime,
    ) -> list[dict]:
        symbols = resolve_alpaca_symbol_universe(config_payload)[: max(0, int(max_symbols))]
        if not symbols:
            return []
        payload = self._get_json(
            client,
            f"{self.data_base_url}/stocks/bars",
            headers=headers,
            params={
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start_at.isoformat(),
                "end": end_at.isoformat(),
                "limit": "10000",
                "feed": self.data_feed,
            },
            operation="alpaca historical stock bars",
        )
        bar_rows = []
        for symbol, bars in _bars_by_symbol(payload).items():
            for bar in bars:
                bar_rows.append(
                    self.importer.record_stock_bar(
                        environment=environment,
                        symbol=symbol,
                        timeframe=timeframe,
                        payload=bar,
                        imported_at=imported_at,
                    )
                )
        checkpoint_source = _stock_bars_source(self.account_mode, timeframe)
        self.importer.record_import_checkpoint(
            environment=environment,
            source=checkpoint_source,
            cursor_type="timestamp",
            cursor_value=end_at.isoformat(),
            status="stored",
            metadata={"symbols": symbols, "bars": len(bar_rows), "timeframe": timeframe},
            last_success_at=imported_at,
        )
        return bar_rows

    def _get_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        operation: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        try:
            response = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise AlpacaHistoryImportError(
                status="failed",
                error_code="provider_http_error",
                message=f"{operation} failed: {type(exc).__name__}.",
            ) from exc
        if response.status_code == 429:
            raise AlpacaHistoryImportError(
                status="rate_limited",
                error_code="provider_rate_limited",
                message=f"{operation} was rate limited by Alpaca.",
            )
        if response.status_code >= 400:
            raise AlpacaHistoryImportError(
                status="failed",
                error_code=f"provider_http_{response.status_code}",
                message=f"{operation} returned HTTP {response.status_code}.",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise AlpacaHistoryImportError(
                status="failed",
                error_code="provider_invalid_json",
                message=f"{operation} returned invalid JSON.",
            ) from exc
        return payload

    def _headers(self) -> dict[str, str] | None:
        key_id = self.environ.get("ALPACA_KEY_ID", "").strip()
        secret_key = self.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key_id or not secret_key:
            return None
        return {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


def _reconstruct_long_only_cost_basis(fills: list[dict]) -> dict[str, Decimal]:
    open_quantity = Decimal("0")
    cost_basis = Decimal("0")
    realized = Decimal("0")
    for fill in sorted(fills, key=lambda row: row["filled_at"]):
        quantity = Decimal(str(fill["quantity"]))
        price = Decimal(str(fill["price"]))
        side = str(fill["side"]).lower()
        if side == "buy":
            open_quantity += quantity
            cost_basis += quantity * price
            continue
        if side != "sell" or quantity <= 0:
            continue
        average_cost = _safe_average(cost_basis, open_quantity) or Decimal("0")
        closed_quantity = min(quantity, open_quantity)
        if closed_quantity <= 0:
            continue
        realized += (price - average_cost) * closed_quantity
        cost_basis -= average_cost * closed_quantity
        open_quantity -= closed_quantity
    return {
        "open_quantity": open_quantity,
        "cost_basis": cost_basis,
        "realized_pnl_usd": realized,
    }


def _safe_average(cost_basis: Decimal, quantity: Decimal) -> Decimal | None:
    if quantity == 0:
        return None
    return cost_basis / quantity


def _items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "orders", "activities", "positions", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _bars_by_symbol(payload: dict[str, Any] | list[Any]) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("bars") if isinstance(payload.get("bars"), dict) else payload
    parsed: dict[str, list[dict[str, Any]]] = {}
    for symbol, bars in raw.items():
        if isinstance(bars, list):
            parsed[str(symbol).strip().upper()] = [bar for bar in bars if isinstance(bar, dict)]
    return parsed


def _decimal(value: Any, label: str) -> Decimal:
    result = _decimal_or_none(value)
    if result is None:
        raise ValueError(f"{label} is required")
    return result


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("value must be decimal-compatible") from exc
    if not decimal.is_finite():
        raise ValueError("value must be finite")
    return decimal


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _required_text(value: Any, label: str) -> str:
    text = _first_text(value)
    if text is None:
        raise ValueError(f"{label} is required")
    return text


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return None


def _base_url(value: str | None, default: str) -> str:
    text = (value or default).strip().rstrip("/")
    return text or default


def _account_mode(value: str) -> str:
    text = value.strip().lower()
    if text not in {"paper", "live"}:
        raise ValueError("account_mode must be paper or live")
    return text


def _broker_history_source(account_mode: str) -> str:
    return f"{ALPACA_BROKER_HISTORY_SOURCE_PREFIX}:{account_mode}"


def _stock_bars_source(account_mode: str, timeframe: str) -> str:
    return f"{ALPACA_STOCK_BARS_SOURCE_PREFIX}:{account_mode}:{timeframe}"


def _checkpoint_datetime(
    registry: RepositoryRegistry,
    *,
    environment: Environment,
    source: str,
) -> datetime | None:
    for row in registry.shared().historical_import_checkpoints(environment=environment):
        if row["source"] == source and row["cursor_type"] == "timestamp":
            return _parse_datetime(row.get("cursor_value"))
    return None
