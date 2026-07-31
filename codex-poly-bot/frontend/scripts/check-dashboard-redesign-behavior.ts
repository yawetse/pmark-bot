// @ts-nocheck

import assert from "node:assert/strict";

import {
  buildActivityFunnel,
  latestTradeOutcome,
} from "../lib/dashboard-activity-view-model.ts";
import {
  buildPerformanceAccountBalances,
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
      metadata: {
        candidateCount: 12,
        scannerAcceptedCount: 4,
        reasoningScoredCount: 3,
        strategyApprovedCount: 2,
        orderIntentCount: 3,
        orderRefusedCount: 0,
        orderSubmittedCount: 1,
        orderSimulatedCount: 2,
      },
      steps: [],
    },
  ],
};

const funnel = buildActivityFunnel(operations);
assert.deepEqual(funnel.map((stage) => stage.value), [12, 4, 3, 2, 3]);
assert.equal(funnel[4].statusLabel, "Passed");
assert.match(funnel[4].detail, /3 planned, 0 refused, 2 simulated, 1 submitted/);
assert.match(latestTradeOutcome(operations), /1 live order was submitted/);

const missingScanner = structuredClone(operations);
delete missingScanner.pipelineRuns[0].metadata.scannerAcceptedCount;
assert.equal(buildActivityFunnel(missingScanner)[1].value, null);

const refusedOrders = structuredClone(operations);
Object.assign(refusedOrders.pipelineRuns[0].metadata, {
  orderSubmittedCount: 0,
  orderSimulatedCount: 0,
  orderRefusedCount: 3,
});
assert.match(latestTradeOutcome(refusedOrders), /3 order intents were refused/);

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

// TST-REQ-UI-013-06: account balances prefer buying power and fall back to cash.

const accountBalances = buildPerformanceAccountBalances({
  accounts: [
    {
      venue: "alpaca",
      accountRef: "alpaca-live",
      accountMode: "live",
      providers: ["openai"],
      accountValueUsd: "120.00",
      cashUsd: "75.00",
      buyingPowerUsd: "100.00",
      status: "ready",
      lastUpdatedAt: "2026-07-31T12:00:00Z",
    },
    {
      venue: "polymarket_us",
      accountRef: "polymarket-live",
      accountMode: "live",
      providers: ["openai", "claude"],
      accountValueUsd: "80.00",
      cashUsd: "45.00",
      buyingPowerUsd: null,
      status: "stale",
      lastUpdatedAt: "2026-07-31T11:55:00Z",
    },
    {
      venue: "alpaca",
      accountRef: "alpaca-paper",
      accountMode: "paper",
      providers: ["claude"],
      accountValueUsd: null,
      cashUsd: null,
      buyingPowerUsd: null,
      status: "unavailable",
      lastUpdatedAt: null,
    },
  ],
});

assert.deepEqual(
  accountBalances.map((account) => [
    account.availableToTradeUsd,
    account.availableToTradeSource,
    account.status,
  ]),
  [
    ["100.00", "Buying power", "ready"],
    ["45.00", "Cash balance", "stale"],
    [null, null, "unavailable"],
  ],
);
