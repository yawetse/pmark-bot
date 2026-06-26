"use client";

import { useState } from "react";

import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-004, REQ-OBS-005

export type ManualRunMode = "data_import" | "scanner_only" | "full_dry_run" | "full_live_gated";

export type ManualRunResult = {
  environment: string;
  runId: string;
  status: "accepted";
  requestedMode: ManualRunMode;
  triggeredBy: string;
  triggeredAt: string;
  auditEventId: string;
  message: string;
  marketDataPull: MarketDataPullView;
  marketDataPulls?: MarketDataPullView[];
  scannerRun?: {
    id?: string | null;
    status?: string;
    acceptedCount?: number;
    rejectedCount?: number;
    candidateCount?: number;
    candidates?: unknown[];
  };
  reasoningRun?: {
    id?: string | null;
    status?: string;
    promptCount?: number;
    scoredCount?: number;
    skippedCount?: number;
    failedCount?: number;
    outputs?: unknown[];
  };
  strategyRun?: {
    id?: string | null;
    status?: string;
    voteCount?: number;
    approvedCount?: number;
    refusedCount?: number;
    votes?: unknown[];
    outputs?: unknown[];
  };
  executionRun?: {
    id?: string | null;
    status?: string;
    intentCount?: number;
    submittedCount?: number;
    simulatedCount?: number;
    refusedCount?: number;
    intents?: unknown[];
  };
  exitRun?: {
    id?: string | null;
    status?: string;
    openPositionCount?: number;
    triggeredCount?: number;
    submittedCount?: number;
    simulatedCount?: number;
    refusedCount?: number;
    intents?: unknown[];
  };
  pipelineRun?: PipelineRunView;
};

export type PipelineStepView = {
  id: string;
  key: string;
  order: number;
  label: string;
  status: string;
  startedAt?: string | null;
  completedAt?: string | null;
  message?: string | null;
  metrics?: Record<string, unknown>;
  recordIds?: string[];
};

export type PipelineRunView = {
  id: string;
  environment: string;
  trigger: string;
  status: string;
  startedAt?: string | null;
  completedAt?: string | null;
  metadata?: Record<string, unknown>;
  steps: PipelineStepView[];
};

type RunState =
  | { status: "idle" }
  | { status: "submitting"; mode: ManualRunMode }
  | { status: "accepted"; message: string; runId: string; mode: ManualRunMode }
  | { status: "error"; message: string };

const RUN_MODES: { mode: ManualRunMode; label: string; title: string }[] = [
  { mode: "data_import", label: "Data import", title: "Fetch provider market data only" },
  { mode: "scanner_only", label: "Scanner only", title: "Fetch data and run scanner filters" },
  { mode: "full_dry_run", label: "Full dry run", title: "Run all five steps with live orders disabled" },
  { mode: "full_live_gated", label: "Full live-gated", title: "Run all five steps using configured live gates" },
];

export function ManualRunControl({
  environment,
  onAccepted,
}: {
  environment: string;
  onAccepted?: (result: ManualRunResult) => void;
}) {
  const [runState, setRunState] = useState<RunState>({ status: "idle" });

  async function triggerManualRun(mode: ManualRunMode) {
    setRunState({ status: "submitting", mode });
    const result = await dashboardApi<ManualRunResult>("operations/manual-run", {
      method: "POST",
      body: JSON.stringify({ environment, mode }),
    });
    if (!result.ok) {
      setRunState({ status: "error", message: result.message });
      return;
    }
    onAccepted?.(result.data);
    setRunState({
      status: "accepted",
      message: result.data.message,
      runId: result.data.runId,
      mode: result.data.requestedMode,
    });
  }

  return (
    <section className="operator-panel" aria-labelledby="manual-run-title">
      <div>
        <p className="section-label">Manual run</p>
        <h2 id="manual-run-title">Trigger process</h2>
      </div>
      <p className="panel-note">
        Manual requests are audited and still use the configured trading gates.
      </p>
      <div className="manual-run-actions" role="group" aria-label="Manual run modes">
        {RUN_MODES.map((item) => (
          <button
            className={`button ${item.mode === "full_live_gated" ? "primary" : ""}`}
            disabled={runState.status === "submitting"}
            key={item.mode}
            title={item.title}
            type="button"
            onClick={() => triggerManualRun(item.mode)}
          >
            {runState.status === "submitting" && runState.mode === item.mode
              ? "Triggering"
              : item.label}
          </button>
        ))}
      </div>
      {runState.status === "accepted" ? (
        <p className="status-message">
          {runState.message} Mode: {runState.mode.replaceAll("_", " ")}. Run ID: {runState.runId}
        </p>
      ) : null}
      {runState.status === "error" ? <p className="status-message">{runState.message}</p> : null}
    </section>
  );
}
