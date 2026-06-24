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
