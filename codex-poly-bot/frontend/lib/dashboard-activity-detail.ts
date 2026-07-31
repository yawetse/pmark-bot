import type { PipelineRunView } from "@/components/dashboard/manual-run-control";
import type {
  ActivityStageKey,
  ActivityStageView,
} from "@/lib/dashboard-activity-view-model";

export type ActivityRunRecord = {
  table: string;
  id: string;
  record: Record<string, unknown>;
};

export type ActivityRunRecordGroup = {
  stepKey: string;
  stepLabel: string;
  recordIds: string[];
  recordCount: number;
  items: ActivityRunRecord[];
};

export type ActivityRunDetail = {
  environment: string;
  run: PipelineRunView;
  records: ActivityRunRecordGroup[];
};

export type ActivityDetailRow = {
  id: string;
  venue?: string;
  name: string;
  provider?: string;
  status?: string;
  price?: string;
  liquidity?: string;
  spread?: string;
  volume?: string;
  outcome?: string;
  strategies?: string;
  signal?: string;
  strength?: string;
  confidence?: string;
  probability?: string;
  thesis?: string;
  side?: string;
  size?: string;
  orderType?: string;
  notional?: string;
  reason?: string;
  venueOrder?: string;
};

export type ActivityStageDetail = {
  key: ActivityStageKey;
  title: string;
  summary: string;
  explanation: string;
  rows: ActivityDetailRow[];
  expectedCount: number | null;
  recordCountNote?: string;
  gridTitle: string;
  emptyTitle: string;
  emptyBody: string;
};

export function buildActivityStageDetail(
  stage: ActivityStageView,
  detail: ActivityRunDetail,
): ActivityStageDetail {
  const rows = stageRows(stage.key, detail);
  const step = stageStep(stage.key, detail.run);
  const expectedCount = stage.value;
  const explanation = step?.message || stage.detail;
  const recordCountNote =
    expectedCount !== null &&
    stage.key !== "acted" &&
    rows.length !== expectedCount
      ? `Showing ${rows.length.toLocaleString()} stored detail ${
          rows.length === 1 ? "record" : "records"
        } for a recorded total of ${expectedCount.toLocaleString()}.`
      : undefined;

  return {
    key: stage.key,
    title: stageTitle(stage),
    summary: stageSummary(stage, rows, detail),
    explanation,
    rows,
    expectedCount,
    recordCountNote,
    gridTitle: gridTitle(stage.key),
    emptyTitle: emptyTitle(stage.key),
    emptyBody: explanation || emptyBody(stage.key),
  };
}

function stageRows(
  key: ActivityStageKey,
  detail: ActivityRunDetail,
): ActivityDetailRow[] {
  if (key === "scanned") {
    return scannedRows(detail);
  }
  if (key === "promising") {
    return scannerRows(detail);
  }
  if (key === "scored") {
    return reasoningRows(detail);
  }
  if (key === "approved") {
    return strategyRows(detail);
  }
  return orderRows(detail);
}

function scannedRows(detail: ActivityRunDetail): ActivityDetailRow[] {
  const rows: ActivityDetailRow[] = [];
  for (const item of recordsForStep(detail, "data_fetch")) {
    if (!item.table.endsWith(".dashboard_market_data_pulls")) continue;
    const candidates = Array.isArray(item.record.candidates)
      ? item.record.candidates
      : [];
    candidates.forEach((candidate, index) => {
      if (!isRecord(candidate)) return;
      const venue = text(candidate, "venue") || text(item.record, "venue");
      rows.push({
        id: text(candidate, "id") || `${item.id}:candidate:${index}`,
        venue,
        name: candidateName(candidate),
        status: text(candidate, "state") || "recorded",
        price: text(candidate, "price", "midpoint"),
        liquidity: text(candidate, "liquidity"),
        spread: text(candidate, "spread"),
        volume: text(candidate, "volume", "latestVolume"),
        outcome: text(candidate, "outcome", "category"),
      });
    });
  }
  return rows;
}

function scannerRows(detail: ActivityRunDetail): ActivityDetailRow[] {
  const persisted = recordsForStep(detail, "scanner")
    .filter((item) => item.table.endsWith(".scanner_candidates"))
    .map((item) => item.record)
    .filter((record) => text(record, "status").toLowerCase() === "accepted");
  const candidates = persisted.length
    ? persisted
    : decisionRecords(detail.run, "scanner", "candidates").filter(
        (record) => text(record, "status").toLowerCase() === "accepted",
      );

  return candidates.map((candidate, index) => ({
    id: text(candidate, "id") || `accepted-candidate:${index}`,
    venue: text(candidate, "venue"),
    name: candidateName(candidate),
    status: text(candidate, "status") || "accepted",
    price: text(candidate, "price"),
    liquidity: text(candidate, "liquidity"),
    spread: text(candidate, "spread"),
    strategies: joined(candidate, "strategy_names", "strategyNames"),
    reason: text(candidate, "refusal_reason", "refusalReason"),
  }));
}

function reasoningRows(detail: ActivityRunDetail): ActivityDetailRow[] {
  const persisted = recordsForStep(detail, "brain")
    .filter((item) => item.table.endsWith(".reasoning_outputs"))
    .map((item) => item.record)
    .filter((record) => text(record, "status").toLowerCase() === "scored");
  const outputs = persisted.length
    ? persisted
    : decisionRecords(detail.run, "brain", "outputs").filter(
        (record) => text(record, "status").toLowerCase() === "scored",
      );

  return outputs.map((output, index) => ({
    id: text(output, "id") || `model-score:${index}`,
    venue: text(output, "venue"),
    name: text(output, "instrument_id", "instrumentId") || "Unknown instrument",
    provider: text(output, "model_provider", "modelProvider"),
    status: text(output, "status") || "scored",
    signal: text(output, "directional_signal", "directionalSignal"),
    strength: formatScore(text(output, "signal_strength", "signalStrength")),
    confidence: formatScore(text(output, "confidence")),
    probability: formatScore(
      text(output, "estimated_probability", "estimatedProbability"),
    ),
    thesis: text(output, "output_thesis", "thesis"),
    reason: text(output, "refusal_reason", "refusalReason"),
  }));
}

function strategyRows(detail: ActivityRunDetail): ActivityDetailRow[] {
  const persisted = recordsForStep(detail, "execution")
    .filter((item) => item.table.endsWith(".strategy_consensus_outputs"))
    .map((item) => item.record)
    .filter((record) => text(record, "status").toLowerCase() === "approved");
  const outputs = persisted.length
    ? persisted
    : decisionRecords(detail.run, "execution", "consensus").filter(
        (record) => text(record, "status").toLowerCase() === "approved",
      );

  return outputs.map((output, index) => ({
    id: text(output, "id") || `strategy-approval:${index}`,
    venue: text(output, "venue"),
    name: text(output, "instrument_id", "instrumentId") || "Unknown instrument",
    provider: text(output, "model_provider", "modelProvider"),
    status: text(output, "status") || "approved",
    side: text(output, "side"),
    size: text(output, "size_multiplier", "sizeMultiplier"),
    strategies: joined(output, "strategy_names", "strategyNames"),
    reason: text(output, "refusal_reason", "refusalReason"),
  }));
}

function orderRows(detail: ActivityRunDetail): ActivityDetailRow[] {
  const persisted = recordsForStep(detail, "execution")
    .filter((item) => item.table.endsWith(".order_intents"))
    .map((item) => item.record);
  const intents = persisted.length
    ? persisted
    : decisionRecords(detail.run, "execution", "intents");

  return intents.map((intent, index) => ({
    id: text(intent, "id") || `order-intent:${index}`,
    venue: text(intent, "venue"),
    name: text(intent, "instrument_id", "instrumentId") || "Unknown instrument",
    provider: text(intent, "model_provider", "modelProvider"),
    status: text(intent, "status") || "unknown",
    side: text(intent, "side"),
    orderType: text(intent, "order_type", "orderType"),
    notional: text(intent, "notional_usd", "notionalUsd"),
    reason: orderReason(intent),
    venueOrder: text(intent, "venue_order_id", "venueOrderId"),
  }));
}

function recordsForStep(
  detail: ActivityRunDetail,
  stepKey: string,
): ActivityRunRecord[] {
  return detail.records.find((group) => group.stepKey === stepKey)?.items ?? [];
}

function decisionRecords(
  run: PipelineRunView,
  stepKey: string,
  key: string,
): Record<string, unknown>[] {
  const value = run.steps.find((step) => step.key === stepKey)?.decisions?.[key];
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function stageStep(key: ActivityStageKey, run: PipelineRunView) {
  const stepKey = {
    scanned: "data_fetch",
    promising: "scanner",
    scored: "brain",
    approved: "execution",
    acted: "execution",
  }[key];
  return run.steps.find((step) => step.key === stepKey);
}

function stageTitle(stage: ActivityStageView): string {
  const count = stage.value === null ? "Unavailable" : stage.value.toLocaleString();
  return `${stage.label}: ${count}`;
}

function stageSummary(
  stage: ActivityStageView,
  rows: ActivityDetailRow[],
  detail: ActivityRunDetail,
): string {
  const count = stage.value;
  if (stage.key === "scanned") {
    return `${formatCount(count)} market ${count === 1 ? "record entered" : "records entered"} the latest check.`;
  }
  if (stage.key === "promising") {
    const scanned = runMetric(detail.run, "candidateCount");
    return `${formatCount(count)} of ${formatCount(scanned)} scanned markets passed the scanner filters.`;
  }
  if (stage.key === "scored") {
    const accepted = runMetric(detail.run, "scannerAcceptedCount");
    return `${formatCount(count)} model ${count === 1 ? "score was" : "scores were"} recorded for ${formatCount(accepted)} scanner ${accepted === 1 ? "survivor" : "survivors"}.`;
  }
  if (stage.key === "approved") {
    const scored = runMetric(detail.run, "reasoningScoredCount");
    return `${formatCount(count)} of ${formatCount(scored)} scored outputs were approved by strategy consensus.`;
  }

  const planned = runMetric(detail.run, "orderIntentCount");
  const refused = runMetric(detail.run, "orderRefusedCount");
  const simulated = runMetric(detail.run, "orderSimulatedCount");
  const submitted = runMetric(detail.run, "orderSubmittedCount");
  return `${formatCount(count)} orders passed execution. ${formatCount(planned)} planned, ${formatCount(refused)} refused, ${formatCount(simulated)} simulated, and ${formatCount(submitted)} submitted. ${rows.length ? "The order decisions and stop reasons are listed below." : ""}`.trim();
}

function gridTitle(key: ActivityStageKey): string {
  return {
    scanned: "Scanned market records",
    promising: "Markets that passed the scanner",
    scored: "Model scores",
    approved: "Approved strategy decisions",
    acted: "Order decisions",
  }[key];
}

function emptyTitle(key: ActivityStageKey): string {
  return {
    scanned: "No scanned market details",
    promising: "No market passed the scanner",
    scored: "No usable model scores",
    approved: "No strategy approvals",
    acted: "No order intents were created",
  }[key];
}

function emptyBody(key: ActivityStageKey): string {
  return {
    scanned: "The latest run did not store market records.",
    promising: "Scanner filters did not accept a market in this run.",
    scored: "Model scoring did not produce a usable score in this run.",
    approved: "Strategy consensus did not approve a scored output in this run.",
    acted: "The run stopped before order planning.",
  }[key];
}

function runMetric(run: PipelineRunView, key: string): number | null {
  const value = run.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

function candidateName(record: Record<string, unknown>): string {
  return (
    text(
      record,
      "display_name",
      "displayName",
      "market",
      "symbol",
      "instrument_id",
      "instrumentId",
      "marketSlug",
      "market_slug",
    ) ||
    text(record, "id") ||
    "Unknown market"
  );
}

function orderReason(record: Record<string, unknown>): string {
  const refusal = text(record, "refusal_reason", "refusalReason");
  if (refusal) return refusal;
  const status = text(record, "status").toLowerCase();
  if (status === "simulated") return "Simulation only; no live venue order was submitted.";
  if (status === "submitted") return "Submitted to the venue.";
  return "";
}

function text(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (value === null || value === undefined || value === "") continue;
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
  }
  return "";
}

function joined(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) return value.map(String).join(", ");
    if (typeof value === "string") return value;
  }
  return "";
}

function formatScore(value: string): string {
  if (!value) return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0 || numeric > 1) return value;
  return `${value} (${new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(numeric)})`;
}

function formatCount(value: number | null): string {
  return value === null ? "An unknown number of" : value.toLocaleString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
