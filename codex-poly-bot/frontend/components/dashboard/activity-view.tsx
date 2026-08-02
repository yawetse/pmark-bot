"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Database,
  GitBranch,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import {
  buildActivityStageDetail,
  type ActivityDetailRow,
  type ActivityRunDetail,
} from "@/lib/dashboard-activity-detail";
import {
  buildActivityFunnel,
  latestCompletedActivityRun,
  latestTradeOutcome,
  type ActivityStageKey,
} from "@/lib/dashboard-activity-view-model";
import { dashboardApi } from "@/lib/api";
import { useDashboardRealtime, type DashboardRealtimeSnapshot } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-016, REQ-UI-020, REQ-UI-025

export function ActivityView({
  summary,
  initialErrors = [],
}: {
  summary?: OperationsSummaryView;
  initialErrors?: string[];
}) {
  const [operations, setOperations] = useState(summary);
  const [loadErrors, setLoadErrors] = useState(initialErrors);
  const onSnapshot = useCallback((snapshot: DashboardRealtimeSnapshot) => {
    setOperations((current) => ({
      ...snapshot.operations,
      pipelineRuns: snapshot.operations.pipelineRuns.length
        ? snapshot.operations.pipelineRuns
        : current?.pipelineRuns ?? [],
      scanner: snapshot.operations.scanner?.status === "deferred"
        ? current?.scanner ?? snapshot.operations.scanner
        : snapshot.operations.scanner ?? current?.scanner,
      reasoning: snapshot.operations.reasoning?.status === "deferred"
        ? current?.reasoning ?? snapshot.operations.reasoning
        : snapshot.operations.reasoning ?? current?.reasoning,
      strategyConsensus: snapshot.operations.strategyConsensus?.status === "deferred"
        ? current?.strategyConsensus ?? snapshot.operations.strategyConsensus
        : snapshot.operations.strategyConsensus ?? current?.strategyConsensus,
      execution: snapshot.operations.execution?.status === "deferred"
        ? current?.execution ?? snapshot.operations.execution
        : snapshot.operations.execution ?? current?.execution,
      exit: snapshot.operations.exit?.status === "deferred"
        ? current?.exit ?? snapshot.operations.exit
        : snapshot.operations.exit ?? current?.exit,
    }));
    setLoadErrors([]);
  }, []);
  const realtime = useDashboardRealtime({ onSnapshot });
  const funnel = useMemo(() => buildActivityFunnel(operations), [operations]);
  const latestRun = latestCompletedActivityRun(operations);
  const [selectedStageKey, setSelectedStageKey] = useState<ActivityStageKey | null>(null);
  const [detailState, setDetailState] = useState<ActivityDetailLoadState>({ status: "idle" });
  const selectedStage = useMemo(() => {
    const sourceFunnel =
      detailState.status === "ready"
        ? buildActivityFunnel({ pipelineRuns: [detailState.detail.run] })
        : funnel;
    return sourceFunnel.find((stage) => stage.key === selectedStageKey);
  }, [detailState, funnel, selectedStageKey]);
  const selectedDetail = useMemo(
    () =>
      selectedStage && detailState.status === "ready"
        ? buildActivityStageDetail(selectedStage, detailState.detail)
        : null,
    [detailState, selectedStage],
  );

  async function openStage(key: ActivityStageKey) {
    setSelectedStageKey(key);
    if (!latestRun) {
      setDetailState({
        status: "error",
        runId: null,
        stageKey: key,
        message: "No completed check is available yet. Run a check and try again.",
      });
      return;
    }
    if (
      detailState.status === "ready" &&
      detailState.runId === latestRun.id &&
      detailState.stageKey === key
    ) {
      return;
    }
    setDetailState({ status: "loading", runId: latestRun.id, stageKey: key });
    const result = await dashboardApi<ActivityRunDetail>(
      `operations/runs/${encodeURIComponent(latestRun.id)}?activity_stage=${encodeURIComponent(key)}`,
    );
    setDetailState(
      result.ok
        ? {
            status: "ready",
            runId: latestRun.id,
            stageKey: key,
            detail: result.data,
          }
        : {
            status: "error",
            runId: latestRun.id,
            stageKey: key,
            message: result.message,
          },
    );
  }

  return (
    <div className="ia-page activity-page" aria-labelledby="activity-title">
      <header className="ia-page-heading">
        <div>
          <p className="section-label">Activity</p>
          <h1 id="activity-title">What the bot checked</h1>
          <p>Follow the latest market check from the initial scan through order handling.</p>
        </div>
        <span className={`ia-update-chip ${realtime.status}`}>
          <span aria-hidden="true" />
          {latestRun?.completedAt ? `Updated ${relativeTime(latestRun.completedAt)}` : realtime.status === "connected" ? "Live updates" : "Waiting for a check"}
        </span>
      </header>

      {loadErrors.length ? (
        <p className="ia-degraded-message" role="status">
          <CircleAlert aria-hidden="true" size={16} /> Activity data is unavailable. {loadErrors.join(" ")}
        </p>
      ) : null}

      <section className="ia-panel" aria-labelledby="activity-funnel-title">
        <div className="ia-section-heading">
          <div>
            <p className="section-label">Latest check</p>
            <h2 id="activity-funnel-title">Last check, step by step</h2>
          </div>
          <span className={`status ${statusTone(latestRun?.status)}`}>{latestRun?.status ?? "not recorded"}</span>
        </div>
        {latestRun ? (
          <p className="activity-outcome-summary">
            <strong>Why no trade:</strong> {latestTradeOutcome(operations)}
          </p>
        ) : null}
        <div className="activity-funnel" aria-label="Latest check funnel">
          {funnel.map((stage, index) => {
            const Icon = stageIcon(stage.key);
            return (
              <button
                aria-label={`View details for ${stage.label.toLowerCase()}: ${
                  stage.value === null ? "unavailable" : stage.value.toLocaleString()
                }`}
                className={`activity-stage ${stage.tone}`}
                key={stage.label}
                type="button"
                onClick={() => void openStage(stage.key)}
              >
                <span className="activity-stage-top">
                  <span className="activity-stage-index">{index + 1}</span>
                  <Icon aria-hidden="true" size={18} />
                </span>
                <span className="activity-stage-label">{stage.label}</span>
                <strong>{stage.value === null ? "Unavailable" : stage.value.toLocaleString()}</strong>
                <span className={`activity-stage-status ${stage.tone}`}>{stage.statusLabel}</span>
                <span className="activity-stage-description">{stage.detail}</span>
                <span className="activity-stage-open">
                  View details <ChevronRight aria-hidden="true" size={14} />
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="ia-panel" aria-labelledby="recent-checks-title">
        <div className="ia-section-heading">
          <div>
            <p className="section-label">History</p>
            <h2 id="recent-checks-title">Recent checks</h2>
          </div>
          <Link className="ia-text-link" href="/dashboard/operations">
            Detailed operations and emergency stop <ArrowRight aria-hidden="true" size={15} />
          </Link>
        </div>
        {operations?.pipelineRuns.length ? (
          <div className="activity-log" role="list">
            {operations.pipelineRuns.slice(0, 8).map((run) => (
              <article className="activity-log-row" key={run.id} role="listitem">
                <time dateTime={run.completedAt ?? run.startedAt ?? undefined}>{formatTime(run.completedAt ?? run.startedAt)}</time>
                <div>
                  <strong>{checkSummary(run)}</strong>
                  <span>{run.trigger.replaceAll("_", " ")} · {runDetail(run)}</span>
                </div>
                <span className={`status ${statusTone(run.status)}`}>{run.status}</span>
              </article>
            ))}
          </div>
        ) : (
          <div className="ia-empty-state">
            <GitBranch aria-hidden="true" size={22} />
            <strong>No completed checks yet</strong>
            <p>A scheduled or manual run will appear here after its first persisted step.</p>
          </div>
        )}
      </section>

      <div className="ia-context-links">
        <Link href="/dashboard/data"><Database aria-hidden="true" size={17} /><span><strong>Market data</strong><small>Review venue inputs and freshness.</small></span><ArrowRight aria-hidden="true" size={15} /></Link>
        <Link href="/dashboard/operations"><ShieldCheck aria-hidden="true" size={17} /><span><strong>Detailed operations</strong><small>Run checks, review orders, or use the emergency stop.</small></span><ArrowRight aria-hidden="true" size={15} /></Link>
      </div>

      <Dialog.Root
        open={selectedStageKey !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedStageKey(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content
            aria-describedby="activity-detail-summary"
            className="dialog-content activity-detail-dialog"
          >
            <div className="activity-detail-header">
              <div>
                <p className="section-label">Latest check details</p>
                <Dialog.Title>
                  {selectedDetail?.title ?? selectedStage?.label ?? "Activity details"}
                </Dialog.Title>
                <Dialog.Description id="activity-detail-summary">
                  {selectedDetail?.summary ??
                    (detailState.status === "loading"
                      ? "Loading the records behind this count."
                      : "Review the records behind this activity count.")}
                </Dialog.Description>
              </div>
              <Dialog.Close
                aria-label="Close activity details"
                className="activity-detail-close"
                type="button"
              >
                <X aria-hidden="true" size={18} />
              </Dialog.Close>
            </div>

            {detailState.status === "loading" ? (
              <p className="activity-detail-loading" role="status">
                <LoaderCircle aria-hidden="true" size={18} />
                Loading persisted run details
              </p>
            ) : null}

            {detailState.status === "error" ? (
              <p className="ia-degraded-message" role="alert">
                <CircleAlert aria-hidden="true" size={16} />
                Details could not be loaded. {detailState.message}
              </p>
            ) : null}

            {selectedDetail ? (
              <>
                <p className="activity-detail-explanation">
                  <strong>Recorded result:</strong> {selectedDetail.explanation}
                </p>
                {selectedDetail.recordCountNote ? (
                  <p className="activity-detail-record-note" role="status">
                    {selectedDetail.recordCountNote}
                  </p>
                ) : null}
                <DashboardDataGrid
                  columns={activityDetailColumns(selectedDetail.key)}
                  description={activityGridDescription(selectedDetail.key)}
                  emptyBody={selectedDetail.emptyBody}
                  emptyTitle={selectedDetail.emptyTitle}
                  getRowId={(row) => row.id}
                  height={520}
                  pageSize={25}
                  rows={selectedDetail.rows}
                  searchPlaceholder={activitySearchPlaceholder(selectedDetail.key)}
                  title={selectedDetail.gridTitle}
                />
              </>
            ) : null}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

type ActivityDetailLoadState =
  | { status: "idle" }
  | { status: "loading"; runId: string; stageKey: ActivityStageKey }
  | {
      status: "ready";
      runId: string;
      stageKey: ActivityStageKey;
      detail: ActivityRunDetail;
    }
  | { status: "error"; runId: string | null; stageKey: ActivityStageKey; message: string };

function activityDetailColumns(
  key: ActivityStageKey,
): DashboardGridColumn<ActivityDetailRow>[] {
  const common: DashboardGridColumn<ActivityDetailRow>[] = [
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "name", headerName: key === "scanned" || key === "promising" ? "Market" : "Instrument", minWidth: 250 },
  ];
  if (key === "scanned") {
    return [
      ...common,
      { field: "status", headerName: "State", minWidth: 120 },
      { field: "price", headerName: "Price", minWidth: 110 },
      { field: "liquidity", headerName: "Liquidity", minWidth: 130 },
      { field: "spread", headerName: "Spread", minWidth: 110 },
      { field: "volume", headerName: "Volume", minWidth: 120 },
      { field: "outcome", headerName: "Outcome", minWidth: 160 },
    ];
  }
  if (key === "promising") {
    return [
      ...common,
      { field: "status", headerName: "State", minWidth: 120 },
      { field: "price", headerName: "Price", minWidth: 110 },
      { field: "liquidity", headerName: "Liquidity", minWidth: 130 },
      { field: "spread", headerName: "Spread", minWidth: 110 },
      { field: "strategies", headerName: "Strategies", minWidth: 210 },
    ];
  }
  if (key === "scored") {
    return [
      ...common,
      { field: "provider", headerName: "Model", minWidth: 130 },
      { field: "signal", headerName: "Signal", minWidth: 130 },
      { field: "strength", headerName: "Signal score", minWidth: 150 },
      { field: "confidence", headerName: "Confidence score", minWidth: 170 },
      { field: "probability", headerName: "Model probability", minWidth: 170 },
      { field: "thesis", headerName: "Model explanation", minWidth: 320 },
      { field: "reason", headerName: "Stop reason", minWidth: 220 },
    ];
  }
  if (key === "approved") {
    return [
      ...common,
      { field: "provider", headerName: "Model", minWidth: 130 },
      { field: "status", headerName: "Decision", minWidth: 130 },
      { field: "side", headerName: "Side", minWidth: 100 },
      { field: "size", headerName: "Size multiplier", minWidth: 140 },
      { field: "strategies", headerName: "Strategies", minWidth: 220 },
      { field: "reason", headerName: "Stop reason", minWidth: 240 },
    ];
  }
  return [
    ...common,
    { field: "provider", headerName: "Model", minWidth: 130 },
    { field: "status", headerName: "Order result", minWidth: 140 },
    { field: "side", headerName: "Side", minWidth: 100 },
    { field: "orderType", headerName: "Order type", minWidth: 120 },
    { field: "notional", headerName: "Notional USD", minWidth: 140 },
    { field: "reason", headerName: "Why it stopped", minWidth: 320 },
    { field: "venueOrder", headerName: "Venue order", minWidth: 180 },
  ];
}

function activityGridDescription(key: ActivityStageKey): string {
  return {
    scanned: "Every priced market record stored at the start of this check.",
    promising: "The scanner candidates that passed deterministic market filters.",
    scored: "Each usable model output, including its signal, confidence, and estimated probability.",
    approved: "The scored opportunities approved before order sizing and execution checks.",
    acted: "Every order intent, including refused, simulated, and submitted outcomes.",
  }[key];
}

function activitySearchPlaceholder(key: ActivityStageKey): string {
  return {
    scanned: "Filter the scanned markets",
    promising: "Filter the accepted markets",
    scored: "Filter model scores",
    approved: "Filter strategy approvals",
    acted: "Filter order decisions",
  }[key];
}

function stageIcon(key: ActivityStageKey) {
  return {
    scanned: Database,
    promising: Sparkles,
    scored: CheckCircle2,
    approved: ShieldCheck,
    acted: ArrowRight,
  }[key];
}

function statusTone(status?: string): "ok" | "waiting" | "blocked" | "idle" {
  const value = status?.toLowerCase() ?? "";
  if (["completed", "succeeded", "success", "ready", "submitted"].includes(value)) return "ok";
  if (["failed", "blocked", "error", "degraded"].includes(value)) return "blocked";
  return value ? "waiting" : "idle";
}

function checkSummary(run: OperationsSummaryView["pipelineRuns"][number]): string {
  const submitted = runMetric(run, "orderSubmittedCount");
  const simulated = runMetric(run, "orderSimulatedCount");
  const refused = runMetric(run, "orderRefusedCount");
  const intents = runMetric(run, "orderIntentCount");
  const approved = runMetric(run, "strategyApprovedCount");
  const scored = runMetric(run, "reasoningScoredCount");
  const accepted = runMetric(run, "scannerAcceptedCount");
  if (submitted > 0) return "Reached live order submission";
  if (simulated > 0) return "Reached simulated execution";
  if (refused > 0) return "Stopped at execution gates";
  if (intents > 0) return "Reached order planning";
  if (approved > 0) return "Reached strategy approval";
  if (scored > 0) return "Stopped at strategy consensus";
  if (accepted > 0) return "Stopped at model scoring";

  const stopped = run.steps.find((step) => statusTone(step.status) === "blocked");
  if (stopped) return `Stopped at ${stopped.label.toLowerCase()}`;
  const last = run.steps.at(-1);
  return last ? `Reached ${last.label.toLowerCase()}` : "No step detail recorded";
}

function runDetail(run: OperationsSummaryView["pipelineRuns"][number]): string {
  const scanned = runMetric(run, "candidateCount");
  const accepted = runMetric(run, "scannerAcceptedCount");
  if (scanned > 0 || accepted > 0) {
    return `${scanned.toLocaleString()} scanned · ${accepted.toLocaleString()} accepted`;
  }
  return run.steps.length
    ? `${run.steps.length.toLocaleString()} recorded steps`
    : "no candidate totals recorded";
}

function runMetric(
  run: OperationsSummaryView["pipelineRuns"][number],
  key: string,
): number {
  const value = run.metadata?.[key];
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function formatTime(value?: string | null): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not recorded" : new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(date);
}

function relativeTime(value: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return "recently";
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  return `${minutes}m ago`;
}
