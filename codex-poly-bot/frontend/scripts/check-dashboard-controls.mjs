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
  "alpaca.symbol_presets",
  "alpaca.custom_symbols",
  "alpaca.custom_presets",
  "notifications.recipients",
  "notifications.cooldown_seconds",
  "notifications.email_on_trade_placed",
]) {
  assert.match(configPaths, new RegExp(path.replaceAll(".", "\\.")));
}
for (const token of [
  "CONFIG_PATH_DETAILS",
  "Default venue",
  "Live trading",
]) {
  assert.match(configPaths, new RegExp(token));
}

const configControls = read("components/dashboard/config-controls.tsx");
assert.match(configControls, /isAllowedConfigPath/);
assert.match(configControls, /dashboardApi<ConfigUpdateResponse>\("config"/);
assert.match(configControls, /method: "POST"/);
assert.match(configControls, /JSON\.parse/);
assert.match(configControls, /Alpaca stock universe/);
assert.match(configControls, /Save stock universe/);
assert.match(configControls, /Resolved symbols/);
assert.match(configControls, /parseCustomPresets/);
assert.match(configControls, /parseSymbols/);
assert.match(configControls, /result\.status === 409/);
assert.match(configControls, /Current server version is/);
assert.match(configControls, /CONFIG_PATH_DETAILS/);
assert.match(configControls, /selectedDetail\.description/);
assert.match(configControls, /selectedDetail\.effect/);
assert.match(configControls, /Expected value/);
assert.match(configControls, /Current value/);
assert.doesNotMatch(configControls, /unsupported\.path/);

const configPage = read("app/dashboard/config/page.tsx");
assert.match(configPage, /serverDashboardApi<ConfigSnapshot>/);
assert.match(configPage, /"config\/current"/);

const walletStatus = read("components/dashboard/wallet-status.tsx");
assert.match(walletStatus, /publicIdentifier/);
assert.doesNotMatch(walletStatus, /private/i);
assert.doesNotMatch(walletStatus, /secret/i);

const dashboardPage = read("app/dashboard/page.tsx");
assert.match(dashboardPage, /ConsumerDashboard/);
assert.doesNotMatch(dashboardPage, /serverDashboardApi<DashboardSummaryView>/);

const dashboardLayout = read("app/dashboard/layout.tsx");
for (const token of [
  "DashboardNav",
  "getDashboardSession",
  "page-shell",
  "dashboard-main",
]) {
  assert.match(dashboardLayout, new RegExp(token));
}

const dashboardLoadingPage = read("app/dashboard/loading.tsx");
assert.match(dashboardLoadingPage, /DashboardLoadingPanels/);

const dashboardLoading = read("components/dashboard/dashboard-loading.tsx");
for (const token of [
  "DashboardPanelLoading",
  "loading-panel",
  "aria-busy",
  "loading",
]) {
  assert.match(dashboardLoading, new RegExp(token));
}

const dashboardNav = read("components/dashboard/dashboard-nav.tsx");
assert.match(dashboardNav, /ThemePreferenceControl/);

const themeControl = read("components/dashboard/theme-preference-control.tsx");
for (const token of [
  "System",
  "Light",
  "Dark",
  "dashboardApi<UserPreferencesView>",
  "applyDashboardTheme",
  "aria-pressed",
]) {
  assert.match(themeControl, new RegExp(token));
}

const commandCenter = read("components/dashboard/operator-command-center.tsx");
for (const token of [
  "What is running",
  "LoopMonitor",
  "PreferencesPanel",
  "ManualRunControl",
  "MarketDataPanel",
  "EconomicsPanel",
  "What happens next",
  "Pending activity",
  "Available controls",
  "No orders recorded",
]) {
  assert.match(commandCenter, new RegExp(token));
}

const consumerDashboard = read("components/dashboard/consumer-dashboard.tsx");
for (const token of [
  "config/current",
  "operations/summary",
  "economics/summary",
  "market-data/latest",
  "notifications/settings",
  "operations/tick-summary",
  "P&L over time",
  "Five steps",
  "Daily summary",
  "Run summary now",
  "Conservative",
  "Balanced",
  "Aggressive",
  "notifications.email_on_trade_placed",
  "Reset defaults",
  "currentValue",
  "nextValue",
  "refreshConfigSnapshot",
  "result.status === 409",
  'method: "POST"',
  "finalizeConfigSave",
]) {
  assert.match(consumerDashboard, new RegExp(token.replaceAll("?", "\\?")));
}

const manualRunControl = read("components/dashboard/manual-run-control.tsx");
for (const token of [
  "data_import",
  "scanner_only",
  "full_dry_run",
  "full_live_gated",
  "ManualRunMode",
]) {
  assert.match(manualRunControl, new RegExp(token));
}

const dataGrid = read("components/dashboard/data-grid.tsx");
for (const token of [
  "AgGridReact",
  "AllCommunityModule",
  "pagination",
  "quickFilterText",
  "sortable",
  "filter",
]) {
  assert.match(dataGrid, new RegExp(token));
}

const loopMonitor = read("components/dashboard/loop-monitor.tsx");
for (const token of [
  "Loop monitor",
  "Next run",
  "Data in use",
  "Prompts",
  "Decision logic",
  "Calculations",
  "Pre-trade gates",
  "loop.prompts",
]) {
  assert.match(loopMonitor, new RegExp(token));
}
