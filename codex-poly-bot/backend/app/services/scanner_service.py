"""Deterministic scanner persistence for Polymarket and stock candidates.

REQ: REQ-STR-003, REQ-DAT-008, REQ-DB-009, REQ-OBS-005, REQ-UI-004,
REQ-KAL-001, REQ-KAL-002
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db import PersistenceUnavailableError, RepositoryRegistry, UnitOfWork
from app.domain import Environment, Venue
from app.services.stock_universe import resolve_alpaca_symbol_universe


DEFAULT_POLYMARKET_MARKET_DATA_LIMIT = 100
MAX_POLYMARKET_MARKET_DATA_LIMIT = 250

DEFAULT_SCANNER_CONFIG: dict[str, Any] = {
    "polymarket": {
        "market_data_limit": DEFAULT_POLYMARKET_MARKET_DATA_LIMIT,
        "min_depth": "500",
        "min_liquidity": "500",
        "max_spread": "0.05",
        "min_volume": "0",
        "min_hours_to_resolution": "4",
        "max_hours_to_resolution": "168",
        "allowed_categories": [],
        "blocked_categories": [],
        "target_wallet_recent_hours": 72,
    },
    "alpaca": {
        "min_quote_liquidity": "0.5",
        "max_spread": "1.00",
        "min_history_bars": 2,
        "strategies": {
            "momentum": {"enabled": True, "min_change_pct": "0.005"},
            "mean_reversion": {"enabled": True, "min_deviation_pct": "0.01"},
            "gap": {"enabled": True, "min_gap_pct": "0.01"},
            "liquidity": {"enabled": True, "min_volume": "100000"},
            "volatility": {"enabled": True, "min_range_pct": "0.015"},
            "unusual_volume": {"enabled": True, "min_ratio": "1.25"},
        },
    },
    Venue.KALSHI.value: {
        "market_data_limit": DEFAULT_POLYMARKET_MARKET_DATA_LIMIT,
        "min_depth": "5",
        "min_liquidity": "10",
        "max_spread": "0.05",
        "min_volume": "0",
        "min_hours_to_resolution": "4",
        "max_hours_to_resolution": "168",
        "allowed_categories": [],
        "blocked_categories": [],
        "target_wallet_recent_hours": 72,
    },
}


@dataclass(frozen=True)
class ScannerRunResult:
    """One persisted scanner run with dashboard-ready candidate rows."""

    row: dict[str, Any] | None
    candidates: tuple[dict[str, Any], ...]
    payload: dict[str, Any]


class ScannerService:
    """Apply deterministic scanner filters and persist accepted/rejected candidates."""

    def __init__(self, registry: RepositoryRegistry) -> None:
        self.registry = registry

    def run(
        self,
        *,
        environment: Environment,
        pipeline_run_id: str,
        trigger: str,
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        started_at: datetime,
        completed_at: datetime | None = None,
    ) -> ScannerRunResult:
        """Scan provider candidates and persist one scanner run."""

        finished_at = completed_at or datetime.now(UTC)
        scanner_config = scanner_config_from_payload(config_payload)
        source_pull_ids = [pull["id"] for pull in market_data_pulls if pull.get("id")]
        candidate_results = self._scan_candidates(
            environment=environment,
            market_data_pulls=market_data_pulls,
            config_payload=config_payload,
            scanner_config=scanner_config,
            scanned_at=finished_at,
        )
        accepted_count = sum(1 for candidate in candidate_results if candidate["status"] == "accepted")
        rejected_count = sum(1 for candidate in candidate_results if candidate["status"] == "rejected")
        status = _scanner_status(
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            pull_statuses=[str(pull.get("status", "idle")) for pull in market_data_pulls],
        )

        try:
            # Persist the run and its candidate rows in one transaction. Production
            # ticks can contain hundreds of candidates, so per-row commits exhaust
            # small RDS volume I/O credits and delay dashboard reads.
            with UnitOfWork(self.registry.state) as unit:
                run_row = self.registry.shared().record_scanner_run(
                    environment=environment,
                    pipeline_run_id=pipeline_run_id,
                    trigger=trigger,
                    status=status,
                    config=scanner_config,
                    source_pull_ids=source_pull_ids,
                    accepted_count=accepted_count,
                    rejected_count=rejected_count,
                    started_at=started_at,
                    completed_at=finished_at,
                )
                persisted_candidates = tuple(
                    self.registry.shared().record_scanner_candidate(
                        environment=environment,
                        scanner_run_id=run_row["id"],
                        venue=candidate["venue"],
                        instrument_id=candidate["instrument_id"],
                        display_name=candidate["display_name"],
                        status=candidate["status"],
                        refusal_reason=candidate.get("refusal_reason"),
                        strategy_names=candidate.get("strategy_names", []),
                        price=candidate.get("price"),
                        liquidity=candidate.get("liquidity"),
                        spread=candidate.get("spread"),
                        hours_to_resolution=candidate.get("hours_to_resolution"),
                        metrics=candidate.get("metrics", {}),
                        source_payload=candidate.get("source_payload", {}),
                        symbol=candidate.get("symbol"),
                        market_id=candidate.get("market_id"),
                        outcome_id=candidate.get("outcome_id"),
                        created_at=finished_at,
                    )
                    for candidate in candidate_results
                )
                unit.commit()
        except PersistenceUnavailableError:
            run_row = None
            persisted_candidates = tuple(candidate_results)

        payload = scanner_run_payload(run_row, persisted_candidates, fallback={
            "id": None,
            "environment": environment.value,
            "pipeline_run_id": pipeline_run_id,
            "trigger": trigger,
            "status": status,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "started_at": started_at,
            "completed_at": finished_at,
            "source_pull_ids": source_pull_ids,
            "config": scanner_config,
        })
        return ScannerRunResult(row=run_row, candidates=persisted_candidates, payload=payload)

    def _scan_candidates(
        self,
        *,
        environment: Environment,
        market_data_pulls: list[dict[str, Any]],
        config_payload: dict[str, Any],
        scanner_config: dict[str, Any],
        scanned_at: datetime,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        symbol_universe = {
            key
            for symbol in resolve_alpaca_symbol_universe(config_payload)
            for key in _stock_symbol_keys(symbol)
        }
        for pull in market_data_pulls:
            for candidate in pull.get("candidates", []):
                if not isinstance(candidate, dict):
                    continue
                venue = str(candidate.get("venue") or pull.get("venue") or "")
                if venue == Venue.KALSHI.value and not _kalshi_scanning_enabled(
                    config_payload
                ):
                    continue
                if venue == Venue.ALPACA.value:
                    results.append(
                        self._scan_stock_candidate(
                            environment=environment,
                            candidate=candidate,
                            symbol_universe=symbol_universe,
                            config=scanner_config["alpaca"],
                            scanned_at=scanned_at,
                        )
                    )
                elif venue in {
                    Venue.POLYMARKET_US.value,
                    Venue.POLYMARKET_INTERNATIONAL.value,
                    Venue.KALSHI.value,
                }:
                    results.append(
                        self._scan_polymarket_candidate(
                            environment=environment,
                            candidate=candidate,
                            config=scanner_config[
                                Venue.KALSHI.value if venue == Venue.KALSHI.value else "polymarket"
                            ],
                            scanned_at=scanned_at,
                        )
                    )
        return results
    def _scan_polymarket_candidate(
        self,
        *,
        environment: Environment,
        candidate: dict[str, Any],
        config: dict[str, Any],
        scanned_at: datetime,
    ) -> dict[str, Any]:
        price = _decimal_or_none(candidate.get("midpoint") or candidate.get("price"))
        liquidity = _decimal_or_zero(candidate.get("liquidity"))
        spread = _decimal_or_none(candidate.get("spread"))
        bid_depth = _decimal_or_zero(candidate.get("bidDepth"))
        ask_depth = _decimal_or_zero(candidate.get("askDepth"))
        volume = _decimal_or_zero(candidate.get("volume"))
        end_at = _parse_datetime(candidate.get("endDate"))
        hours_to_resolution = (
            Decimal(str((end_at - scanned_at).total_seconds())) / Decimal("3600")
            if end_at is not None
            else None
        )
        category = str(candidate.get("category") or "").strip()
        target_overlap = (
            {"count": 0, "wallets": []}
            if candidate.get("venue") == Venue.KALSHI.value
            else self._target_wallet_overlap(
                environment=environment,
                market_id=_market_id(candidate),
                outcome_id=_outcome_id(candidate),
                scanned_at=scanned_at,
                recent_hours=_int_setting(config.get("target_wallet_recent_hours"), 72),
            )
        )
        metrics = {
            "midpoint": _string_or_none(price),
            "bestBid": candidate.get("bestBid"),
            "bestAsk": candidate.get("bestAsk"),
            "bidDepth": _string_or_none(bid_depth),
            "askDepth": _string_or_none(ask_depth),
            "minSideDepth": _string_or_none(min(bid_depth, ask_depth)),
            "volume": _string_or_none(volume),
            "category": category or None,
            "hoursToResolution": _string_or_none(hours_to_resolution),
            "targetWalletOverlap": target_overlap["count"],
            "targetWallets": target_overlap["wallets"],
        }
        refusal = _polymarket_refusal(
            candidate=candidate,
            price=price,
            liquidity=liquidity,
            spread=spread,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            volume=volume,
            hours_to_resolution=hours_to_resolution,
            category=category,
            config=config,
        )
        return _scanner_candidate_payload(
            candidate=candidate,
            venue=str(candidate.get("venue") or Venue.POLYMARKET_US.value),
            instrument_id=str(candidate.get("id") or _outcome_id(candidate) or _market_id(candidate)),
            display_name=str(candidate.get("market") or _market_id(candidate) or "Polymarket candidate"),
            status="rejected" if refusal else "accepted",
            refusal_reason=refusal,
            strategy_names=[] if refusal else ["order_book_depth", "resolution_window"],
            price=price,
            liquidity=liquidity,
            spread=spread,
            hours_to_resolution=hours_to_resolution,
            metrics=metrics,
            market_id=_market_id(candidate),
            outcome_id=_outcome_id(candidate),
        )

    def _target_wallet_overlap(
        self,
        *,
        environment: Environment,
        market_id: str | None,
        outcome_id: str | None,
        scanned_at: datetime,
        recent_hours: int,
    ) -> dict[str, Any]:
        if not market_id and not outcome_id:
            return {"count": 0, "wallets": []}
        snapshots = self.registry.shared().polymarket_target_wallet_snapshots(
            environment=environment
        )
        if not snapshots:
            return {"count": 0, "wallets": []}
        latest = max(snapshots, key=lambda row: row.get("created_at") or datetime.min.replace(tzinfo=UTC))
        target_wallets = _wallets_from_snapshot(latest)
        if not target_wallets:
            return {"count": 0, "wallets": []}
        since = scanned_at - timedelta(hours=max(1, recent_hours))
        matched: set[str] = set()
        for position in self.registry.state.rows("shared.polymarket_wallet_positions"):
            if position.get("environment") != environment.value:
                continue
            wallet = str(position.get("wallet_address") or "").lower()
            if wallet not in target_wallets:
                continue
            if _market_matches(position, market_id, outcome_id) and position.get("state") == "open":
                matched.add(wallet)
        for trade in self.registry.shared().polymarket_trades(environment=environment):
            wallet = str(trade.get("wallet_address") or "").lower()
            if wallet not in target_wallets:
                continue
            traded_at = trade.get("traded_at")
            if (
                isinstance(traded_at, datetime)
                and traded_at >= since
                and _market_matches(trade, market_id, outcome_id)
            ):
                matched.add(wallet)
        wallets = sorted(matched)
        return {"count": len(wallets), "wallets": wallets[:20]}

    def _scan_stock_candidate(
        self,
        *,
        environment: Environment,
        candidate: dict[str, Any],
        symbol_universe: set[str],
        config: dict[str, Any],
        scanned_at: datetime,
    ) -> dict[str, Any]:
        symbol = str(candidate.get("symbol") or "").strip().upper()
        price = _decimal_or_none(candidate.get("price"))
        liquidity = _decimal_or_zero(candidate.get("liquidity"))
        spread = _decimal_or_none(candidate.get("spread"))
        bars = _stock_bars_for_symbol(
            self.registry,
            environment=environment,
            symbol=symbol,
            fallback_candidate=candidate,
        )
        metrics = _stock_metrics(price=price, candidate=candidate, bars=bars)
        strategies = _stock_strategy_matches(metrics, config.get("strategies", {}))
        refusal = _stock_refusal(
            candidate=candidate,
            symbol=symbol,
            symbol_universe=symbol_universe,
            price=price,
            liquidity=liquidity,
            spread=spread,
            bars=bars,
            strategies=strategies,
            config=config,
        )
        return _scanner_candidate_payload(
            candidate=candidate,
            venue=Venue.ALPACA.value,
            instrument_id=str(candidate.get("id") or f"{Venue.ALPACA.value}:{symbol}"),
            display_name=symbol or "Alpaca candidate",
            status="rejected" if refusal else "accepted",
            refusal_reason=refusal,
            strategy_names=[] if refusal else strategies,
            price=price,
            liquidity=liquidity,
            spread=spread,
            hours_to_resolution=None,
            metrics={**metrics, "scannedAt": scanned_at.isoformat()},
            symbol=symbol,
        )


def _kalshi_scanning_enabled(config_payload: dict[str, Any]) -> bool:
    venues = config_payload.get("venues") if isinstance(config_payload, dict) else None
    kalshi = venues.get(Venue.KALSHI.value) if isinstance(venues, dict) else None
    return bool(kalshi.get("enabled", False)) if isinstance(kalshi, dict) else False


def scanner_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    """Merge scanner defaults with runtime config."""

    configured = config_payload.get("scanner")
    if not isinstance(configured, dict):
        configured = {}
    return {
        "polymarket": _merge_dicts(
            DEFAULT_SCANNER_CONFIG["polymarket"],
            configured.get("polymarket") if isinstance(configured.get("polymarket"), dict) else {},
        ),
        "alpaca": _merge_dicts(
            DEFAULT_SCANNER_CONFIG["alpaca"],
            configured.get("alpaca") if isinstance(configured.get("alpaca"), dict) else {},
        ),
        Venue.KALSHI.value: _merge_dicts(
            DEFAULT_SCANNER_CONFIG[Venue.KALSHI.value],
            configured.get(Venue.KALSHI.value)
            if isinstance(configured.get(Venue.KALSHI.value), dict)
            else {},
        ),
    }


def scanner_run_payload(
    row: dict[str, Any] | None,
    candidates: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a dashboard-safe scanner run payload."""

    source = row or fallback or {}
    candidate_payloads = [_scanner_candidate_view(candidate) for candidate in candidates]
    accepted = [candidate for candidate in candidate_payloads if candidate["status"] == "accepted"]
    rejected = [candidate for candidate in candidate_payloads if candidate["status"] == "rejected"]
    return {
        "id": source.get("id"),
        "environment": source.get("environment"),
        "pipelineRunId": source.get("pipeline_run_id"),
        "trigger": source.get("trigger"),
        "status": source.get("status", "idle"),
        "acceptedCount": _int_setting(source.get("accepted_count"), len(accepted)),
        "rejectedCount": _int_setting(source.get("rejected_count"), len(rejected)),
        "candidateCount": len(candidate_payloads),
        "sourcePullIds": source.get("source_pull_ids", []),
        "startedAt": _isoformat_or_none(source.get("started_at")),
        "completedAt": _isoformat_or_none(source.get("completed_at")),
        "config": source.get("config", {}),
        "candidates": candidate_payloads,
    }


def _scanner_candidate_payload(
    *,
    candidate: dict[str, Any],
    venue: str,
    instrument_id: str,
    display_name: str,
    status: str,
    refusal_reason: str | None,
    strategy_names: list[str],
    price: Decimal | None,
    liquidity: Decimal | None,
    spread: Decimal | None,
    hours_to_resolution: Decimal | None,
    metrics: dict[str, Any],
    symbol: str | None = None,
    market_id: str | None = None,
    outcome_id: str | None = None,
) -> dict[str, Any]:
    return {
        "venue": venue,
        "instrument_id": instrument_id,
        "display_name": display_name,
        "symbol": symbol,
        "market_id": market_id,
        "outcome_id": outcome_id,
        "status": status,
        "refusal_reason": refusal_reason,
        "strategy_names": strategy_names,
        "price": price,
        "liquidity": liquidity,
        "spread": spread,
        "hours_to_resolution": hours_to_resolution,
        "metrics": metrics,
        "source_payload": candidate,
    }


def _scanner_candidate_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id") or row.get("instrument_id"),
        "scannerRunId": row.get("scanner_run_id"),
        "venue": row.get("venue"),
        "instrumentId": row.get("instrument_id"),
        "displayName": row.get("display_name"),
        "symbol": row.get("symbol"),
        "marketId": row.get("market_id"),
        "outcomeId": row.get("outcome_id"),
        "status": row.get("status"),
        "refusalReason": row.get("refusal_reason"),
        "strategyNames": row.get("strategy_names", []),
        "price": _string_or_none(row.get("price")),
        "liquidity": _string_or_none(row.get("liquidity")),
        "spread": _string_or_none(row.get("spread")),
        "hoursToResolution": _string_or_none(row.get("hours_to_resolution")),
        "metrics": row.get("metrics", {}),
        "createdAt": _isoformat_or_none(row.get("created_at")),
    }


def _scanner_status(
    *,
    accepted_count: int,
    rejected_count: int,
    pull_statuses: list[str],
) -> str:
    if accepted_count:
        return "completed"
    if rejected_count:
        return "no_candidates_passed"
    if any(status in {"failed", "rate_limited"} for status in pull_statuses):
        return "blocked"
    return "empty"


def _polymarket_refusal(
    *,
    candidate: dict[str, Any],
    price: Decimal | None,
    liquidity: Decimal,
    spread: Decimal | None,
    bid_depth: Decimal,
    ask_depth: Decimal,
    volume: Decimal,
    hours_to_resolution: Decimal | None,
    category: str,
    config: dict[str, Any],
) -> str | None:
    if not bool(candidate.get("active", True)):
        return "market inactive"
    if bool(candidate.get("closed", False)):
        return "market closed"
    if price is None:
        return "midpoint missing"
    if liquidity < _decimal_setting(config.get("min_liquidity"), "500"):
        return "liquidity below minimum"
    min_depth = _decimal_setting(config.get("min_depth"), "500")
    if bid_depth < min_depth:
        return "bid depth below minimum"
    if ask_depth < min_depth:
        return "ask depth below minimum"
    max_spread = _decimal_setting(config.get("max_spread"), "0.05")
    if spread is None:
        return "spread missing"
    if spread > max_spread:
        return "spread too wide"
    if hours_to_resolution is None:
        return "resolution timestamp missing"
    if hours_to_resolution < _decimal_setting(config.get("min_hours_to_resolution"), "4"):
        return "resolution too near"
    if hours_to_resolution > _decimal_setting(config.get("max_hours_to_resolution"), "168"):
        return "resolution too far"
    if volume < _decimal_setting(config.get("min_volume"), "0"):
        return "volume below minimum"
    allowed = {str(item).lower() for item in config.get("allowed_categories", []) if str(item).strip()}
    blocked = {str(item).lower() for item in config.get("blocked_categories", []) if str(item).strip()}
    category_key = category.lower()
    if allowed and category_key not in allowed:
        return "category outside allowlist"
    if blocked and category_key in blocked:
        return "category blocked"
    return None


def _stock_refusal(
    *,
    candidate: dict[str, Any],
    symbol: str,
    symbol_universe: set[str],
    price: Decimal | None,
    liquidity: Decimal,
    spread: Decimal | None,
    bars: list[dict[str, Any]],
    strategies: list[str],
    config: dict[str, Any],
) -> str | None:
    if candidate.get("state") != "priced":
        return "candidate unpriced"
    if not symbol:
        return "symbol missing"
    if symbol_universe and not any(key in symbol_universe for key in _stock_symbol_keys(symbol)):
        return "symbol outside universe"
    if price is None:
        return "price missing"
    if liquidity < _decimal_setting(config.get("min_quote_liquidity"), "0.5"):
        return "quote liquidity below minimum"
    max_spread = _decimal_setting(config.get("max_spread"), "1.00")
    if spread is None:
        return "spread missing"
    if spread > max_spread:
        return "spread too wide"
    if len(bars) < _int_setting(config.get("min_history_bars"), 2):
        return "insufficient historical bars"
    if not strategies:
        return "no stock strategy threshold met"
    return None


def _stock_strategy_matches(metrics: dict[str, Any], strategies_config: dict[str, Any]) -> list[str]:
    matched: list[str] = []
    momentum = _decimal_or_none(metrics.get("momentumPct"))
    mean_reversion = _decimal_or_none(metrics.get("meanReversionPct"))
    gap = _decimal_or_none(metrics.get("gapPct"))
    volume = _decimal_or_none(metrics.get("latestVolume"))
    volatility = _decimal_or_none(metrics.get("rangePct"))
    unusual_volume = _decimal_or_none(metrics.get("unusualVolumeRatio"))

    if _strategy_enabled(strategies_config, "momentum") and momentum is not None:
        if momentum >= _strategy_decimal(strategies_config, "momentum", "min_change_pct", "0.01"):
            matched.append("momentum")
    if _strategy_enabled(strategies_config, "mean_reversion") and mean_reversion is not None:
        if abs(mean_reversion) >= _strategy_decimal(
            strategies_config, "mean_reversion", "min_deviation_pct", "0.02"
        ):
            matched.append("mean_reversion")
    if _strategy_enabled(strategies_config, "gap") and gap is not None:
        if abs(gap) >= _strategy_decimal(strategies_config, "gap", "min_gap_pct", "0.015"):
            matched.append("gap")
    if _strategy_enabled(strategies_config, "liquidity") and volume is not None:
        if volume >= _strategy_decimal(strategies_config, "liquidity", "min_volume", "100000"):
            matched.append("liquidity")
    if _strategy_enabled(strategies_config, "volatility") and volatility is not None:
        if volatility >= _strategy_decimal(strategies_config, "volatility", "min_range_pct", "0.02"):
            matched.append("volatility")
    if _strategy_enabled(strategies_config, "unusual_volume") and unusual_volume is not None:
        if unusual_volume >= _strategy_decimal(strategies_config, "unusual_volume", "min_ratio", "1.50"):
            matched.append("unusual_volume")
    return matched


def _stock_metrics(
    *,
    price: Decimal | None,
    candidate: dict[str, Any],
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_bar = bars[-1] if bars else {}
    prior_bars = bars[:-1]
    previous_close = _decimal_or_none(candidate.get("previousClose"))
    if previous_close is None and len(bars) >= 2:
        previous_close = _decimal_or_none(bars[-2].get("close_price"))
    latest_close = _decimal_or_none(latest_bar.get("close_price")) or price
    latest_open = _decimal_or_none(candidate.get("latestOpen")) or _decimal_or_none(latest_bar.get("open_price"))
    latest_high = _decimal_or_none(candidate.get("latestHigh")) or _decimal_or_none(latest_bar.get("high_price"))
    latest_low = _decimal_or_none(candidate.get("latestLow")) or _decimal_or_none(latest_bar.get("low_price"))
    latest_volume = (
        _decimal_or_none(candidate.get("latestVolume"))
        or _decimal_or_none(latest_bar.get("volume"))
        or _decimal_or_none(candidate.get("liquidity"))
    )
    average_volume = _decimal_or_none(candidate.get("averageVolume")) or _average(
        [_decimal_or_none(bar.get("volume")) for bar in prior_bars]
    )
    sma = _average([_decimal_or_none(bar.get("close_price")) for bar in bars])
    first_close = _decimal_or_none(bars[0].get("close_price")) if bars else previous_close

    metrics = {
        "historyBarCount": len(bars),
        "previousClose": _string_or_none(previous_close),
        "latestOpen": _string_or_none(latest_open),
        "latestHigh": _string_or_none(latest_high),
        "latestLow": _string_or_none(latest_low),
        "latestClose": _string_or_none(latest_close),
        "latestVolume": _string_or_none(latest_volume),
        "averageVolume": _string_or_none(average_volume),
        "simpleMovingAverage": _string_or_none(sma),
        "priceChangePct": _string_or_none(_pct_change(price, previous_close)),
        "momentumPct": _string_or_none(_pct_change(price, first_close)),
        "meanReversionPct": _string_or_none(_pct_change(price, sma)),
        "gapPct": _string_or_none(_pct_change(latest_open, previous_close)),
        "rangePct": _string_or_none(_range_pct(latest_high, latest_low, latest_close)),
        "unusualVolumeRatio": _string_or_none(_ratio(latest_volume, average_volume)),
    }
    return metrics


def _stock_bars_for_symbol(
    registry: RepositoryRegistry,
    *,
    environment: Environment,
    symbol: str,
    fallback_candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    for key in _stock_symbol_keys(symbol):
        bars = registry.shared().stock_bars(
            environment=environment,
            symbol=key,
            timeframe="1Day",
        )
        bars.sort(key=lambda row: row.get("bar_start_at") or datetime.min.replace(tzinfo=UTC))
        if bars:
            return bars
    history_count = _int_setting(fallback_candidate.get("historyBarCount"), 0)
    if history_count >= 2:
        return _synthetic_bars_from_candidate(fallback_candidate)
    return []


def _synthetic_bars_from_candidate(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    previous_close = _decimal_or_none(candidate.get("previousClose"))
    latest_close = _decimal_or_none(candidate.get("latestClose") or candidate.get("price"))
    if previous_close is None or latest_close is None:
        return []
    latest_open = _decimal_or_none(candidate.get("latestOpen")) or previous_close
    latest_high = _decimal_or_none(candidate.get("latestHigh")) or max(latest_open, latest_close)
    latest_low = _decimal_or_none(candidate.get("latestLow")) or min(latest_open, latest_close)
    latest_volume = _decimal_or_none(candidate.get("latestVolume")) or Decimal("0")
    average_volume = _decimal_or_none(candidate.get("averageVolume")) or latest_volume
    now = datetime.now(UTC)
    return [
        {
            "bar_start_at": now - timedelta(days=1),
            "open_price": previous_close,
            "high_price": previous_close,
            "low_price": previous_close,
            "close_price": previous_close,
            "volume": average_volume,
        },
        {
            "bar_start_at": now,
            "open_price": latest_open,
            "high_price": latest_high,
            "low_price": latest_low,
            "close_price": latest_close,
            "volume": latest_volume,
        },
    ]


def _stock_symbol_keys(symbol: Any) -> tuple[str, ...]:
    text = str(symbol or "").strip().upper()
    if not text:
        return ()
    aliases = [text]
    if "." in text:
        aliases.append(text.replace(".", "-"))
    if "-" in text:
        aliases.append(text.replace("-", "."))
    return tuple(dict.fromkeys(aliases))


def _market_id(candidate: dict[str, Any]) -> str | None:
    value = candidate.get("marketId") or candidate.get("conditionId")
    if value is not None:
        return str(value)
    raw_id = str(candidate.get("id") or "")
    parts = raw_id.split(":")
    return parts[1] if len(parts) >= 3 else None


def _outcome_id(candidate: dict[str, Any]) -> str | None:
    value = candidate.get("tokenId") or candidate.get("outcomeId")
    if value is not None:
        return str(value)
    raw_id = str(candidate.get("id") or "")
    parts = raw_id.split(":")
    return parts[2] if len(parts) >= 3 else None


def _wallets_from_snapshot(snapshot: dict[str, Any]) -> set[str]:
    wallets = set()
    for item in snapshot.get("wallets", []):
        if isinstance(item, dict):
            value = item.get("walletAddress") or item.get("wallet_address") or item.get("wallet")
        else:
            value = item
        if value:
            wallets.add(str(value).lower())
    return wallets


def _market_matches(row: dict[str, Any], market_id: str | None, outcome_id: str | None) -> bool:
    if market_id and str(row.get("market_id")) == market_id:
        return True
    if outcome_id and str(row.get("asset_id")) == outcome_id:
        return True
    return False


def _merge_dicts(default: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(default)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _strategy_enabled(config: dict[str, Any], name: str) -> bool:
    strategy = config.get(name, {})
    return not isinstance(strategy, dict) or bool(strategy.get("enabled", True))


def _strategy_decimal(config: dict[str, Any], name: str, key: str, default: str) -> Decimal:
    strategy = config.get(name, {})
    if not isinstance(strategy, dict):
        return Decimal(default)
    return _decimal_setting(strategy.get(key), default)


def _decimal_setting(value: Any, default: str) -> Decimal:
    parsed = _decimal_or_none(value)
    return parsed if parsed is not None else Decimal(default)


def _int_setting(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _decimal_or_zero(value: Any) -> Decimal:
    return _decimal_or_none(value) or Decimal("0")


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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _average(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present, Decimal("0")) / Decimal(len(present))


def _pct_change(current: Decimal | None, prior: Decimal | None) -> Decimal | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / prior


def _range_pct(high: Decimal | None, low: Decimal | None, close: Decimal | None) -> Decimal | None:
    if high is None or low is None or close is None or close == 0:
        return None
    return (high - low) / close


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _isoformat_or_none(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
