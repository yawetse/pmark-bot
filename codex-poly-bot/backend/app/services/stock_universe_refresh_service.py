"""Refresh Alpaca stock universe preset memberships.

REQ: REQ-ALP-015, REQ-DAT-008, REQ-OBS-005
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from app.db import PersistenceUnavailableError, RepositoryRegistry
from app.domain import Environment
from app.services.stock_universe import (
    DEFAULT_ALPACA_PRESET_REFRESH_CONFIG,
    DEFAULT_ALPACA_SYMBOL_PRESETS,
    normalize_preset_name,
    normalize_symbol_list,
    seed_alpaca_preset_snapshots,
)


@dataclass(frozen=True)
class StockUniversePresetSnapshot:
    """One refreshed preset membership snapshot."""

    preset_name: str
    symbols: tuple[str, ...]
    source: str
    source_url: str | None
    status: str
    effective_at: datetime
    refreshed_at: datetime
    message: str


@dataclass(frozen=True)
class StockUniverseRefreshResult:
    """Summary from one stock universe refresh pass."""

    status: str
    refreshed_count: int
    skipped_count: int
    failed_count: int
    snapshots: tuple[dict[str, Any], ...]

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "refreshedCount": self.refreshed_count,
            "skippedCount": self.skipped_count,
            "failedCount": self.failed_count,
            "snapshots": list(self.snapshots),
        }


class StockUniverseSource(Protocol):
    """Fetch current preset memberships from a source adapter."""

    def fetch_preset(
        self,
        *,
        preset_name: str,
        source_url: str,
        fetched_at: datetime,
    ) -> StockUniversePresetSnapshot:
        ...


class HtmlTableStockUniverseSource:
    """Fetch stock symbols from public constituent HTML tables."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def fetch_preset(
        self,
        *,
        preset_name: str,
        source_url: str,
        fetched_at: datetime,
    ) -> StockUniversePresetSnapshot:
        with httpx.Client(
            transport=self.transport,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = client.get(source_url, headers={"User-Agent": "codex-poly-bot/stock-universe"})
            response.raise_for_status()
        symbols = symbols_from_constituent_html(response.text)
        if not symbols:
            raise ValueError(f"no symbols parsed for {preset_name}")
        return StockUniversePresetSnapshot(
            preset_name=preset_name,
            symbols=tuple(symbols),
            source="html_table",
            source_url=source_url,
            status="refreshed",
            effective_at=fetched_at,
            refreshed_at=fetched_at,
            message=f"Refreshed {len(symbols)} symbols from HTML constituent table.",
        )


class StaticStockUniverseSource:
    """Deterministic source for tests and local fallback."""

    def __init__(self, snapshots: dict[str, list[str] | tuple[str, ...]]) -> None:
        self.snapshots = {
            normalize_preset_name(name): tuple(normalize_symbol_list(symbols))
            for name, symbols in snapshots.items()
        }

    def fetch_preset(
        self,
        *,
        preset_name: str,
        source_url: str,
        fetched_at: datetime,
    ) -> StockUniversePresetSnapshot:
        symbols = self.snapshots.get(normalize_preset_name(preset_name), ())
        if not symbols:
            raise ValueError(f"no static snapshot for {preset_name}")
        return StockUniversePresetSnapshot(
            preset_name=normalize_preset_name(preset_name),
            symbols=symbols,
            source="static_test_source",
            source_url=source_url,
            status="refreshed",
            effective_at=fetched_at,
            refreshed_at=fetched_at,
            message=f"Loaded {len(symbols)} symbols from static source.",
        )


class StockUniverseRefreshService:
    """Refresh and persist latest stock preset memberships."""

    def __init__(
        self,
        registry: RepositoryRegistry,
        *,
        source: StockUniverseSource | None = None,
    ) -> None:
        self.registry = registry
        self.source = source or HtmlTableStockUniverseSource()

    def refresh(
        self,
        *,
        environment: Environment,
        config_payload: dict[str, Any],
        trigger: str,
        now: datetime | None = None,
        force: bool = False,
    ) -> StockUniverseRefreshResult:
        """Refresh due active presets and persist snapshot rows."""

        observed_at = now or datetime.now(UTC)
        refresh_config = stock_universe_refresh_config_from_payload(config_payload)
        if not refresh_config["enabled"]:
            return StockUniverseRefreshResult(
                status="disabled",
                refreshed_count=0,
                skipped_count=0,
                failed_count=0,
                snapshots=(),
            )
        active_presets = _active_preset_names(config_payload)
        sources = refresh_config["sources"]
        latest = self._latest_successful_snapshots(environment)
        refreshed: list[dict[str, Any]] = []
        skipped = 0
        failed = 0
        for preset_name in active_presets:
            source_url = sources.get(preset_name)
            if not source_url:
                skipped += 1
                continue
            if not force and not _refresh_due(
                latest.get(preset_name),
                cadence_hours=refresh_config["cadence_hours"],
                now=observed_at,
            ):
                skipped += 1
                continue
            try:
                snapshot = self.source.fetch_preset(
                    preset_name=preset_name,
                    source_url=source_url,
                    fetched_at=observed_at,
                )
                refreshed.append(
                    self.registry.shared().record_alpaca_symbol_preset_snapshot(
                        environment=environment,
                        preset_name=snapshot.preset_name,
                        status=snapshot.status,
                        source=snapshot.source,
                        source_url=snapshot.source_url,
                        symbols=list(snapshot.symbols),
                        effective_at=snapshot.effective_at,
                        refreshed_at=snapshot.refreshed_at,
                        message=snapshot.message,
                    )
                )
            except (httpx.HTTPError, ValueError, PersistenceUnavailableError) as exc:
                failed += 1
                try:
                    self.registry.shared().record_alpaca_symbol_preset_snapshot(
                        environment=environment,
                        preset_name=preset_name,
                        status="failed",
                        source="html_table",
                        source_url=source_url,
                        symbols=[],
                        effective_at=observed_at,
                        refreshed_at=observed_at,
                        message=str(exc),
                    )
                except PersistenceUnavailableError:
                    pass
        return StockUniverseRefreshResult(
            status=_refresh_status(refreshed_count=len(refreshed), skipped_count=skipped, failed_count=failed),
            refreshed_count=len(refreshed),
            skipped_count=skipped,
            failed_count=failed,
            snapshots=tuple(_snapshot_payload(row) for row in refreshed),
        )

    def seed_missing_snapshots(
        self,
        *,
        environment: Environment,
        now: datetime | None = None,
    ) -> None:
        """Persist seed rows once so the dashboard has baseline metadata."""

        observed_at = now or datetime.now(UTC)
        latest = self._latest_successful_snapshots(environment)
        seeds = seed_alpaca_preset_snapshots()
        for preset_name, seed in seeds.items():
            if preset_name in latest:
                continue
            self.registry.shared().record_alpaca_symbol_preset_snapshot(
                environment=environment,
                preset_name=preset_name,
                status="seed",
                source="static_seed",
                source_url=seed.get("sourceUrl"),
                symbols=seed["symbols"],
                effective_at=_parse_datetime(seed.get("effectiveAt")) or observed_at,
                refreshed_at=_parse_datetime(seed.get("refreshedAt")) or observed_at,
                message=str(seed.get("message") or "Seed membership snapshot."),
            )

    def _latest_successful_snapshots(self, environment: Environment) -> dict[str, dict[str, Any]]:
        try:
            rows = self.registry.shared().alpaca_symbol_preset_snapshots(environment=environment)
        except PersistenceUnavailableError:
            return {}
        successful = [
            row
            for row in rows
            if row.get("status") in {"refreshed", "seed"} and row.get("symbols")
        ]
        latest: dict[str, dict[str, Any]] = {}
        for row in successful:
            preset_name = str(row.get("preset_name"))
            current = latest.get(preset_name)
            if current is None or row.get("refreshed_at") > current.get("refreshed_at"):
                latest[preset_name] = row
        return latest


def stock_universe_refresh_config_from_payload(config_payload: dict[str, Any]) -> dict[str, Any]:
    alpaca = config_payload.get("alpaca") if isinstance(config_payload.get("alpaca"), dict) else {}
    configured = alpaca.get("preset_refresh") if isinstance(alpaca.get("preset_refresh"), dict) else {}
    source_urls = configured.get("sources") if isinstance(configured.get("sources"), dict) else {}
    sources = {
        **DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["sources"],
        **{
            normalize_preset_name(name): str(url)
            for name, url in source_urls.items()
            if normalize_preset_name(name) and str(url).strip()
        },
    }
    return {
        "enabled": bool(configured.get("enabled", DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["enabled"])),
        "cadence_hours": _positive_int(
            configured.get("cadence_hours"),
            DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["cadence_hours"],
        ),
        "stale_after_hours": _positive_int(
            configured.get("stale_after_hours"),
            DEFAULT_ALPACA_PRESET_REFRESH_CONFIG["stale_after_hours"],
        ),
        "sources": sources,
    }


def latest_preset_snapshot_payloads(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the latest successful snapshot payload by preset name."""

    latest_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("status") not in {"refreshed", "seed"} or not row.get("symbols"):
            continue
        preset_name = normalize_preset_name(row.get("preset_name"))
        current = latest_rows.get(preset_name)
        if current is None or row.get("refreshed_at") > current.get("refreshed_at"):
            latest_rows[preset_name] = row
    return {
        preset_name: _snapshot_payload(row)
        for preset_name, row in latest_rows.items()
    }


def symbols_from_constituent_html(html: str) -> list[str]:
    """Extract stock symbols from a constituent table."""

    parser = _HtmlTableParser()
    parser.feed(html)
    best_symbols: list[str] = []
    for table in parser.tables:
        if not table:
            continue
        header = [_normalize_header(cell) for cell in table[0]]
        ticker_index = _ticker_column_index(header)
        if ticker_index is None:
            continue
        symbols = normalize_symbol_list(
            row[ticker_index]
            for row in table[1:]
            if len(row) > ticker_index and _looks_like_symbol(row[ticker_index])
        )
        if len(symbols) > len(best_symbols):
            best_symbols = symbols
    return best_symbols


def _active_preset_names(config_payload: dict[str, Any]) -> list[str]:
    alpaca = config_payload.get("alpaca") if isinstance(config_payload.get("alpaca"), dict) else {}
    if "symbol_presets" not in alpaca and alpaca.get("symbol_universe"):
        return []
    raw_presets = alpaca.get("symbol_presets") or DEFAULT_ALPACA_SYMBOL_PRESETS
    return [
        preset
        for preset in (normalize_preset_name(raw) for raw in raw_presets)
        if preset
    ]


def _refresh_due(row: dict[str, Any] | None, *, cadence_hours: int, now: datetime) -> bool:
    if row is None:
        return True
    refreshed_at = row.get("refreshed_at")
    if not isinstance(refreshed_at, datetime):
        return True
    return now - refreshed_at >= timedelta(hours=cadence_hours)


def _refresh_status(*, refreshed_count: int, skipped_count: int, failed_count: int) -> str:
    if failed_count and refreshed_count:
        return "partial"
    if failed_count:
        return "failed"
    if refreshed_count:
        return "refreshed"
    if skipped_count:
        return "fresh"
    return "empty"


def _snapshot_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "presetName": row.get("preset_name"),
        "status": row.get("status"),
        "source": row.get("source"),
        "sourceUrl": row.get("source_url"),
        "symbols": list(row.get("symbols") or []),
        "symbolCount": int(row.get("symbol_count") or len(row.get("symbols") or [])),
        "effectiveAt": _isoformat(row.get("effective_at")),
        "refreshedAt": _isoformat(row.get("refreshed_at")),
        "message": row.get("message"),
    }


def _positive_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _parse_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _isoformat(raw: Any) -> str | None:
    parsed = _parse_datetime(raw)
    return parsed.isoformat() if parsed is not None else None


def _normalize_header(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _ticker_column_index(headers: list[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in {"symbol", "ticker", "ticker symbol"}:
            return index
    for index, header in enumerate(headers):
        if "ticker" in header or "symbol" in header:
            return index
    return None


def _looks_like_symbol(value: str) -> bool:
    symbol = value.strip().upper().replace(".", "-")
    if not symbol or len(symbol) > 12:
        return False
    return all(character.isalnum() or character == "-" for character in symbol)


class _HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._current_table = []
            return
        if self._current_table is None:
            return
        if tag == "tr":
            self._current_row = []
            return
        if tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(" ".join("".join(self._current_cell).split()))
            self._current_cell = None
            return
        if tag == "tr" and self._current_row is not None and self._current_table is not None:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = None
            return
        if tag == "table" and self._current_table is not None:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)
