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
  "venues.polymarket_us.enabled",
  "trading_loop_interval_seconds",
  "llm.openai.budget_usd",
  "risk.alpaca.max_position_usd",
  "notifications.cooldown_seconds",
]) {
  assert.match(configPaths, new RegExp(path.replaceAll(".", "\\.")));
}

const configControls = read("components/dashboard/config-controls.tsx");
assert.match(configControls, /isAllowedConfigPath/);
assert.match(configControls, /dashboardApi<ConfigUpdateResponse>\("config"/);
assert.match(configControls, /result\.status === 409/);
assert.match(configControls, /Current server version is/);
assert.doesNotMatch(configControls, /unsupported\.path/);

const walletStatus = read("components/dashboard/wallet-status.tsx");
assert.match(walletStatus, /publicIdentifier/);
assert.doesNotMatch(walletStatus, /private/i);
assert.doesNotMatch(walletStatus, /secret/i);
