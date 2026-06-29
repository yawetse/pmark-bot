"use client";

// REQ: REQ-UI-008, REQ-OBS-005

import { RefreshCw } from "lucide-react";

export type TickSummaryView = {
  id?: string | null;
  environment?: string | null;
  status: string;
  windowMinutes: number;
  windowStartedAt?: string | null;
  windowEndedAt?: string | null;
  latestRunId?: string | null;
  runCount: number;
  model?: string | null;
  promptVersion?: string | null;
  inputHash?: string | null;
  summaryMarkdown: string;
  keyEvents?: string[];
  warnings?: string[];
  usage?: {
    promptTokens?: number;
    completionTokens?: number;
    totalTokens?: number;
    costUsd?: string;
    costSource?: string;
    responseId?: string | null;
  };
  errorCode?: string | null;
  message?: string;
  generatedAt?: string | null;
};

export const FALLBACK_TICK_SUMMARY: TickSummaryView = {
  status: "empty",
  windowMinutes: 10,
  runCount: 0,
  summaryMarkdown: "No ticks have been recorded in the current summary window.",
  keyEvents: [],
  warnings: [],
  usage: {
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    costUsd: "0",
    costSource: "none",
    responseId: null,
  },
};

export function TickSummaryPanel({
  summary = FALLBACK_TICK_SUMMARY,
  timeZone,
  onRefresh,
  refreshing = false,
}: {
  summary?: TickSummaryView;
  timeZone: string;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  const usage = summary.usage ?? {};
  return (
    <section className="operator-panel span-2" aria-labelledby="tick-summary-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Tick summary</p>
          <h2 id="tick-summary-title">Last {summary.windowMinutes} minutes</h2>
        </div>
        <div className="panel-heading-actions">
          {onRefresh ? (
            <button
              className="icon-button"
              disabled={refreshing}
              onClick={onRefresh}
              title="Run tick summary now"
              type="button"
            >
              <RefreshCw aria-hidden="true" size={17} />
            </button>
          ) : null}
          <span className={`status ${statusClass(summary.status)}`}>{summary.status}</span>
        </div>
      </div>
      <div className="metric-grid">
        <Metric label="Runs" value={String(summary.runCount ?? 0)} />
        <Metric label="Model" value={summary.model ?? "none"} />
        <Metric label="Tokens" value={String(usage.totalTokens ?? 0)} />
        <Metric label="AI cost" value={`$${usage.costUsd ?? "0"}`} />
      </div>
      <div className="status-message">
        <MarkdownBlock value={summary.summaryMarkdown} />
      </div>
      {summary.keyEvents?.length ? (
        <div className="compact-list">
          {summary.keyEvents.map((event) => (
            <div className="compact-row" key={event}>
              <span>{event}</span>
            </div>
          ))}
        </div>
      ) : null}
      {summary.warnings?.length ? (
        <ul className="status-list">
          {summary.warnings.map((warning) => (
            <li key={warning}>
              <span>{warning}</span>
              <span className="status blocked">warning</span>
            </li>
          ))}
        </ul>
      ) : null}
      {summary.status === "error" && summary.message ? (
        <p className="panel-note">
          Summary error: {summary.errorCode ? `${summary.errorCode}: ` : ""}
          {summary.message}
        </p>
      ) : null}
      <p className="panel-note">
        Generated {formatDateTime(summary.generatedAt, timeZone)} from ticks since{" "}
        {formatDateTime(summary.windowStartedAt, timeZone)}.
      </p>
    </section>
  );
}

function MarkdownBlock({ value }: { value: string }) {
  const lines = value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) {
    return <p>No summary text was generated.</p>;
  }
  return (
    <>
      {lines.map((line) => (
        <p key={line}>{line.replace(/^[-*]\s+/, "")}</p>
      ))}
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function statusClass(status: string): string {
  if (["summarized", "ok", "completed"].includes(status)) {
    return "ok";
  }
  if (["error", "failed", "blocked"].includes(status)) {
    return "blocked";
  }
  return "idle";
}

function formatDateTime(value: string | null | undefined, timeZone: string): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(date);
}
