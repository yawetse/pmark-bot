import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// REQ: REQ-UI-008, REQ-UI-010, REQ-UI-011, REQ-CMP-002, REQ-CMP-003,
// REQ-CMP-004, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const modelSummary = read("components/dashboard/model-summary.tsx");
for (const token of [
  "DashboardDataGrid",
  "positions",
  "decisions",
  "orders",
  "used_usd",
  "limit_usd",
  "pnl",
  "claude",
  "openai",
  "No simulated or live orders",
]) {
  assert.match(modelSummary, new RegExp(token));
}

const comparisonView = read("components/dashboard/comparison-view.tsx");
for (const token of ["No comparison metrics yet", "P&L", "win rate", "drawdown", "Unavailable"]) {
  assert.match(comparisonView, new RegExp(token));
}
assert.doesNotMatch(comparisonView, /value: "0"/);

const operationsView = read("components/dashboard/operations-view.tsx");
for (const state of ["refused", "submitted", "filled", "canceled", "failed", "unknown"]) {
  assert.match(operationsView, new RegExp(state));
}
for (const token of [
  "Pending Orders",
  "Trade and Order History",
  "ManualRunControl",
  "PipelineRunsPanel",
  "HistoricalImportPanel",
  "Run pipeline",
  "Historical import",
  "Polymarket history",
  "Gamma markets",
  "Chain fills",
  "Wallet stats",
  "No import checkpoints",
  "Data Fetch",
  "Scanner",
  "Reasoning / Brain",
  "Execution",
  "Exit",
  "pipelineRuns",
  "MarketDataPanel",
  "EconomicsPanel",
  "No pending orders",
  "No trade or order history",
  "No simulated or live order events",
  "Activate kill switch",
  "Cancel progress",
  "Degraded venue status",
  "Manual-review state",
  "useResolvedTimeZone",
]) {
  assert.match(operationsView, new RegExp(token));
}
assert.doesNotMatch(operationsView, /order-submitted/);
assert.doesNotMatch(operationsView, /FALLBACK_ORDER_EVENTS/);

const nav = read("components/dashboard/dashboard-nav.tsx");
for (const route of [
  "/dashboard/models/claude",
  "/dashboard/models/openai",
  "/dashboard/comparison",
  "/dashboard/operations",
  "/dashboard/help",
]) {
  assert.match(nav, new RegExp(route.replaceAll("/", "\\/")));
}

const marketDataPanel = read("components/dashboard/market-data-panel.tsx");
for (const token of [
  "venues",
  "venuePulls",
  "market-venue-grid",
  "market-venue-card",
  "Latest pull",
]) {
assert.match(marketDataPanel, new RegExp(token));
}
assert.match(marketDataPanel, /DashboardDataGrid/);

const economicsPanel = read("components/dashboard/economics-panel.tsx");
assert.match(economicsPanel, /DashboardDataGrid/);

const dataGrid = read("components/dashboard/data-grid.tsx");
for (const token of ["AgGridReact", "paginationPageSizeSelector", "quickFilterText"]) {
  assert.match(dataGrid, new RegExp(token));
}
for (const view of [
  operationsView,
  marketDataPanel,
  modelSummary,
  comparisonView,
  economicsPanel,
]) {
  assert.doesNotMatch(view, /<table/);
}

const helpPage = read("app/dashboard/help/page.tsx");
assert.match(helpPage, /HelpAboutView/);
assert.match(helpPage, /getDashboardSession/);

const aboutPage = read("app/dashboard/about/page.tsx");
assert.match(aboutPage, /redirect\("\/dashboard\/help"\)/);

const helpAbout = read("components/dashboard/help-about-view.tsx");
for (const token of [
  "How codex-poly-bot Works",
  "Main Components",
  "How Work Moves Through the System",
  "What Users Can Do",
  "How Information Is Stored",
  "AWS Infrastructure",
  "Where It Runs",
  "How Code Gets Deployed",
  "ECS Fargate",
  "RDS Postgres",
  "AWS Secrets Manager",
]) {
  assert.match(helpAbout, new RegExp(token));
}
