import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// REQ: REQ-UI-008, REQ-UI-010, REQ-UI-011, REQ-CMP-002, REQ-CMP-003,
// REQ-CMP-004, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const modelSummary = read("components/dashboard/model-summary.tsx");
for (const token of ["positions", "decisions", "budgetUsd", "pnlUsd", "claude", "openai"]) {
  assert.match(modelSummary, new RegExp(token));
}

const comparisonView = read("components/dashboard/comparison-view.tsx");
for (const token of ["Claude / Polymarket US", "OpenAI / Alpaca", "Unavailable", "caveat"]) {
  assert.match(comparisonView, new RegExp(token));
}
assert.doesNotMatch(comparisonView, /value: "0"/);

const operationsView = read("components/dashboard/operations-view.tsx");
for (const state of ["refused", "submitted", "filled", "canceled", "failed", "unknown"]) {
  assert.match(operationsView, new RegExp(state));
}
for (const token of ["Cancel progress", "Degraded venue status", "Manual-review state"]) {
  assert.match(operationsView, new RegExp(token));
}

const nav = read("components/dashboard/dashboard-nav.tsx");
for (const route of [
  "/dashboard/models/claude",
  "/dashboard/models/openai",
  "/dashboard/comparison",
  "/dashboard/operations",
]) {
  assert.match(nav, new RegExp(route.replaceAll("/", "\\/")));
}
