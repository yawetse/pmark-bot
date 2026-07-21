// @ts-nocheck

import assert from "node:assert/strict";

import { buildActivityFunnel } from "../lib/dashboard-activity-view-model.ts";
import {
  buildPerformanceHeadline,
  buildPerformanceVenueRows,
} from "../lib/dashboard-performance-view-model.ts";

// TST-REQ-UI-020-02: the funnel uses one completed pipeline's persisted metrics.

const operations = {
  scanner: { candidateCount: 999, acceptedCount: 888 },
  reasoning: { scoredCount: 777 },
  execution: { submittedCount: 666, simulatedCount: 555 },
  pipelineRuns: [
    {
      id: "current-run",
      status: "completed",
      completedAt: "2026-07-21T12:00:10Z",
      steps: [
        { key: "data_fetch", metrics: { candidateCount: 12 } },
        { key: "scanner", metrics: { acceptedCount: 4 } },
        { key: "brain", metrics: { scoredCount: 3 } },
        { key: "execution", metrics: { submittedCount: 1, simulatedCount: 2 } },
      ],
    },
  ],
};

const funnel = buildActivityFunnel(operations);
assert.deepEqual(funnel.map((stage) => stage.value), [12, 4, null, 3]);
assert.equal(funnel[2].statusLabel, "Unavailable");
assert.match(funnel[2].detail, /does not expose/);

const missingScanner = structuredClone(operations);
missingScanner.pipelineRuns[0].steps = missingScanner.pipelineRuns[0].steps.filter(
  (step) => step.key !== "scanner",
);
assert.equal(buildActivityFunnel(missingScanner)[1].value, null);

const explicitConfidence = structuredClone(operations);
explicitConfidence.pipelineRuns[0].steps.find((step) => step.key === "brain").metrics.confidencePassedCount = 2;
assert.equal(buildActivityFunnel(explicitConfidence)[2].value, 2);

// TST-REQ-UI-021-02: trade totals come only from venue-confirmed portfolio fills.

const portfolio = {
  overall: { filledTrades: 7 },
  venues: [
    {
      venue: "alpaca",
      label: "Alpaca",
      accounts: [{ accountRef: "paper" }],
      filledTrades: 5,
      totalPnlUsd: "12.50",
    },
    {
      venue: "polymarket_us",
      label: "Polymarket US",
      accounts: [],
      filledTrades: 2,
      totalPnlUsd: null,
    },
  ],
};

assert.deepEqual(buildPerformanceHeadline(portfolio), {
  tradeCount: 7,
  winRate: null,
  winRateDetail: "Needs confirmed closed outcomes",
});
assert.deepEqual(
  buildPerformanceVenueRows(portfolio).map((row) => [row.market, row.trades, row.winRate]),
  [["Alpaca", 5, null], ["Polymarket US", 2, null]],
);
assert.equal(buildPerformanceHeadline(undefined).tradeCount, null);
