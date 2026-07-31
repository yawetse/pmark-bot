import type { OperationsSummaryView } from "@/components/dashboard/operations-view";

// REQ: REQ-UI-020, REQ-UI-025

export type ActivityStageKey = "scanned" | "promising" | "scored" | "approved" | "acted";

export type ActivityStageView = {
  key: ActivityStageKey;
  label: string;
  value: number | null;
  detail: string;
  tone: "ok" | "waiting" | "blocked";
  statusLabel: "Passed" | "Stopped" | "No records" | "Unavailable";
};

type ActivityOperationsView = Pick<OperationsSummaryView, "pipelineRuns">;

export function latestCompletedActivityRun(operations?: ActivityOperationsView) {
  return operations?.pipelineRuns.find(
    (run) => Boolean(run.completedAt) || isTerminalStatus(run.status),
  );
}

export function buildActivityFunnel(operations?: ActivityOperationsView): ActivityStageView[] {
  const run = latestCompletedActivityRun(operations);
  const metadata = run?.metadata;
  const scanned = metric(metadata, "candidateCount");
  const promising = metric(metadata, "scannerAcceptedCount");
  const scored = metric(metadata, "reasoningScoredCount");
  const approved = metric(metadata, "strategyApprovedCount");
  const intents = metric(metadata, "orderIntentCount");
  const submitted = metric(metadata, "orderSubmittedCount");
  const simulated = metric(metadata, "orderSimulatedCount");
  const refused = metric(metadata, "orderRefusedCount");
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
      "scored",
      "Scored by models",
      promising,
      scored,
      "Model outputs recorded for the scanner survivors.",
    ),
    stage(
      "approved",
      "Strategy approved",
      scored,
      approved,
      "Scored opportunities approved before order sizing and execution gates.",
    ),
    stage(
      "acted",
      "Orders acted on",
      approved,
      passedRisk,
      orderDetail(intents, refused, simulated, submitted),
    ),
  ];
}

export function latestTradeOutcome(operations?: ActivityOperationsView): string {
  const run = latestCompletedActivityRun(operations);
  const metadata = run?.metadata;
  const accepted = metric(metadata, "scannerAcceptedCount");
  const scored = metric(metadata, "reasoningScoredCount");
  const approved = metric(metadata, "strategyApprovedCount");
  const intents = metric(metadata, "orderIntentCount");
  const submitted = metric(metadata, "orderSubmittedCount");
  const simulated = metric(metadata, "orderSimulatedCount");
  const refused = metric(metadata, "orderRefusedCount");

  if (submitted && submitted > 0) {
    return `${submitted.toLocaleString()} live order${submitted === 1 ? " was" : "s were"} submitted.`;
  }
  if (simulated && simulated > 0) {
    return `${simulated.toLocaleString()} order${simulated === 1 ? " was" : "s were"} simulated; no live order was submitted.`;
  }
  if (refused && refused > 0) {
    return `${refused.toLocaleString()} order intent${refused === 1 ? " was" : "s were"} refused by execution gates.`;
  }
  if (intents && intents > 0) {
    return `${intents.toLocaleString()} order intent${intents === 1 ? " was" : "s were"} created, but none reached simulation or live submission.`;
  }
  if (approved === 0 && scored !== null && scored > 0) {
    return "Models produced scores, but strategy consensus approved no trade.";
  }
  if (scored === 0 && accepted !== null && accepted > 0) {
    return "The scanner found candidates, but model scoring produced no usable score.";
  }
  if (accepted === 0) {
    return "No market passed the scanner filters.";
  }
  return "The latest run did not record enough data to identify the stopping gate.";
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

function orderDetail(
  intents: number | null,
  refused: number | null,
  simulated: number | null,
  submitted: number | null,
): string {
  if ([intents, refused, simulated, submitted].every((value) => value === null)) {
    return "Order execution totals were not recorded for this run.";
  }
  return `${formatCount(intents)} planned, ${formatCount(refused)} refused, ${formatCount(simulated)} simulated, ${formatCount(submitted)} submitted.`;
}

function formatCount(value: number | null): string {
  return value === null ? "unknown" : value.toLocaleString();
}

function isTerminalStatus(status: string): boolean {
  return ["completed", "succeeded", "success", "failed", "blocked", "partial"].includes(
    status.toLowerCase(),
  );
}
