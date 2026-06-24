import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// REQ: REQ-UI-004, REQ-UI-005, REQ-UI-007, REQ-UI-009, REQ-OBS-005

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const statusOverview = read("components/dashboard/status-overview.tsx");
for (const section of [
  "Venue",
  "Wallet",
  "Ingestion",
  "Trading loop",
  "Notification",
  "Audit",
  "Health",
]) {
  assert.match(statusOverview, new RegExp(section));
}

const configPaths = read("lib/config-paths.ts");
for (const path of [
  "live_enabled",
  "default_selected_venue",
  "venues.polymarket_us.enabled",
  "trading_loop_interval_seconds",
  "llm.openai.budget_usd",
  "risk.alpaca.max_position_usd",
  "risk.alpaca.market_order_slippage_threshold",
  "notifications.recipients",
  "notifications.cooldown_seconds",
]) {
  assert.match(configPaths, new RegExp(path.replaceAll(".", "\\.")));
}

const configControls = read("components/dashboard/config-controls.tsx");
assert.match(configControls, /isAllowedConfigPath/);
assert.match(configControls, /dashboardApi<ConfigUpdateResponse>\("config"/);
assert.match(configControls, /JSON\.parse/);
assert.match(configControls, /result\.status === 409/);
assert.match(configControls, /Current server version is/);
assert.doesNotMatch(configControls, /unsupported\.path/);

const configPage = read("app/dashboard/config/page.tsx");
assert.match(configPage, /serverDashboardApi<ConfigSnapshot>/);
assert.match(configPage, /"config\/current"/);

const walletStatus = read("components/dashboard/wallet-status.tsx");
assert.match(walletStatus, /publicIdentifier/);
assert.doesNotMatch(walletStatus, /private/i);
assert.doesNotMatch(walletStatus, /secret/i);

const dashboardPage = read("app/dashboard/page.tsx");
assert.match(dashboardPage, /GettingStartedGuide/);

const gettingStarted = read("components/dashboard/getting-started-guide.tsx");
for (const token of [
  "Why trading has not started",
  "Polymarket wallet",
  "Alpaca account",
  "live-trading checklist",
  "Review config",
  "Open operations",
]) {
  assert.match(gettingStarted, new RegExp(token));
}
