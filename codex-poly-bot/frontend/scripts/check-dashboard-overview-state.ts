// @ts-nocheck

import assert from "node:assert/strict";

import { deriveOverviewState, latestTickLiveOrder } from "../lib/dashboard-overview-state.ts";

// TST-REQ-UI-017-02: live state must match the latest completed pipeline run.

const baseOperations = {
  killSwitch: "inactive",
  openOrders: 0,
  cancelProgress: "0 / 0",
  manualReview: "none",
  degradedVenueStatus: "none",
  manualReviewState: "clear",
  orderEvents: [],
  pipelineRuns: [
    {
      id: "latest-run",
      environment: "local",
      trigger: "scheduled",
      status: "completed",
      startedAt: "2026-07-21T12:00:00Z",
      completedAt: "2026-07-21T12:00:10Z",
      steps: [],
    },
  ],
  scanner: { status: "completed", message: "done", latestRun: null, candidateCount: 2, acceptedCount: 2, rejectedCount: 0, candidates: [] },
  reasoning: { status: "completed", message: "done", latestRun: null, promptCount: 2, scoredCount: 2, skippedCount: 0, failedCount: 0, outputs: [] },
  strategyConsensus: { status: "completed", message: "done", latestRun: null, voteCount: 2, approvedCount: 2, refusedCount: 0, votes: [], outputs: [] },
  execution: {
    status: "completed",
    message: "done",
    intentCount: 1,
    submittedCount: 1,
    simulatedCount: 0,
    refusedCount: 0,
    intents: [{ id: "intent", pipelineRunId: "older-run", executionRunId: "execution", consensusOutputId: null, venue: "alpaca", instrumentId: "SPY", modelProvider: "openai", side: "buy", orderType: "market", status: "submitted", notionalUsd: "25", sizeMultiplier: null, idempotencyKey: null, refusalReason: null, venueOrderId: "order", createdAt: "2026-07-21T11:00:00Z", updatedAt: "2026-07-21T11:00:01Z" }],
    latestRun: { id: "execution", environment: "local", pipelineRunId: "older-run", strategyConsensusRunId: null, trigger: "scheduled", status: "completed", intentCount: 1, submittedCount: 1, simulatedCount: 0, refusedCount: 0, startedAt: "2026-07-21T11:00:00Z", completedAt: "2026-07-21T11:00:01Z", intents: [{ id: "intent", pipelineRunId: "older-run", executionRunId: "execution", consensusOutputId: null, venue: "alpaca", instrumentId: "SPY", modelProvider: "openai", side: "buy", orderType: "market", status: "submitted", notionalUsd: "25", sizeMultiplier: null, idempotencyKey: null, refusalReason: null, venueOrderId: "order", createdAt: "2026-07-21T11:00:00Z", updatedAt: "2026-07-21T11:00:01Z" }] },
  },
  exit: { status: "idle", message: "none", latestRun: null, openPositionCount: 0, triggeredCount: 0, submittedCount: 0, simulatedCount: 0, refusedCount: 0, intents: [] },
  historicalImport: undefined,
  brokerHistory: undefined,
};

assert.equal(latestTickLiveOrder(baseOperations).matched, false);

const matchingOperations = structuredClone(baseOperations);
matchingOperations.execution.latestRun.pipelineRunId = "latest-run";
matchingOperations.execution.latestRun.intents[0].pipelineRunId = "latest-run";
assert.equal(latestTickLiveOrder(matchingOperations).matched, true);
assert.equal(deriveOverviewState({ operations: matchingOperations, marketData: null, activeVenueLabels: ["Alpaca"], configReady: true, notificationsReady: true, criticalErrors: [] }).kind, "live");

const inProgressOperations = structuredClone(matchingOperations);
inProgressOperations.pipelineRuns[0].status = "running";
inProgressOperations.pipelineRuns[0].completedAt = null;
assert.equal(latestTickLiveOrder(inProgressOperations).matched, false);

const blockedOperations = structuredClone(baseOperations);
blockedOperations.execution.submittedCount = 0;
blockedOperations.execution.intentCount = 0;
blockedOperations.execution.intents = [];
blockedOperations.execution.latestRun.submittedCount = 0;
blockedOperations.execution.latestRun.intentCount = 0;
blockedOperations.execution.latestRun.intents = [];
blockedOperations.scanner.acceptedCount = 0;
blockedOperations.scanner.rejectedCount = 2;
const attention = deriveOverviewState({ operations: blockedOperations, marketData: null, activeVenueLabels: ["Alpaca"], configReady: true, notificationsReady: true, criticalErrors: [] });
assert.equal(attention.kind, "attention");
assert.equal(attention.kind === "attention" && attention.blockers[0]?.stage, "scanner");
assert.equal(attention.kind === "attention" && attention.blockers[0]?.recommendationPath, undefined);

const clearOperations = structuredClone(blockedOperations);
clearOperations.scanner.candidateCount = 0;
clearOperations.scanner.rejectedCount = 0;
clearOperations.reasoning.promptCount = 0;
clearOperations.strategyConsensus.voteCount = 0;
assert.equal(deriveOverviewState({ operations: clearOperations, marketData: null, activeVenueLabels: ["Alpaca"], configReady: true, notificationsReady: true, criticalErrors: [] }).kind, "clear");

const unknownSetup = deriveOverviewState({ operations: clearOperations, marketData: null, activeVenueLabels: [], configReady: false, notificationsReady: null, criticalErrors: ["Config unavailable"] });
assert.equal(unknownSetup.kind, "attention");
assert.equal(unknownSetup.kind === "attention" && unknownSetup.blockers.some((blocker) => blocker.key === "venues"), false);
assert.equal(unknownSetup.kind === "attention" && unknownSetup.blockers.some((blocker) => blocker.key === "notifications"), false);
