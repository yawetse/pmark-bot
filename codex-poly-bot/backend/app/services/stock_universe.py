"""Alpaca stock universe presets and symbol resolution helpers.

REQ: REQ-DAT-008, REQ-UI-005, REQ-ALP-014, REQ-ALP-015
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable


# Constituents were captured from public S&P 500 and Nasdaq-100 tables on 2026-06-25.
SP500_SYMBOLS = (
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL",
    "GOOGL", "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG",
    "AMT", "AWK", "AMP", "AME", "AMGN", "APH", "ADI", "AON", "APA",
    "APO", "AAPL", "AMAT", "APP", "APTV", "ACGL", "ADM", "ARES", "ANET",
    "AJG", "AIZ", "T", "ATO", "ADSK", "ADP", "AZO", "AVB", "AVY",
    "AXON", "BKR", "BALL", "BAC", "BAX", "BDX", "BRK-B", "BBY", "TECH",
    "BIIB", "BLK", "BX", "XYZ", "BNY", "BA", "BKNG", "BSX", "BMY",
    "AVGO", "BR", "BRO", "BF-B", "BLDR", "BG", "BXP", "CHRW", "CDNS",
    "CPT", "COF", "CAH", "CCL", "CARR", "CVNA", "CASY", "CAT", "CBOE",
    "CBRE", "CDW", "COR", "CNC", "CNP", "CF", "CRL", "SCHW", "CHTR",
    "CVX", "CMG", "CB", "CHD", "CIEN", "CI", "CINF", "CTAS", "CSCO",
    "C", "CFG", "CLX", "CME", "CMS", "KO", "CTSH", "COHR", "COIN",
    "CL", "CMCSA", "FIX", "CAG", "COP", "ED", "STZ", "CEG", "COO",
    "CPRT", "GLW", "CPAY", "CTVA", "CSGP", "COST", "CRH", "CRWD", "CCI",
    "CSX", "CMI", "CVS", "DHR", "DRI", "DDOG", "DVA", "DECK", "DE",
    "DELL", "DAL", "DVN", "DXCM", "FANG", "DLR", "DG", "DLTR", "D",
    "DPZ", "DASH", "DOV", "DOW", "DHI", "DTE", "DUK", "DD", "ETN",
    "EBAY", "ECHO", "ECL", "EIX", "EW", "EA", "ELV", "EME", "EMR",
    "ETR", "EOG", "EQT", "EFX", "EQIX", "EQR", "ERIE", "ESS", "EL",
    "EG", "EVRG", "ES", "EXC", "EXE", "EXPE", "EXPD", "EXR", "XOM",
    "FFIV", "FDS", "FICO", "FAST", "FRT", "FDX", "FDXF", "FIS", "FITB",
    "FSLR", "FE", "FISV", "FLEX", "F", "FTNT", "FTV", "FOXA", "FOX",
    "BEN", "FCX", "GRMN", "IT", "GE", "GEHC", "GEV", "GEN", "GNRC",
    "GD", "GIS", "GM", "GPC", "GILD", "GPN", "GL", "GDDY", "GS", "HAL",
    "HIG", "HAS", "HCA", "DOC", "HSIC", "HSY", "HPE", "HLT", "HD",
    "HON", "HRL", "HST", "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII",
    "IBM", "IEX", "IDXX", "ITW", "INCY", "IR", "PODD", "INTC", "IBKR",
    "ICE", "IFF", "IP", "INTU", "ISRG", "IVZ", "INVH", "IQV", "IRM",
    "JBHT", "JBL", "JKHY", "J", "JNJ", "JCI", "JPM", "KVUE", "KDP",
    "KEY", "KEYS", "KMB", "KIM", "KMI", "KKR", "KLAC", "KHC", "KR",
    "LHX", "LH", "LRCX", "LVS", "LDOS", "LEN", "LII", "LLY", "LIN",
    "LYV", "LMT", "L", "LOW", "LULU", "LITE", "LYB", "MTB", "MPC",
    "MAR", "MRSH", "MLM", "MRVL", "MAS", "MA", "MKC", "MCD", "MCK",
    "MDT", "MRK", "META", "MET", "MTD", "MGM", "MCHP", "MU", "MSFT",
    "MAA", "MRNA", "TAP", "MDLZ", "MPWR", "MNST", "MCO", "MS", "MOS",
    "MSI", "MSCI", "NDAQ", "NTAP", "NFLX", "NEM", "NWSA", "NWS", "NEE",
    "NKE", "NI", "NDSN", "NSC", "NTRS", "NOC", "NCLH", "NRG", "NUE",
    "NVDA", "NVR", "NXPI", "ORLY", "OXY", "ODFL", "OMC", "ON", "OKE",
    "ORCL", "OTIS", "PCAR", "PKG", "PLTR", "PANW", "PSKY", "PH", "PAYX",
    "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX", "PNW", "PNC",
    "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU", "PEG", "PTC",
    "PSA", "PHM", "PWR", "QCOM", "DGX", "Q", "RL", "RJF", "RTX", "O",
    "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "HOOD", "ROK", "ROL",
    "ROP", "ROST", "RCL", "SPGI", "CRM", "SNDK", "SBAC", "SLB", "STX",
    "SRE", "NOW", "SHW", "SPG", "SWKS", "SJM", "SW", "SNA", "SOLV",
    "SO", "LUV", "SWK", "SBUX", "STT", "STLD", "STE", "SYK", "SMCI",
    "SYF", "SNPS", "SYY", "TMUS", "TROW", "TTWO", "TPR", "TRGP", "TGT",
    "TEL", "TDY", "TER", "TSLA", "TXN", "TPL", "TXT", "TMO", "TJX",
    "TKO", "TTD", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC", "TYL",
    "TSN", "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI",
    "UNH", "UHS", "VLO", "VEEV", "VTR", "VLTO", "VRSN", "VRSK", "VZ",
    "VRTX", "VRT", "VTRS", "VICI", "V", "VST", "VMC", "WRB", "GWW",
    "WAB", "WMT", "DIS", "WBD", "WM", "WAT", "WEC", "WFC", "WELL",
    "WST", "WDC", "WY", "WSM", "WMB", "WTW", "WDAY", "WYNN", "XEL",
    "XYL", "YUM", "ZBRA", "ZBH", "ZTS",
)

NASDAQ100_SYMBOLS = (
    "ADBE", "AMD", "ABNB", "ALNY", "GOOGL", "GOOG", "AMZN", "AEP", "AMGN",
    "ADI", "AAPL", "AMAT", "APP", "ARM", "ASML", "ADSK", "ADP", "AXON",
    "BKR", "BKNG", "AVGO", "CDNS", "CHTR", "CTAS", "CSCO", "CCEP", "CTSH",
    "CMCSA", "CEG", "CPRT", "COST", "CRWD", "CSX", "DDOG", "DXCM", "FANG",
    "DASH", "EA", "EXC", "FAST", "FER", "FTNT", "GEHC", "GILD", "HON",
    "IDXX", "INSM", "INTC", "INTU", "ISRG", "KDP", "KLAC", "KHC", "LRCX",
    "LIN", "LITE", "MAR", "MRVL", "MELI", "META", "MCHP", "MU", "MSFT",
    "MSTR", "MDLZ", "MPWR", "MNST", "NFLX", "NVDA", "NXPI", "ORLY", "ODFL",
    "PCAR", "PLTR", "PANW", "PAYX", "PYPL", "PDD", "PEP", "QCOM", "REGN",
    "ROP", "ROST", "SNDK", "STX", "SHOP", "SBUX", "SNPS", "TMUS", "TTWO",
    "TSLA", "TXN", "TRI", "VRSK", "VRTX", "WMT", "WBD", "WDC", "WDAY",
    "XEL", "ZS",
)

CORE_ETF_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "XLK", "XLF", "XLE")

BUILT_IN_ALPACA_PRESETS: dict[str, tuple[str, ...]] = {
    "sp500": SP500_SYMBOLS,
    "nasdaq100": NASDAQ100_SYMBOLS,
    "core_etfs": CORE_ETF_SYMBOLS,
}

DEFAULT_ALPACA_SYMBOL_PRESETS = ("sp500", "nasdaq100")
DEFAULT_ALPACA_PRESET_SOURCE_URLS: dict[str, str] = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}
DEFAULT_ALPACA_PRESET_REFRESH_CONFIG: dict[str, Any] = {
    "enabled": True,
    "cadence_hours": 24,
    "stale_after_hours": 168,
    "sources": DEFAULT_ALPACA_PRESET_SOURCE_URLS,
}
SEED_SNAPSHOT_EFFECTIVE_AT = datetime(2026, 6, 25, tzinfo=UTC)


def normalize_symbol_list(raw: Iterable[Any]) -> list[str]:
    """Return unique uppercase ticker symbols in input order."""

    symbols: list[str] = []
    seen: set[str] = set()
    for item in raw:
        symbol = str(item).strip().upper().replace(".", "-")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def normalize_preset_name(raw: Any) -> str:
    return str(raw).strip().lower().replace(" ", "_")


def seed_alpaca_preset_snapshots() -> dict[str, dict[str, Any]]:
    """Return static seed snapshots used before provider refresh runs."""

    return {
        preset_name: {
            "presetName": preset_name,
            "status": "seed",
            "source": "static_seed",
            "sourceUrl": DEFAULT_ALPACA_PRESET_SOURCE_URLS.get(preset_name),
            "symbols": list(symbols),
            "symbolCount": len(symbols),
            "effectiveAt": SEED_SNAPSHOT_EFFECTIVE_AT.isoformat(),
            "refreshedAt": SEED_SNAPSHOT_EFFECTIVE_AT.isoformat(),
            "message": "Seed membership captured on 2026-06-25.",
        }
        for preset_name, symbols in BUILT_IN_ALPACA_PRESETS.items()
    }


def resolve_alpaca_symbol_universe(config_payload: dict[str, Any]) -> list[str]:
    """Resolve built-in presets, user presets, and individual custom symbols."""

    alpaca_config = config_payload.get("alpaca", {})
    if not isinstance(alpaca_config, dict):
        return []

    if "symbol_presets" not in alpaca_config and "custom_symbols" not in alpaca_config:
        return normalize_symbol_list(alpaca_config.get("symbol_universe") or [])

    custom_presets = _custom_presets(alpaca_config.get("custom_presets"))
    preset_snapshots = _preset_snapshots(alpaca_config.get("preset_snapshots"))
    active_presets = [
        normalize_preset_name(preset)
        for preset in alpaca_config.get("symbol_presets") or ()
        if normalize_preset_name(preset)
    ]
    symbols: list[str] = []
    for preset in active_presets:
        snapshot = preset_snapshots.get(preset)
        symbols.extend(snapshot.get("symbols", ()) if snapshot else BUILT_IN_ALPACA_PRESETS.get(preset, ()))
        symbols.extend(custom_presets.get(preset, ()))
    symbols.extend(alpaca_config.get("custom_symbols") or ())
    return normalize_symbol_list(symbols)


def stock_universe_metadata(config_payload: dict[str, Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Return dashboard metadata for active stock universe presets."""

    alpaca_config = config_payload.get("alpaca", {})
    if not isinstance(alpaca_config, dict):
        return []
    observed_at = now or datetime.now(UTC)
    preset_snapshots = _preset_snapshots(alpaca_config.get("preset_snapshots"))
    custom_presets = _custom_presets(alpaca_config.get("custom_presets"))
    active_presets = [
        normalize_preset_name(preset)
        for preset in alpaca_config.get("symbol_presets") or ()
        if normalize_preset_name(preset)
    ]
    rows: list[dict[str, Any]] = []
    for preset in active_presets:
        snapshot = preset_snapshots.get(preset)
        snapshot_symbols = normalize_symbol_list(snapshot.get("symbols", ())) if snapshot else []
        custom_symbols = custom_presets.get(preset, [])
        fallback_symbols = normalize_symbol_list(BUILT_IN_ALPACA_PRESETS.get(preset, ()))
        effective_symbols = normalize_symbol_list(snapshot_symbols or fallback_symbols)
        combined_symbols = normalize_symbol_list([*effective_symbols, *custom_symbols])
        refreshed_at = _parse_datetime((snapshot or {}).get("refreshedAt"))
        age_hours = (
            int((observed_at - refreshed_at).total_seconds() // 3600)
            if refreshed_at is not None
            else None
        )
        rows.append(
            {
                "presetName": preset,
                "status": (snapshot or {}).get("status") or ("custom" if custom_symbols and not effective_symbols else "seed"),
                "source": (snapshot or {}).get("source") or ("custom_preset" if custom_symbols and not effective_symbols else "static_seed"),
                "sourceUrl": (snapshot or {}).get("sourceUrl"),
                "symbolCount": len(combined_symbols),
                "snapshotSymbolCount": len(effective_symbols),
                "customSymbolCount": len(custom_symbols),
                "effectiveAt": (snapshot or {}).get("effectiveAt"),
                "refreshedAt": (snapshot or {}).get("refreshedAt"),
                "ageHours": age_hours,
                "message": (snapshot or {}).get("message"),
            }
        )
    return rows


def _custom_presets(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    presets: dict[str, list[str]] = {}
    for name, symbols in raw.items():
        preset_name = normalize_preset_name(name)
        if not preset_name or not isinstance(symbols, list):
            continue
        presets[preset_name] = normalize_symbol_list(symbols)
    return presets


def _preset_snapshots(raw: Any) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else seed_alpaca_preset_snapshots()
    snapshots: dict[str, dict[str, Any]] = {}
    for name, snapshot in source.items():
        preset_name = normalize_preset_name(name)
        if not preset_name or not isinstance(snapshot, dict):
            continue
        symbols = normalize_symbol_list(snapshot.get("symbols") or [])
        if not symbols:
            continue
        snapshots[preset_name] = {
            **snapshot,
            "presetName": preset_name,
            "symbols": symbols,
            "symbolCount": len(symbols),
        }
    return snapshots


def _parse_datetime(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
