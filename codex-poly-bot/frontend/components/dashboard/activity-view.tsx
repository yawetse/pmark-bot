"use client";

import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Database,
  GitBranch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import {
  buildActivityFunnel,
  latestCompletedActivityRun,
  latestTradeOutcome,
  type ActivityStageKey,
} from "@/lib/dashboard-activity-view-model";
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
              <article className={`activity-stage ${stage.tone}`} key={stage.label}>
                <div className="activity-stage-top">
                  <span className="activity-stage-index">{index + 1}</span>
                  <Icon aria-hidden="true" size={18} />
                </div>
                <span>{stage.label}</span>
                <strong>{stage.value === null ? "Unavailable" : stage.value.toLocaleString()}</strong>
                <span className={`activity-stage-status ${stage.tone}`}>{stage.statusLabel}</span>
                <p>{stage.detail}</p>
              </article>
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
    </div>
  );
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
