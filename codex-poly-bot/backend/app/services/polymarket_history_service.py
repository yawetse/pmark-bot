"""Clean-room Polymarket historical trade import helpers.

REQ: REQ-DAT-009, REQ-STR-002, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.db import RepositoryRegistry
from app.domain import Environment


POLYMARKET_CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
POLYMARKET_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
POLYMARKET_GAMMA_MARKET_SOURCE = "polymarket_gamma_markets"
POLYMARKET_ORDER_FILLED_V2_SIGNATURE = (
    "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
)
POLYMARKET_POLYGON_ORDER_FILLED_SOURCE = "polygon_order_filled"


@dataclass(frozen=True)
class PolymarketHistoricalImportSummary:
    """Summary of records written by one historical import slice."""

    environment: Environment
    market_count: int = 0
    chain_fill_count: int = 0
    trade_count: int = 0
    checkpoint_id: str | None = None
    target_wallet_snapshot_id: str | None = None
    status: str = "stored"
    message: str = ""
    error_code: str | None = None
    source: str | None = None
    next_cursor: str | None = None


class PolymarketGammaBackfillError(RuntimeError):
    """Provider failure normalized for historical importer status rows."""

    def __init__(self, *, status: str, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message


class PolymarketPolygonBackfillError(RuntimeError):
    """Polygon JSON-RPC failure normalized for historical importer status rows."""

    def __init__(
        self,
        *,
        status: str,
        error_code: str,
        message: str,
        retryable_with_smaller_window: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.message = message
        self.retryable_with_smaller_window = retryable_with_smaller_window


class PolymarketGammaMarketBackfiller:
    """Fetch Gamma market metadata with limit/offset pagination."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        base_url: str = POLYMARKET_GAMMA_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.registry = registry
        self.importer = PolymarketHistoryImporter(registry)
        self.base_url = _base_url(base_url, POLYMARKET_GAMMA_BASE_URL)
        self.transport = transport
        self.timeout_seconds = max(0.5, float(timeout_seconds))

    def backfill_markets(
        self,
        *,
        environment: Environment,
        limit: int = 100,
        max_pages: int = 1,
        active: bool | None = None,
        closed: bool | None = True,
        order: str | None = None,
        ascending: bool | None = None,
        fetched_at: datetime | None = None,
    ) -> PolymarketHistoricalImportSummary:
        """Fetch and persist Gamma markets from the last stored offset."""

        page_limit = _bounded_int(limit, default=100, minimum=1, maximum=500)
        pages_to_fetch = _bounded_int(max_pages, default=1, minimum=1, maximum=1000)
        observed_at = fetched_at or datetime.now(UTC)
        source = _gamma_market_source(active=active, closed=closed)
        offset = _checkpoint_offset(self.registry, environment=environment, source=source)
        initial_offset = offset
        written = 0
        pages = 0
        last_page_count = 0
        status = "complete"

        with self._client() as client:
            for _page in range(pages_to_fetch):
                try:
                    payload = self._get_json(
                        client=client,
                        params=_gamma_market_params(
                            limit=page_limit,
                            offset=offset,
                            active=active,
                            closed=closed,
                            order=order,
                            ascending=ascending,
                        ),
                    )
                except PolymarketGammaBackfillError as exc:
                    checkpoint = self.importer.record_import_checkpoint(
                        environment=environment,
                        source=source,
                        cursor_type="offset",
                        cursor_value=str(offset),
                        status=exc.status,
                        metadata={
                            "errorCode": exc.error_code,
                            "message": exc.message,
                            "limit": page_limit,
                            "initialOffset": initial_offset,
                            "active": active,
                            "closed": closed,
                        },
                    )
                    return PolymarketHistoricalImportSummary(
                        environment=environment,
                        checkpoint_id=checkpoint["id"],
                        status=exc.status,
                        message=exc.message,
                        error_code=exc.error_code,
                        source=source,
                        next_cursor=str(offset),
                    )

                markets = _gamma_market_items(payload)
                last_page_count = len(markets)
                for market in markets:
                    self.importer.record_market_metadata(
                        environment=environment,
                        payload=market,
                        fetched_at=observed_at,
                    )
                    written += 1

                pages += 1
                offset += last_page_count
                if last_page_count < page_limit:
                    status = "complete"
                    break
                status = "stored"

        checkpoint = self.importer.record_import_checkpoint(
            environment=environment,
            source=source,
            cursor_type="offset",
            cursor_value=str(offset),
            status=status,
            metadata={
                "limit": page_limit,
                "pages": pages,
                "initialOffset": initial_offset,
                "lastPageCount": last_page_count,
                "active": active,
                "closed": closed,
                "order": order,
                "ascending": ascending,
            },
            last_success_at=observed_at,
        )
        return PolymarketHistoricalImportSummary(
            environment=environment,
            market_count=written,
            checkpoint_id=checkpoint["id"],
            status=status,
            message=(
                f"Stored {written} Gamma market metadata row"
                f"{'' if written == 1 else 's'} from {pages} page"
                f"{'' if pages == 1 else 's'}."
            ),
            source=source,
            next_cursor=str(offset),
        )

    def _get_json(
        self,
        *,
        client: httpx.Client,
        params: dict[str, str],
    ) -> dict[str, Any] | list[Any]:
        try:
            response = client.get(f"{self.base_url}/markets", params=params)
        except httpx.HTTPError as exc:
            raise PolymarketGammaBackfillError(
                status="failed",
                error_code="provider_http_error",
                message=f"Gamma markets backfill failed: {type(exc).__name__}.",
            ) from exc
        if response.status_code == 429:
            raise PolymarketGammaBackfillError(
                status="rate_limited",
                error_code="provider_rate_limited",
                message="Gamma markets backfill was rate limited by Polymarket.",
            )
        if response.status_code >= 400:
            raise PolymarketGammaBackfillError(
                status="failed",
                error_code=f"provider_http_{response.status_code}",
                message=f"Gamma markets backfill returned HTTP {response.status_code}.",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PolymarketGammaBackfillError(
                status="failed",
                error_code="provider_invalid_json",
                message="Gamma markets backfill returned invalid JSON.",
            ) from exc

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


class PolymarketPolygonOrderFilledBackfiller:
    """Fetch CTF Exchange V2 OrderFilled logs from Polygon JSON-RPC."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        rpc_url: str,
        exchange_contract: str = POLYMARKET_CTF_EXCHANGE_V2,
        order_filled_topic: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.registry = registry
        self.importer = PolymarketHistoryImporter(registry)
        self.rpc_url = rpc_url.strip()
        if not self.rpc_url:
            raise ValueError("rpc_url is required")
        self.exchange_contract = _normalize_address(exchange_contract)
        self.order_filled_topic = _normalize_topic(order_filled_topic)
        self.transport = transport
        self.timeout_seconds = max(0.5, float(timeout_seconds))

    def backfill_order_filled_events(
        self,
        *,
        environment: Environment,
        start_block: int,
        end_block: int,
        max_block_range: int = 500,
        max_windows: int = 1,
        decode_logs: bool | None = None,
        fetched_at: datetime | None = None,
    ) -> PolymarketHistoricalImportSummary:
        """Backfill OrderFilled logs and checkpoint the last scanned block."""

        start = max(0, _int(start_block))
        end = max(start, _int(end_block))
        range_size = _bounded_int(max_block_range, default=500, minimum=1, maximum=100_000)
        windows_to_fetch = _bounded_int(max_windows, default=1, minimum=1, maximum=10_000)
        source = _polygon_order_filled_source(
            exchange_contract=self.exchange_contract,
            order_filled_topic=self.order_filled_topic,
        )
        cursor = _checkpoint_block_number(self.registry, environment=environment, source=source)
        current = max(start, cursor + 1)
        observed_at = fetched_at or datetime.now(UTC)
        written = 0
        windows = 0
        last_scanned = current - 1
        status = "complete" if current > end else "stored"
        should_decode_logs = (
            bool(decode_logs) if decode_logs is not None else self.order_filled_topic is not None
        )

        with self._client() as client:
            while current <= end and windows < windows_to_fetch:
                window_end = min(current + range_size - 1, end)
                try:
                    logs = self._fetch_logs_with_retries(
                        client=client,
                        from_block=current,
                        to_block=window_end,
                    )
                except PolymarketPolygonBackfillError as exc:
                    checkpoint = self.importer.record_import_checkpoint(
                        environment=environment,
                        source=source,
                        cursor_type="block_number",
                        cursor_value=str(last_scanned),
                        status=exc.status,
                        metadata={
                            "errorCode": exc.error_code,
                            "message": exc.message,
                            "failedFromBlock": current,
                            "failedToBlock": window_end,
                            "startBlock": start,
                            "endBlock": end,
                            "maxBlockRange": range_size,
                        },
                    )
                    return PolymarketHistoricalImportSummary(
                        environment=environment,
                        chain_fill_count=written,
                        checkpoint_id=checkpoint["id"],
                        status=exc.status,
                        message=exc.message,
                        error_code=exc.error_code,
                        source=source,
                        next_cursor=str(last_scanned),
                    )

                for raw_log in logs:
                    event = decode_order_filled_v2_log(raw_log) if should_decode_logs else raw_log
                    self.importer.record_decoded_fill_event(
                        environment=environment,
                        event=event,
                        block_timestamp=observed_at,
                    )
                    written += 1

                windows += 1
                last_scanned = window_end
                current = window_end + 1
                status = "complete" if last_scanned >= end else "stored"

        checkpoint = self.importer.record_import_checkpoint(
            environment=environment,
            source=source,
            cursor_type="block_number",
            cursor_value=str(last_scanned),
            status=status,
            metadata={
                "startBlock": start,
                "endBlock": end,
                "lastScannedBlock": last_scanned,
                "windows": windows,
                "maxBlockRange": range_size,
                "exchangeContract": self.exchange_contract,
                "orderFilledTopic": self.order_filled_topic,
                "decodeLogs": should_decode_logs,
            },
            last_success_at=observed_at if windows else None,
        )
        return PolymarketHistoricalImportSummary(
            environment=environment,
            chain_fill_count=written,
            checkpoint_id=checkpoint["id"],
            status=status,
            message=(
                f"Stored {written} Polygon OrderFilled log"
                f"{'' if written == 1 else 's'} through block {last_scanned}."
            ),
            source=source,
            next_cursor=str(last_scanned),
        )

    def _fetch_logs_with_retries(
        self,
        *,
        client: httpx.Client,
        from_block: int,
        to_block: int,
    ) -> list[dict[str, Any]]:
        try:
            return self._eth_get_logs(client=client, from_block=from_block, to_block=to_block)
        except PolymarketPolygonBackfillError as exc:
            if not exc.retryable_with_smaller_window or from_block >= to_block:
                raise
            midpoint = (from_block + to_block) // 2
            return [
                *self._fetch_logs_with_retries(
                    client=client,
                    from_block=from_block,
                    to_block=midpoint,
                ),
                *self._fetch_logs_with_retries(
                    client=client,
                    from_block=midpoint + 1,
                    to_block=to_block,
                ),
            ]

    def _eth_get_logs(
        self,
        *,
        client: httpx.Client,
        from_block: int,
        to_block: int,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "address": self.exchange_contract,
            "fromBlock": _hex_block(from_block),
            "toBlock": _hex_block(to_block),
        }
        if self.order_filled_topic is not None:
            params["topics"] = [self.order_filled_topic]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getLogs",
            "params": [params],
        }
        try:
            response = client.post(self.rpc_url, json=payload)
        except httpx.HTTPError as exc:
            raise PolymarketPolygonBackfillError(
                status="failed",
                error_code="provider_http_error",
                message=f"Polygon OrderFilled backfill failed: {type(exc).__name__}.",
            ) from exc
        if response.status_code == 429:
            raise PolymarketPolygonBackfillError(
                status="rate_limited",
                error_code="provider_rate_limited",
                message="Polygon OrderFilled backfill was rate limited by the RPC provider.",
            )
        if response.status_code >= 400:
            raise PolymarketPolygonBackfillError(
                status="failed",
                error_code=f"provider_http_{response.status_code}",
                message=f"Polygon OrderFilled backfill returned HTTP {response.status_code}.",
            )
        try:
            rpc_payload = response.json()
        except ValueError as exc:
            raise PolymarketPolygonBackfillError(
                status="failed",
                error_code="provider_invalid_json",
                message="Polygon OrderFilled backfill returned invalid JSON.",
            ) from exc
        if isinstance(rpc_payload, dict) and isinstance(rpc_payload.get("error"), dict):
            error = rpc_payload["error"]
            message = str(error.get("message") or "Polygon RPC returned an error.")
            code = str(error.get("code") or "rpc_error")
            raise PolymarketPolygonBackfillError(
                status="failed",
                error_code=f"polygon_rpc_{code}",
                message=message,
                retryable_with_smaller_window=_rpc_error_is_window_retryable(message=message),
            )
        result = rpc_payload.get("result") if isinstance(rpc_payload, dict) else None
        if not isinstance(result, list):
            raise PolymarketPolygonBackfillError(
                status="failed",
                error_code="provider_invalid_result",
                message="Polygon OrderFilled backfill returned a non-list result.",
            )
        return [item for item in result if isinstance(item, dict)]

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds, transport=self.transport)


class PolymarketHistoryImporter:
    """Persist normalized historical Polymarket data from public sources.

    This is intentionally transport-free. RPC, Gamma API, and external CSV
    readers should feed decoded payloads into this boundary.
    """

    def __init__(self, registry: RepositoryRegistry) -> None:
        self.registry = registry

    def record_market_metadata(
        self,
        *,
        environment: Environment,
        payload: dict[str, Any],
        fetched_at: datetime | None = None,
    ) -> dict:
        """Persist one Gamma market payload in normalized and raw form."""

        market_id = _first_text(
            payload.get("id"),
            payload.get("marketId"),
            payload.get("market_id"),
            payload.get("conditionId"),
            payload.get("condition_id"),
        )
        if not market_id:
            raise ValueError("market payload must include an id or conditionId")
        question = _first_text(payload.get("question"), payload.get("title"), payload.get("slug"))
        if not question:
            raise ValueError("market payload must include a question, title, or slug")

        return self.registry.shared().record_polymarket_gamma_market(
            environment=environment,
            market_id=market_id,
            condition_id=_first_text(payload.get("conditionId"), payload.get("condition_id")),
            slug=_first_text(payload.get("slug")),
            question=question,
            active=_bool(payload.get("active"), default=True),
            closed=_bool(payload.get("closed"), default=False),
            category=_first_text(payload.get("category"), payload.get("categorySlug")),
            end_date=_parse_datetime(payload.get("endDate") or payload.get("end_date")),
            tokens=_tokens_from_market(payload),
            tags=_tags_from_market(payload),
            raw_payload=payload,
            fetched_at=fetched_at,
        )

    def record_decoded_fill_event(
        self,
        *,
        environment: Environment,
        event: dict[str, Any],
        block_timestamp: datetime | None = None,
    ) -> dict:
        """Persist one decoded Polygon `OrderFilled` event payload."""

        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        block_number = _int(event.get("blockNumber") or event.get("block_number"))
        log_index = _int(event.get("logIndex") or event.get("log_index"))
        transaction_hash = _required_text(
            event.get("transactionHash") or event.get("transaction_hash"),
            "transaction hash",
        )
        return self.registry.shared().record_polymarket_chain_fill_event(
            environment=environment,
            exchange_contract=_first_text(event.get("address"), event.get("exchange_contract"))
            or POLYMARKET_CTF_EXCHANGE_V2,
            block_number=block_number,
            block_hash=_first_text(event.get("blockHash"), event.get("block_hash")),
            log_index=log_index,
            transaction_hash=transaction_hash,
            maker_address=_first_text(
                args.get("maker"),
                args.get("makerAddress"),
                args.get("maker_address"),
            ),
            taker_address=_first_text(
                args.get("taker"),
                args.get("takerAddress"),
                args.get("taker_address"),
            ),
            asset_id=_first_text(
                args.get("assetId"),
                args.get("asset_id"),
                args.get("tokenId"),
                args.get("token_id"),
                args.get("makerAssetId"),
                args.get("maker_asset_id"),
            ),
            market_id=_first_text(args.get("market"), args.get("marketId"), args.get("conditionId")),
            raw_event=event,
            block_timestamp=block_timestamp,
        )

    def record_processed_trade(
        self,
        *,
        environment: Environment,
        trade: dict[str, Any],
        raw_event_id: str | None = None,
        market_record_id: str | None = None,
    ) -> dict:
        """Persist one normalized trade row from chain or CSV-derived data."""

        price = _decimal(trade.get("price"), "price")
        size = _decimal(trade.get("size"), "size")
        notional = _decimal_or_none(trade.get("notional_usd"))
        if notional is None:
            notional = price * size
        traded_at = _parse_datetime(trade.get("traded_at") or trade.get("timestamp")) or datetime.now(UTC)
        return self.registry.shared().record_polymarket_trade(
            environment=environment,
            market_id=_required_text(
                trade.get("market_id") or trade.get("market") or trade.get("condition_id"),
                "market id",
            ),
            condition_id=_first_text(trade.get("condition_id")),
            asset_id=_required_text(trade.get("asset_id") or trade.get("token_id"), "asset id"),
            wallet_address=_required_text(
                trade.get("wallet_address") or trade.get("maker") or trade.get("maker_address"),
                "wallet address",
            ),
            side=_required_text(trade.get("side"), "side"),
            price=price,
            size=size,
            notional_usd=notional,
            realized_pnl_usd=_decimal_or_none(trade.get("realized_pnl_usd")),
            outcome=_first_text(trade.get("outcome")),
            role=_first_text(trade.get("role"), trade.get("trader_side")),
            transaction_hash=_required_text(
                trade.get("transaction_hash") or trade.get("tx_hash"),
                "transaction hash",
            ),
            block_number=_int(trade.get("block_number")),
            raw_event_id=raw_event_id,
            market_record_id=market_record_id,
            traded_at=traded_at,
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
        """Persist a resumable historical importer cursor."""

        return self.registry.shared().upsert_historical_import_checkpoint(
            environment=environment,
            source=source,
            cursor_type=cursor_type,
            cursor_value=cursor_value,
            status=status,
            metadata=metadata,
            last_success_at=last_success_at,
        )

    def build_target_wallet_snapshot(
        self,
        *,
        environment: Environment,
        min_trade_count: int = 100,
        min_win_rate: Decimal = Decimal("0.70"),
        limit: int = 50,
    ) -> dict:
        """Rank target wallets from persisted performance rows."""

        stats = self.registry.shared().polymarket_wallet_performance_stats(environment=environment)
        eligible = [
            row
            for row in stats
            if int(row["trade_count"]) >= min_trade_count
            and Decimal(str(row["win_rate"])) >= Decimal(str(min_win_rate))
        ]
        eligible.sort(
            key=lambda row: (
                Decimal(str(row["total_realized_pnl_usd"])),
                int(row["trade_count"]),
            ),
            reverse=True,
        )
        selected = eligible[: max(1, int(limit))]
        wallets = [
            {
                "walletAddress": row["wallet_address"],
                "tradeCount": row["trade_count"],
                "winRate": str(row["win_rate"]),
                "totalRealizedPnlUsd": str(row["total_realized_pnl_usd"]),
                "averageHoldSeconds": row.get("average_hold_seconds"),
                "sourceStatId": row["id"],
            }
            for row in selected
        ]
        return self.registry.shared().record_polymarket_target_wallet_snapshot(
            environment=environment,
            min_trade_count=min_trade_count,
            min_win_rate=min_win_rate,
            wallets=wallets,
            source_stat_ids=[row["id"] for row in selected],
        )

    def rebuild_wallet_performance_stats(
        self,
        *,
        environment: Environment,
        source: str = "polymarket_trades",
        calculated_at: datetime | None = None,
    ) -> list[dict]:
        """Aggregate persisted realized trades into wallet performance rows."""

        grouped: dict[str, list[dict[str, Any]]] = {}
        for trade in self.registry.shared().polymarket_trades(environment=environment):
            if trade.get("realized_pnl_usd") is None:
                continue
            wallet = _required_text(trade.get("wallet_address"), "wallet address").lower()
            grouped.setdefault(wallet, []).append(trade)

        observed_at = calculated_at or datetime.now(UTC)
        stats: list[dict] = []
        for wallet, trades in grouped.items():
            realized_values = [
                Decimal(str(trade["realized_pnl_usd"]))
                for trade in trades
                if trade.get("realized_pnl_usd") is not None
            ]
            if not realized_values:
                continue
            trade_count = len(realized_values)
            win_count = sum(1 for value in realized_values if value > 0)
            total_realized = sum(realized_values, Decimal("0"))
            win_rate = Decimal(win_count) / Decimal(trade_count)
            stats.append(
                self.registry.shared().record_polymarket_wallet_performance_stat(
                    environment=environment,
                    wallet_address=wallet,
                    trade_count=trade_count,
                    win_rate=win_rate,
                    total_realized_pnl_usd=total_realized,
                    source=source,
                    calculated_at=observed_at,
                )
            )
        stats.sort(
            key=lambda row: (
                Decimal(str(row["total_realized_pnl_usd"])),
                int(row["trade_count"]),
            ),
            reverse=True,
        )
        return stats

    def join_fill_event_to_market_metadata(
        self,
        *,
        environment: Environment,
        fill_event: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Resolve a fill event asset id to persisted Gamma market metadata."""

        asset_id = _first_text(
            fill_event.get("asset_id"),
            fill_event.get("assetId"),
            fill_event.get("token_id"),
            fill_event.get("tokenId"),
        )
        if not asset_id:
            raw_event = fill_event.get("raw_event")
            args = raw_event.get("args") if isinstance(raw_event, dict) else None
            if isinstance(args, dict):
                asset_id = _first_text(args.get("assetId"), args.get("tokenId"))
        if not asset_id:
            return None

        for market in self.registry.shared().polymarket_gamma_markets(environment=environment):
            for token in market.get("tokens") or []:
                if not isinstance(token, dict):
                    continue
                token_id = _first_text(
                    token.get("token_id"),
                    token.get("tokenId"),
                    token.get("id"),
                    token.get("asset_id"),
                    token.get("assetId"),
                )
                if token_id != str(asset_id):
                    continue
                return {
                    "marketRecordId": market["id"],
                    "marketId": market["market_id"],
                    "conditionId": market.get("condition_id"),
                    "assetId": str(asset_id),
                    "outcome": _first_text(token.get("outcome"), token.get("name")),
                    "question": market.get("question"),
                    "slug": market.get("slug"),
                    "category": market.get("category"),
                    "endDate": _isoformat_datetime(market.get("end_date")),
                }
        return None


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


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any) -> int:
    try:
        text = str(value).strip()
        base = 16 if text.lower().startswith("0x") else 10
        return max(0, int(text, base))
    except (TypeError, ValueError):
        return 0


def decode_order_filled_v2_log(log: dict[str, Any]) -> dict[str, Any]:
    """Decode the CTF Exchange V2 OrderFilled event fields from an EVM log."""

    topics = log.get("topics") if isinstance(log.get("topics"), list) else []
    if len(topics) < 4:
        raise ValueError("OrderFilled log must include event, order, maker, and taker topics")
    words = _hex_words(log.get("data"))
    if len(words) < 7:
        raise ValueError("OrderFilled log data must include seven encoded fields")
    decoded = dict(log)
    decoded["event"] = "OrderFilled"
    decoded["args"] = {
        "orderHash": _normalize_topic(topics[1]),
        "maker": _address_from_topic(topics[2]),
        "taker": _address_from_topic(topics[3]),
        "side": _int_from_word(words[0]),
        "tokenId": str(_int_from_word(words[1])),
        "makerAmountFilled": str(_int_from_word(words[2])),
        "takerAmountFilled": str(_int_from_word(words[3])),
        "fee": str(_int_from_word(words[4])),
        "builder": _word_to_hex(words[5]),
        "metadata": _word_to_hex(words[6]),
    }
    return decoded


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


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _isoformat_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _tokens_from_market(payload: dict[str, Any]) -> list[Any]:
    tokens = payload.get("tokens")
    if isinstance(tokens, list):
        return tokens
    token_ids = payload.get("clobTokenIds") or payload.get("clob_token_ids") or payload.get("tokenIds")
    if isinstance(token_ids, list):
        outcomes = payload.get("outcomes") if isinstance(payload.get("outcomes"), list) else []
        return [
            {"token_id": token_id, "outcome": outcomes[index] if index < len(outcomes) else None}
            for index, token_id in enumerate(token_ids)
        ]
    return []


def _tags_from_market(payload: dict[str, Any]) -> list[Any]:
    tags = payload.get("tags")
    if isinstance(tags, list):
        return tags
    tag = _first_text(payload.get("tag"), payload.get("category"))
    return [tag] if tag else []


def _base_url(value: str | None, default: str) -> str:
    text = (value or default).strip().rstrip("/")
    return text or default


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _gamma_market_source(*, active: bool | None, closed: bool | None) -> str:
    parts = [POLYMARKET_GAMMA_MARKET_SOURCE]
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if closed is not None:
        parts.append(f"closed={str(closed).lower()}")
    return ":".join(parts)


def _checkpoint_offset(
    registry: RepositoryRegistry,
    *,
    environment: Environment,
    source: str,
) -> int:
    for row in registry.shared().historical_import_checkpoints(environment=environment):
        if row["source"] == source and row["cursor_type"] == "offset":
            return _int(row.get("cursor_value"))
    return 0


def _gamma_market_params(
    *,
    limit: int,
    offset: int,
    active: bool | None,
    closed: bool | None,
    order: str | None,
    ascending: bool | None,
) -> dict[str, str]:
    params = {"limit": str(limit), "offset": str(offset)}
    if active is not None:
        params["active"] = str(active).lower()
    if closed is not None:
        params["closed"] = str(closed).lower()
    if order:
        params["order"] = order
    if ascending is not None:
        params["ascending"] = str(ascending).lower()
    return params


def _gamma_market_items(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("markets", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_address(value: str) -> str:
    text = value.strip().lower()
    if not text:
        raise ValueError("address is required")
    return text if text.startswith("0x") else f"0x{text}"


def _normalize_topic(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return text if text.startswith("0x") else f"0x{text}"


def _polygon_order_filled_source(
    *,
    exchange_contract: str,
    order_filled_topic: str | None,
) -> str:
    parts = [POLYMARKET_POLYGON_ORDER_FILLED_SOURCE, exchange_contract.lower()]
    if order_filled_topic:
        parts.append(order_filled_topic.lower())
    return ":".join(parts)


def _checkpoint_block_number(
    registry: RepositoryRegistry,
    *,
    environment: Environment,
    source: str,
) -> int:
    for row in registry.shared().historical_import_checkpoints(environment=environment):
        if row["source"] == source and row["cursor_type"] == "block_number":
            return _int(row.get("cursor_value"))
    return -1


def _hex_block(value: int) -> str:
    return hex(max(0, int(value)))


def _rpc_error_is_window_retryable(*, message: str) -> bool:
    text = message.lower()
    return any(
        marker in text
        for marker in (
            "too many",
            "more than",
            "block range",
            "range too",
            "exceed",
            "limit",
            "timeout",
        )
    )


def _hex_words(value: Any) -> list[str]:
    text = _normalize_topic(str(value) if value is not None else "") or "0x"
    body = text[2:]
    if len(body) % 64 != 0:
        raise ValueError("hex data must be 32-byte word aligned")
    return [body[index : index + 64] for index in range(0, len(body), 64)]


def _int_from_word(word: str) -> int:
    return int(word, 16)


def _word_to_hex(word: str) -> str:
    return f"0x{word.lower()}"


def _address_from_topic(topic: Any) -> str:
    text = _normalize_topic(str(topic))
    if text is None or len(text) < 42:
        raise ValueError("address topic is invalid")
    return f"0x{text[-40:]}"
