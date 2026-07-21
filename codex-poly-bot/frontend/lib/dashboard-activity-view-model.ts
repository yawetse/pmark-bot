import type { OperationsSummaryView } from "@/components/dashboard/operations-view";

// REQ: REQ-UI-020, REQ-UI-025

export type ActivityStageKey = "scanned" | "promising" | "confidence" | "risk";

export type ActivityStageView = {
  key: ActivityStageKey;
  label: string;
  value: number | null;
  detail: string;
  tone: "ok" | "waiting" | "blocked";
  statusLabel: "Passed" | "Stopped" | "No records" | "Unavailable";
};

export function latestCompletedActivityRun(operations?: OperationsSummaryView) {
  return operations?.pipelineRuns.find(
    (run) => Boolean(run.completedAt) || isTerminalStatus(run.status),
  );
}

export function buildActivityFunnel(operations?: OperationsSummaryView): ActivityStageView[] {
  const run = latestCompletedActivityRun(operations);
  const dataFetch = run?.steps.find((step) => step.key === "data_fetch");
  const scanner = run?.steps.find((step) => step.key === "scanner");
  const brain = run?.steps.find((step) => step.key === "brain");
  const execution = run?.steps.find((step) => step.key === "execution");

  const scanned = metric(dataFetch?.metrics, "candidateCount");
  const promising = metric(scanner?.metrics, "acceptedCount");
  const confidence = metric(brain?.metrics, "confidencePassedCount");
  const submitted = metric(execution?.metrics, "submittedCount");
  const simulated = metric(execution?.metrics, "simulatedCount");
  const passedRisk = submitted === null || simulated === null ? null : submitted + simulated;

  return [
    stage(
      "scanned",
      "Markets scanned",
      scanned,
      scanned,
      "Markets recorded in the latest completed data-fetch step.",
    ),
    stage(
      "promising",
      "Looked promising",
      scanned,
      promising,
      "Markets accepted by the latest completed scanner step.",
    ),
    stage(
      "confidence",
      "Passed confidence rule",
      promising,
      confidence,
      confidence === null
        ? "The persisted run does not expose a separate confidence-pass total."
        : "Candidates recorded as passing the confidence threshold.",
    ),
    stage(
      "risk",
      "Passed risk checks",
      confidence,
      passedRisk,
      "Order plans from this run that reached simulation or live submission.",
    ),
  ];
}

function stage(
  key: ActivityStageKey,
  label: string,
  entered: number | null,
  value: number | null,
  detail: string,
): ActivityStageView {
  if (value === null) {
    return { key, label, value, detail, tone: "waiting", statusLabel: "Unavailable" };
  }
  if (entered !== null && entered > 0 && value === 0) {
    return { key, label, value, detail, tone: "blocked", statusLabel: "Stopped" };
  }
  if (value > 0) {
    return { key, label, value, detail, tone: "ok", statusLabel: "Passed" };
  }
  return { key, label, value, detail, tone: "waiting", statusLabel: "No records" };
}

function metric(metrics: Record<string, unknown> | undefined, key: string): number | null {
  const value = metrics?.[key];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function isTerminalStatus(status: string): boolean {
  return ["completed", "succeeded", "success", "failed", "blocked", "partial"].includes(
    status.toLowerCase(),
  );
}
