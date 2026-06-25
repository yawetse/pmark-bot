"""Spec tests for refreshable Alpaca stock universe presets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db import RepositoryRegistry
from app.domain import Environment
from app.services import ConfigService, default_config_payload
from app.services.stock_universe import resolve_alpaca_symbol_universe
from app.services.stock_universe_refresh_service import (
    StaticStockUniverseSource,
    StockUniverseRefreshService,
    latest_preset_snapshot_payloads,
    symbols_from_constituent_html,
)


def test_req_alp_015_01_constituent_html_parser_extracts_symbols() -> None:
    """TST-REQ-ALP-015-01: Validates REQ-ALP-015

    Given: a source page with a ticker-symbol table
    When: the parser extracts constituents
    Then: symbols are normalized for Alpaca.
    """

    html = """
    <table>
      <tr><th>Company</th><th>Ticker symbol</th></tr>
      <tr><td>Example A</td><td>AAA</td></tr>
      <tr><td>Class B</td><td>BRK.B</td></tr>
    </table>
    """

    assert symbols_from_constituent_html(html) == ["AAA", "BRK-B"]


def test_req_alp_015_02_scheduled_refresh_persists_membership_snapshot() -> None:
    """TST-REQ-ALP-015-02: Validates REQ-ALP-015 and REQ-DB-003

    Given: a refreshable source for a built-in stock preset
    When: the stock universe refresh service runs
    Then: the latest membership snapshot is persisted with counts and source metadata.
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    result = StockUniverseRefreshService(
        registry,
        source=StaticStockUniverseSource({"sp500": ["AAPL", "MSFT", "IPOX"]}),
    ).refresh(
        environment=Environment.DEVELOPMENT,
        config_payload={
            "alpaca": {
                "symbol_presets": ["sp500"],
                "preset_refresh": {
                    "enabled": True,
                    "cadence_hours": 24,
                    "sources": {"sp500": "https://example.test/sp500"},
                },
            }
        },
        trigger="scheduled",
        now=now,
        force=True,
    )

    rows = registry.shared().alpaca_symbol_preset_snapshots(environment=Environment.DEVELOPMENT)
    latest = latest_preset_snapshot_payloads(rows)

    assert result.status == "refreshed"
    assert result.refreshed_count == 1
    assert rows[0]["preset_name"] == "sp500"
    assert rows[0]["symbol_count"] == 3
    assert latest["sp500"]["symbols"] == ["AAPL", "MSFT", "IPOX"]


def test_req_alp_015_03_config_uses_refreshed_presets_with_additive_custom_symbols() -> None:
    """TST-REQ-ALP-015-03: Validates REQ-ALP-014 and REQ-ALP-015

    Given: a refreshed S&P 500 snapshot and a custom IPO symbol
    When: config is loaded for the next loop
    Then: the resolved universe uses refreshed preset members and keeps the custom symbol additive.
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    payload = default_config_payload()
    payload["alpaca"]["symbol_presets"] = ["sp500"]
    payload["alpaca"]["custom_symbols"] = ["CRCL"]
    payload["alpaca"]["custom_presets"] = {}
    payload["alpaca"]["symbol_universe"] = resolve_alpaca_symbol_universe(payload)
    registry.shared().record_config_version(
        environment=Environment.DEVELOPMENT,
        version="v1",
        payload=payload,
    )
    StockUniverseRefreshService(
        registry,
        source=StaticStockUniverseSource({"sp500": ["AAPL", "MSFT", "IPOX"]}),
    ).refresh(
        environment=Environment.DEVELOPMENT,
        config_payload=payload,
        trigger="scheduled",
        now=now,
        force=True,
    )

    snapshot = ConfigService(registry).config_for_next_loop(Environment.DEVELOPMENT).snapshot
    alpaca = snapshot.payload["alpaca"]

    assert "IPOX" in alpaca["symbol_universe"]
    assert "CRCL" in alpaca["symbol_universe"]
    assert alpaca["preset_metadata"][0]["snapshotSymbolCount"] == 3
    assert isinstance(alpaca["preset_metadata"][0]["ageHours"], int)


def test_req_alp_015_04_refresh_skips_fresh_snapshot_until_cadence_expires() -> None:
    """TST-REQ-ALP-015-04: Validates REQ-ALP-015

    Given: a successful preset snapshot refreshed recently
    When: the scheduled refresh runs before cadence expiry
    Then: no duplicate snapshot is persisted.
    """

    registry = RepositoryRegistry()
    now = datetime(2026, 6, 25, 15, 0, tzinfo=UTC)
    service = StockUniverseRefreshService(
        registry,
        source=StaticStockUniverseSource({"sp500": ["AAPL"]}),
    )
    config_payload = {
        "alpaca": {
            "symbol_presets": ["sp500"],
            "preset_refresh": {
                "enabled": True,
                "cadence_hours": 24,
                "sources": {"sp500": "https://example.test/sp500"},
            },
        }
    }
    first = service.refresh(
        environment=Environment.DEVELOPMENT,
        config_payload=config_payload,
        trigger="scheduled",
        now=now,
    )
    second = service.refresh(
        environment=Environment.DEVELOPMENT,
        config_payload=config_payload,
        trigger="scheduled",
        now=now + timedelta(hours=1),
    )

    assert first.refreshed_count == 1
    assert second.status == "fresh"
    assert len(registry.shared().alpaca_symbol_preset_snapshots(environment=Environment.DEVELOPMENT)) == 1
