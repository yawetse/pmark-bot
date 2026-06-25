"use client";

import { useState } from "react";

import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-008, REQ-DAT-008, REQ-OBS-004, REQ-OBS-005

export type ManualRunResult = {
  environment: string;
  runId: string;
  status: "accepted";
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
  | { status: "submitting" }
  | { status: "accepted"; message: string; runId: string }
  | { status: "error"; message: string };

export function ManualRunControl({
  environment,
  onAccepted,
}: {
  environment: string;
  onAccepted?: (result: ManualRunResult) => void;
}) {
  const [runState, setRunState] = useState<RunState>({ status: "idle" });

  async function triggerManualRun() {
    setRunState({ status: "submitting" });
    const result = await dashboardApi<ManualRunResult>("operations/manual-run", {
      method: "POST",
      body: JSON.stringify({ environment }),
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
      <button
        className="button primary"
        disabled={runState.status === "submitting"}
        type="button"
        onClick={triggerManualRun}
      >
        {runState.status === "submitting" ? "Triggering" : "Run now"}
      </button>
      {runState.status === "accepted" ? (
        <p className="status-message">
          {runState.message} Run ID: {runState.runId}
        </p>
      ) : null}
      {runState.status === "error" ? <p className="status-message">{runState.message}</p> : null}
    </section>
  );
}
