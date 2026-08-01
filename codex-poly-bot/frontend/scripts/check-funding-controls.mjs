import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const performancePage = read("app/dashboard/performance/page.tsx");
const performanceView = read("components/dashboard/performance-view.tsx");
const settingsPage = read("app/dashboard/config/page.tsx");
const configWorkspace = read("components/dashboard/config-workspace.tsx");
const fundingControls = read("components/dashboard/funding-controls.tsx");
const styles = read("app/globals.css");

// TST-REQ-FND-010-06, TST-REQ-FND-010-08, TST-REQ-FND-013-05,
// TST-REQ-FND-019-03, TST-REQ-FND-019-05, TST-REQ-FND-020-04

assertIncludes(performancePage, 'serverDashboardApi<FundingHistoryView>("funding"', "Performance must load funding history through the authenticated server client.");
assertIncludes(performanceView, "Trading P&L excluding deposits", "Performance must separate trading results from external cash flow.");
assertIncludes(performanceView, "Funding history", "Performance must show retained deposits and withdrawals.");
assertIncludes(performanceView, "Expected deposits", "Performance must show matched and missing occurrences.");
assertIncludes(settingsPage, "<ConfigWorkspace", "Settings must render the shared config workspace.");
assertIncludes(configWorkspace, "<FundingControls", "Settings must render recurring-funding controls.");
assertIncludes(configWorkspace, "onSnapshotChange={setSnapshot}", "Funding and trading controls must share the current config version.");
assertIncludes(fundingControls, 'path: "funding"', "Funding saves must replace one complete funding object.");
for (const label of ["Weekly", "Monthly", "Low balance", "Add schedule", "Edit", "Enable", "Disable", "Remove"]) {
  assertIncludes(fundingControls, label, `Settings must expose the ${label} schedule action.`);
}
assertIncludes(fundingControls, "observe-only", "Polymarket schedules must be labeled observe-only.");
assertIncludes(fundingControls, "Plaid is not required", "Settings must explain the venue-managed bank boundary.");
assertIncludes(fundingControls, "Direct transfers are disabled", "Settings must state the fail-closed direct default.");
assertIncludes(fundingControls, "aria-label={`Remove ${schedule.id}`}", "Funding actions must have an accessible name.");
assertIncludes(styles, "@media (max-width: 460px)", "Funding controls must have a narrow mobile layout.");
assertIncludes(styles, "@media (prefers-reduced-motion: reduce)", "Funding controls must honor reduced motion.");

console.log("Recurring funding dashboard controls are present.");

function read(relativePath) {
  return readFileSync(resolve(root, relativePath), "utf8");
}

function assertIncludes(source, expected, message) {
  if (!source.includes(expected)) {
    throw new Error(message);
  }
}
