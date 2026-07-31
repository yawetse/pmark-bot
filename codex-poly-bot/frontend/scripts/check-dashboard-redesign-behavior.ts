// @ts-nocheck

import assert from "node:assert/strict";

import {
  buildActivityFunnel,
  latestTradeOutcome,
} from "../lib/dashboard-activity-view-model.ts";
import {
  buildActivityStageDetail,
} from "../lib/dashboard-activity-detail.ts";
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

// TST-REQ-UI-020-03: each Activity count resolves to the persisted records behind it.

const drilldownOperations = structuredClone(operations);
Object.assign(drilldownOperations.pipelineRuns[0].metadata, {
  candidateCount: 717,
  scannerAcceptedCount: 9,
  reasoningScoredCount: 8,
  strategyApprovedCount: 8,
  orderIntentCount: 8,
  orderRefusedCount: 8,
  orderSubmittedCount: 0,
  orderSimulatedCount: 0,
});

const runDetail = {
  environment: "development",
  run: drilldownOperations.pipelineRuns[0],
  records: [
    {
      stepKey: "data_fetch",
      stepLabel: "Collect prices",
      recordIds: ["pull-1"],
      recordCount: 1,
      items: [
        {
          table: "shared.dashboard_market_data_pulls",
          id: "pull-1",
          record: {
            id: "pull-1",
            venue: "polymarket_us",
            candidates: Array.from({ length: 717 }, (_, index) => ({
              id: `market-${index + 1}`,
              venue: "polymarket_us",
              market: `Market ${index + 1}`,
              state: "priced",
              price: "0.50",
            })),
          },
        },
      ],
    },
    {
      stepKey: "scanner",
      stepLabel: "Find candidates",
      recordIds: ["scanner-1", "candidate-1", "candidate-2"],
      recordCount: 3,
      items: [
        ...Array.from({ length: 9 }, (_, index) => ({
          table: "shared.scanner_candidates",
          id: `candidate-${index + 1}`,
          record: {
            id: `candidate-${index + 1}`,
            venue: "polymarket_us",
            instrument_id: `market-${index + 1}`,
            display_name: `Accepted market ${index + 1}`,
            status: "accepted",
          },
        })),
        {
          table: "shared.scanner_candidates",
          id: "candidate-rejected",
          record: {
            id: "candidate-rejected",
            venue: "polymarket_us",
            instrument_id: "market-rejected",
            display_name: "Rejected market",
            status: "rejected",
            refusal_reason: "spread too wide",
          },
        },
      ],
    },
    {
      stepKey: "brain",
      stepLabel: "Score trade",
      recordIds: ["reasoning-1", "score-1", "score-2", "score-3"],
      recordCount: 4,
      items: Array.from({ length: 8 }, (_, index) => ({
        table: "shared.reasoning_outputs",
        id: `score-${index + 1}`,
        record: {
          id: `score-${index + 1}`,
          venue: "polymarket_us",
          instrument_id: `market-${index + 1}`,
          model_provider: index % 2 ? "claude" : "openai",
          status: "scored",
          directional_signal: "buy",
          signal_strength: "0.22",
          confidence: "0.71",
          estimated_probability: "0.64",
          output_thesis: `Score ${index + 1} thesis`,
        },
      })),
    },
    {
      stepKey: "execution",
      stepLabel: "Handle order",
      recordIds: ["strategy-1", "approval-1", "approval-2", "intent-1", "intent-2", "intent-3"],
      recordCount: 6,
      items: [
        ...Array.from({ length: 8 }, (_, index) => ({
          table: "shared.strategy_consensus_outputs",
          id: `approval-${index + 1}`,
          record: {
            id: `approval-${index + 1}`,
            venue: "polymarket_us",
            instrument_id: `market-${index + 1}`,
            model_provider: "openai",
            status: "approved",
            side: "buy",
          },
        })),
        ...Array.from({ length: 8 }, (_, index) => ({
          table: "shared.order_intents",
          id: `intent-${index + 1}`,
          record: {
            id: `intent-${index + 1}`,
            venue: "polymarket_us",
            instrument_id: `market-${index + 1}`,
            model_provider: "openai",
            status: "refused",
            side: "buy",
            refusal_reason: `Execution gate ${index + 1}`,
          },
        })),
      ],
    },
  ],
};

const drilldownFunnel = buildActivityFunnel(drilldownOperations);
const detailStages = new Map(drilldownFunnel.map((stage) => [stage.key, stage]));
assert.equal(buildActivityStageDetail(detailStages.get("scanned"), runDetail).rows.length, 717);
assert.equal(buildActivityStageDetail(detailStages.get("promising"), runDetail).rows.length, 9);
const scoreDetail = buildActivityStageDetail(detailStages.get("scored"), runDetail);
assert.equal(scoreDetail.rows.length, 8);
assert.equal(scoreDetail.rows[0].confidence, "0.71 (71%)");
assert.equal(scoreDetail.rows[0].probability, "0.64 (64%)");
assert.equal(buildActivityStageDetail(detailStages.get("approved"), runDetail).rows.length, 8);
const orderDetail = buildActivityStageDetail(detailStages.get("acted"), runDetail);
assert.equal(orderDetail.expectedCount, 0);
assert.equal(orderDetail.rows.length, 8);
assert.equal(orderDetail.rows[0].reason, "Execution gate 1");

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
