import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// TST-REQ-UI-016-01, TST-REQ-UI-017-01, TST-REQ-UI-018-01,
// TST-REQ-UI-019-01, TST-REQ-UI-020-01, TST-REQ-UI-021-01,
// TST-REQ-UI-022-01, TST-REQ-UI-023-01, TST-REQ-UI-024-01,
// TST-REQ-UI-025-01, TST-REQ-UI-026-01

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const nav = read("components/dashboard/dashboard-nav.tsx");
for (const [label, route] of [
  ["Overview", "/dashboard"],
  ["Activity", "/dashboard/activity"],
  ["Performance", "/dashboard/performance"],
  ["Settings", "/dashboard/config"],
  ["Help", "/dashboard/help"],
]) {
  assert.match(nav, new RegExp(label));
  assert.ok(nav.includes(route));
}
assert.doesNotMatch(nav, /More|nav-more/);

const overview = read("components/dashboard/overview-dashboard.tsx");
for (const token of [
  "deriveOverviewState",
  "config/current",
  "operations/summary",
  "market-data/latest",
  "operations/tick-schedule",
  "notifications/settings",
  "How things are running",
  "Recent result",
  "Explore more",
  "Confirm change",
  "Undo",
  "expected_version",
  "Performance",
  "Settings",
  "Help",
  "/dashboard/system",
]) assert.match(overview, new RegExp(token.replaceAll("?", "\\?")));
assert.doesNotMatch(overview, /state selector|setOverviewState/);

const state = read("lib/dashboard-overview-state.ts");
for (const token of ["pipelineRunId", "executionWithinPipeline", "live", "attention", "clear", "slice(0, 3)"]) {
  assert.match(state, new RegExp(token.replace(/[()]/g, "\\$&")));
}

const activity = read("components/dashboard/activity-view.tsx");
for (const token of ["Recent checks", "/dashboard/data", "/dashboard/operations"]) {
  assert.match(activity, new RegExp(token));
}

const performance = read("components/dashboard/performance-view.tsx");
for (const token of ["Equity", "Realized P&L", "Unrealized P&L", "Open positions", "Win rate", "Trades", "By market", "Confirmed fills", "/dashboard/comparison", "/dashboard/models"]) {
  assert.match(performance, new RegExp(token));
}
assert.doesNotMatch(performance, /fills\.length\.toLocaleString\(\)/);
assert.match(performance, /setPortfolioError\(undefined\)/);

const performanceModel = read("lib/dashboard-performance-view-model.ts");
assert.match(performanceModel, /overall\.filledTrades/);
assert.match(performanceModel, /venue\.filledTrades/);
assert.match(performanceModel, /Needs confirmed closed outcomes/);

const settings = read("components/dashboard/config-controls.tsx");
for (const token of ["Common settings", "reasoning.alpaca.min_confidence", "reasoning.polymarket.min_confidence", "scanner.alpaca.max_spread", "scanner.polymarket.max_spread", "live_enabled", "notifications.email_on_trade_placed", "notifications.recipients", "Advanced settings and risk controls"]) {
  assert.match(settings, new RegExp(token.replaceAll(".", "\\.")));
}
assert.match(settings, /No settings can be changed until a versioned snapshot is available/);
assert.match(settings, /configRecipientKey\(snapshot\)/);
assert.doesNotMatch(settings, /setExpectedVersion/);

assert.match(activity, /setLoadErrors\(\[\]\)/);
const activityModel = read("lib/dashboard-activity-view-model.ts");
for (const token of ["Markets scanned", "Looked promising", "Scored by models", "Strategy approved", "Orders acted on"]) {
  assert.match(activityModel, new RegExp(token));
}
assert.match(activityModel, /orderRefusedCount/);
assert.match(activityModel, /latestTradeOutcome/);
assert.doesNotMatch(activityModel, /reasoning\?\.scoredCount/);
const settingsPage = read("app/dashboard/config/page.tsx");
assert.match(settingsPage, /\/dashboard\/operations/);
assert.match(settingsPage, /\/dashboard\/scenario/);

const help = read("components/dashboard/help-about-view.tsx");
for (const token of ["Understand every decision", "Five stages, with the details behind each one", "MethodExplorer"]) {
  assert.match(help, new RegExp(token));
}
const productMethod = read("components/product-story/method-explorer.tsx");
for (const step of ["Find repeatable behavior", "Remove weak candidates", "Build the probability case", "Form a trade decision", "Size, submit, and monitor"]) {
  assert.match(productMethod, new RegExp(step));
}
assert.match(help, /Back to Overview/);

const css = read("app/globals.css");
for (const token of ["repeat(5, minmax(0, 1fr))", "max-width: 1100px", "@media (max-width: 460px)", "prefers-reduced-motion"]) assert.ok(css.includes(token));

for (const [owner, route] of [
  [activity, "/dashboard/operations"],
  [activity, "/dashboard/data"],
  [performance, "/dashboard/comparison"],
  [performance, "/dashboard/models"],
  [settingsPage, "/dashboard/scenario"],
  [overview, "/dashboard/system"],
]) assert.ok(owner.includes(route), `${route} missing from contextual owner`);
