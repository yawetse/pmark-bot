"""Clean-room Polymarket historical trade import helpers.

REQ: REQ-DAT-009, REQ-STR-002, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db import RepositoryRegistry
from app.domain import Environment


POLYMARKET_CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"


@dataclass(frozen=True)
class PolymarketHistoricalImportSummary:
    """Summary of records written by one historical import slice."""

    environment: Environment
    market_count: int = 0
    chain_fill_count: int = 0
    trade_count: int = 0
    checkpoint_id: str | None = None
    target_wallet_snapshot_id: str | None = None


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
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


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
