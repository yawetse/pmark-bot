// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-ALP-014, REQ-NOT-006,
// REQ-STR-009, REQ-LLM-006, REQ-EXE-007

export const ALLOWED_CONFIG_PATHS = [
  "default_selected_venue",
  "live_enabled",
  "venues.polymarket_us.enabled",
  "venues.polymarket_international.enabled",
  "venues.alpaca.enabled",
  "trading_loop_interval_seconds",
  "strategies.arbitrage.enabled",
  "strategies.convergence.enabled",
  "strategies.whale_copy.enabled",
  "llm.openai.budget_usd",
  "llm.claude.budget_usd",
  "risk.polymarket.max_position_usd",
  "risk.polymarket.max_daily_loss_usd",
  "risk.polymarket.max_open_positions",
  "risk.polymarket.market_order_slippage_threshold",
  "risk.alpaca.max_position_usd",
  "risk.alpaca.max_daily_loss_usd",
  "risk.alpaca.max_open_positions",
  "risk.alpaca.max_portfolio_allocation_per_symbol",
  "risk.alpaca.market_order_slippage_threshold",
  "alpaca.account_mode",
  "alpaca.symbol_presets",
  "alpaca.custom_symbols",
  "alpaca.custom_presets",
  "alpaca.symbol_universe",
  "notifications.recipients",
  "notifications.thresholds.daily_loss_usd",
  "notifications.thresholds.model_spend_usd",
  "notifications.thresholds.venue_degradation_minutes",
  "notifications.cooldown_seconds",
  "notifications.digest_schedule_utc",
] as const;

export type AllowedConfigPath = (typeof ALLOWED_CONFIG_PATHS)[number];

export function isAllowedConfigPath(path: string): path is AllowedConfigPath {
  return ALLOWED_CONFIG_PATHS.includes(path as AllowedConfigPath);
}

export type ConfigPathDetail = {
  label: string;
  description: string;
  valueHint: string;
  effect: string;
};

export const CONFIG_PATH_DETAILS: Record<AllowedConfigPath, ConfigPathDetail> = {
  default_selected_venue: {
    label: "Default venue",
    description: "Chooses the primary venue the bot evaluates first.",
    valueHint: "polymarket_us, polymarket_international, or alpaca",
    effect: "Applies on the next loop.",
  },
  live_enabled: {
    label: "Live trading",
    description: "Controls whether approved orders may be submitted to a live venue.",
    valueHint: "true or false",
    effect: "Keep false until dry-run evidence and operator signoff are complete.",
  },
  "venues.polymarket_us.enabled": {
    label: "Polymarket US venue",
    description: "Allows scanning, scoring, and trading for Polymarket US when other gates pass.",
    valueHint: "true or false",
    effect: "A disabled venue will not scan, score, or trade.",
  },
  "venues.polymarket_international.enabled": {
    label: "Polymarket International venue",
    description: "Allows international Polymarket activity when the environment supports it.",
    valueHint: "true or false",
    effect: "Unsupported venue settings still block live orders.",
  },
  "venues.alpaca.enabled": {
    label: "Alpaca venue",
    description: "Allows stock and ETF evaluation through Alpaca when account checks pass.",
    valueHint: "true or false",
    effect: "Alpaca remains long-only for stocks and ETFs.",
  },
  trading_loop_interval_seconds: {
    label: "Trading loop interval",
    description: "Sets how often the backend should run the trading loop.",
    valueHint: "Number of seconds, minimum 5",
    effect: "Shorter intervals can increase API and model usage.",
  },
  "strategies.arbitrage.enabled": {
    label: "Arbitrage strategy",
    description: "Enables related-market dislocation signals.",
    valueHint: "true or false",
    effect: "Signals still need consensus and risk approval.",
  },
  "strategies.convergence.enabled": {
    label: "Convergence strategy",
    description: "Enables signals where model probability diverges from market price.",
    valueHint: "true or false",
    effect: "Signals still need consensus and risk approval.",
  },
  "strategies.whale_copy.enabled": {
    label: "Whale-copy strategy",
    description: "Enables target-wallet follow signals after the configured delay.",
    valueHint: "true or false",
    effect: "The strategy needs wallet target data before it produces signals.",
  },
  "llm.openai.budget_usd": {
    label: "OpenAI budget",
    description: "Caps OpenAI model spend for scoring.",
    valueHint: "Positive dollar value, such as 20.00",
    effect: "The bot stops sending new OpenAI scoring requests after budget is exhausted.",
  },
  "llm.claude.budget_usd": {
    label: "Claude budget",
    description: "Caps Claude model spend for scoring.",
    valueHint: "Positive dollar value, such as 20.00",
    effect: "The bot stops sending new Claude scoring requests after budget is exhausted.",
  },
  "risk.polymarket.max_position_usd": {
    label: "Polymarket max position",
    description: "Maximum Polymarket exposure for one position.",
    valueHint: "Positive dollar value",
    effect: "Orders above the limit are refused.",
  },
  "risk.polymarket.max_daily_loss_usd": {
    label: "Polymarket daily loss limit",
    description: "Maximum daily loss allowed before Polymarket orders are refused.",
    valueHint: "Positive dollar value",
    effect: "The risk gate blocks new orders at or above this loss.",
  },
  "risk.polymarket.max_open_positions": {
    label: "Polymarket open positions",
    description: "Maximum number of open Polymarket positions per model provider.",
    valueHint: "Positive whole number",
    effect: "The risk gate blocks new positions above the limit.",
  },
  "risk.polymarket.market_order_slippage_threshold": {
    label: "Polymarket slippage limit",
    description: "Maximum estimated slippage allowed for Polymarket market orders.",
    valueHint: "Ratio, such as 0.02 for 2 percent",
    effect: "Market orders above the threshold are refused.",
  },
  "risk.alpaca.max_position_usd": {
    label: "Alpaca max position",
    description: "Maximum stock or ETF exposure per symbol and model provider.",
    valueHint: "Positive dollar value",
    effect: "Orders above the limit are refused.",
  },
  "risk.alpaca.max_daily_loss_usd": {
    label: "Alpaca daily loss limit",
    description: "Maximum daily loss allowed before Alpaca orders are refused.",
    valueHint: "Positive dollar value",
    effect: "The risk gate blocks new Alpaca orders at or above this loss.",
  },
  "risk.alpaca.max_open_positions": {
    label: "Alpaca open positions",
    description: "Maximum number of open stock or ETF positions per model provider.",
    valueHint: "Positive whole number",
    effect: "The risk gate blocks new positions above the limit.",
  },
  "risk.alpaca.max_portfolio_allocation_per_symbol": {
    label: "Alpaca symbol allocation",
    description: "Maximum share of model capital allocated to one Alpaca symbol.",
    valueHint: "Ratio, such as 0.10 for 10 percent",
    effect: "Orders above the allocation limit are refused.",
  },
  "risk.alpaca.market_order_slippage_threshold": {
    label: "Alpaca slippage limit",
    description: "Maximum estimated slippage allowed for Alpaca market orders.",
    valueHint: "Ratio, such as 0.005 for 0.5 percent",
    effect: "Market orders above the threshold are refused.",
  },
  "alpaca.account_mode": {
    label: "Alpaca account mode",
    description: "Selects Alpaca paper or live account mode.",
    valueHint: "paper or live",
    effect: "Live mode also requires credentials, reconciliation, and risk approval.",
  },
  "alpaca.symbol_presets": {
    label: "Alpaca stock presets",
    description: "Selects built-in or user-defined symbol groups for Alpaca scanning.",
    valueHint: "JSON array, such as [\"sp500\", \"nasdaq100\"]",
    effect: "Preset symbols are resolved on the next loop and combined with custom symbols.",
  },
  "alpaca.custom_symbols": {
    label: "Alpaca extra symbols",
    description: "Adds one-off tickers, such as a new IPO, without replacing selected presets.",
    valueHint: "JSON array, such as [\"CRCL\", \"FIG\"]",
    effect: "Symbols are added to the resolved Alpaca universe on the next loop.",
  },
  "alpaca.custom_presets": {
    label: "Alpaca custom presets",
    description: "Defines reusable operator-managed symbol groups.",
    valueHint: "JSON object, such as {\"new_ipos\":[\"CRCL\", \"FIG\"]}",
    effect: "Custom preset names can be added to Alpaca stock presets.",
  },
  "alpaca.symbol_universe": {
    label: "Alpaca resolved universe",
    description: "Resolved stock universe used by Alpaca ingestion. Prefer presets and extra symbols for edits.",
    valueHint: "JSON array of resolved symbols",
    effect: "This is retained for legacy overrides and backend visibility.",
  },
  "notifications.recipients": {
    label: "Notification recipients",
    description: "Controls who receives alerts and daily digests.",
    valueHint: "JSON object, such as {\"operator\":\"name@example.com\"}",
    effect: "Recipients must be valid email addresses.",
  },
  "notifications.thresholds.daily_loss_usd": {
    label: "Daily loss alert",
    description: "Sends an alert when daily P&L crosses the configured loss threshold.",
    valueHint: "Positive dollar value",
    effect: "Alerts still follow cooldown rules.",
  },
  "notifications.thresholds.model_spend_usd": {
    label: "Model spend alert",
    description: "Sends an alert when model spend crosses the configured threshold.",
    valueHint: "Positive dollar value",
    effect: "Alerts still follow cooldown rules.",
  },
  "notifications.thresholds.venue_degradation_minutes": {
    label: "Venue degradation alert",
    description: "Sends an alert when a venue remains degraded for the configured period.",
    valueHint: "Positive number of minutes",
    effect: "Alerts still follow cooldown rules.",
  },
  "notifications.cooldown_seconds": {
    label: "Alert cooldown",
    description: "Minimum time between repeated alerts for the same condition.",
    valueHint: "Positive number of seconds",
    effect: "Prevents repeated alert delivery.",
  },
  "notifications.digest_schedule_utc": {
    label: "Digest schedule",
    description: "UTC time for the daily summary email.",
    valueHint: "HH:MM, such as 13:00",
    effect: "Uses UTC, not local workstation time.",
  },
};
