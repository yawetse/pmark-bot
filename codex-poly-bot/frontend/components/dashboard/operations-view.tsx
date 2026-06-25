"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  EconomicsPanel,
  type EconomicsSummaryView,
} from "@/components/dashboard/economics-panel";
import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import {
  ManualRunControl,
  type ManualRunResult,
  type PipelineRunView,
  type PipelineStepView,
} from "@/components/dashboard/manual-run-control";
import {
  MarketDataPanel,
  type MarketDataPullView,
} from "@/components/dashboard/market-data-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const ORDER_STATES = ["refused", "submitted", "filled", "canceled", "failed", "unknown"] as const;
const PIPELINE_STEP_LABELS = ["Data Fetch", "Scanner", "Reasoning / Brain", "Execution", "Exit"] as const;

type OrderState = (typeof ORDER_STATES)[number];

export type OrderEventView = {
  id: string;
  state: OrderState;
  venue: string;
  provider: string;
  createdAt?: string | null;
  message?: string | null;
};

export type OperationsSummaryView = {
  killSwitch: string;
  openOrders: number;
  cancelProgress: string;
  manualReview: string;
  degradedVenueStatus: string;
  manualReviewState: string;
  orderEvents: OrderEventView[];
  pipelineRuns: PipelineRunView[];
};

const FALLBACK_OPERATIONS: OperationsSummaryView = {
  killSwitch: "unknown",
  openOrders: 0,
  cancelProgress: "0 / 0",
  manualReview: "none",
  degradedVenueStatus: "unavailable",
  manualReviewState: "unknown",
  orderEvents: [],
  pipelineRuns: [],
};

export function OperationsView({
  summary = FALLBACK_OPERATIONS,
  marketData,
  economics,
  loadError,
  timeZone = "system",
}: {
  summary?: OperationsSummaryView;
  marketData?: MarketDataPullView;
  economics?: EconomicsSummaryView;
  loadError?: string;
  timeZone?: string;
}) {
  const [latestMarketData, setLatestMarketData] = useState(marketData);
  const [pipelineRuns, setPipelineRuns] = useState(summary.pipelineRuns ?? []);
  const displayTimeZone = useResolvedTimeZone(timeZone);
  const pendingEvents = summary.orderEvents.filter(
    (event) => !["filled", "canceled", "failed", "refused"].includes(event.state),
  );
  const terminalEvents = summary.orderEvents.filter((event) =>
    ["filled", "canceled", "failed", "refused"].includes(event.state),
  );

  return (
    <div className="page-stack">
      <section className="panel wide-panel">
        <div className="panel-heading">
          <div>
            <p className="section-label">Operations</p>
            <h1>Trading Activity</h1>
          </div>
          {loadError ? (
            <span className="status blocked">api unavailable</span>
          ) : (
            <span className={`status ${summary.killSwitch === "active" ? "blocked" : "ok"}`}>
              kill switch {summary.killSwitch}
            </span>
          )}
        </div>
        {loadError ? <p className="status-message">{loadError}</p> : null}
        <div className="metric-grid">
          <Metric label="Open orders" value={String(summary.openOrders)} />
          <Metric label="Pending events" value={String(pendingEvents.length)} />
          <Metric label="Cancel progress" value={summary.cancelProgress} />
          <Metric label="Manual review" value={summary.manualReview} />
        </div>
        <ul className="status-list">
          <li>
            <span>Degraded venue status</span>
            <span className={`status ${summary.degradedVenueStatus === "none" ? "ok" : "blocked"}`}>
              {summary.degradedVenueStatus}
            </span>
          </li>
          <li>
            <span>Manual-review state</span>
            <span className={`status ${summary.manualReviewState === "clear" ? "ok" : "blocked"}`}>
              {summary.manualReviewState}
            </span>
          </li>
        </ul>
      </section>

      <ManualRunControl environment={process.env.NEXT_PUBLIC_APP_ENV ?? "local"} onAccepted={onManualRunAccepted} />

      <PipelineRunsPanel runs={pipelineRuns} timeZone={displayTimeZone} />

      {latestMarketData ? <MarketDataPanel marketData={latestMarketData} timeZone={displayTimeZone} /> : null}

      {economics ? <EconomicsPanel economics={economics} /> : null}

      <section className="panel wide-panel">
        <h2>Pending Orders</h2>
        <OrderTable
          emptyTitle="No pending orders"
          emptyBody="No orders are waiting for fill, cancellation, reconciliation, or manual review."
          events={pendingEvents}
        />
      </section>

      <section className="panel wide-panel">
        <h2>Trade and Order History</h2>
        <OrderTable
          emptyTitle="No trade or order history"
          emptyBody="No simulated or live order events have been recorded yet."
          events={terminalEvents}
        />
      </section>

      <section className="panel wide-panel">
        <KillSwitchControl active={summary.killSwitch === "active"} />
      </section>
    </div>
  );

  function onManualRunAccepted(result: ManualRunResult) {
    setLatestMarketData(result.marketDataPull);
    if (result.pipelineRun) {
      setPipelineRuns((currentRuns) => [
        result.pipelineRun as PipelineRunView,
        ...currentRuns.filter((run) => run.id !== result.pipelineRun?.id),
      ]);
    }
  }
}

function useResolvedTimeZone(preference: string): string {
  const [systemTimeZone, setSystemTimeZone] = useState("UTC");

  useEffect(() => {
    const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (resolved) {
      setSystemTimeZone(resolved);
    }
  }, []);

  return preference === "system" ? systemTimeZone : preference;
}

function OrderTable({
  events,
  emptyTitle,
  emptyBody,
}: {
  events: OrderEventView[];
  emptyTitle: string;
  emptyBody: string;
}) {
  const columns: DashboardGridColumn<OrderEventView>[] = [
    { field: "id", headerName: "Order", minWidth: 180 },
    { field: "state", headerName: "State", minWidth: 130 },
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "provider", headerName: "Provider", minWidth: 130 },
    { field: "message", headerName: "Message", minWidth: 240 },
    { field: "createdAt", headerName: "Created", minWidth: 190 },
  ];

  return (
    <DashboardDataGrid
      rows={events}
      columns={columns}
      emptyTitle={emptyTitle}
      emptyBody={emptyBody}
      getRowId={(event) => event.id}
      searchPlaceholder="Filter orders"
    />
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

function PipelineRunsPanel({
  runs,
  timeZone,
}: {
  runs: PipelineRunView[];
  timeZone: string;
}) {
  const latestRun = runs[0];
  const latestSteps: PipelineStepView[] = latestRun?.steps.length
    ? latestRun.steps
    : PIPELINE_STEP_LABELS.map((label, index) => ({
        id: `pending-${index + 1}`,
        key: label.toLowerCase().replaceAll(" ", "_").replaceAll("/", "_"),
        order: index + 1,
        label,
        status: "waiting",
        startedAt: null,
        completedAt: null,
        message: "Waiting for the next recorded run.",
        recordIds: [],
      }));
  const columns: DashboardGridColumn<PipelineRunView>[] = [
    { field: "id", headerName: "Run", minWidth: 220 },
    { field: "trigger", headerName: "Trigger", minWidth: 130 },
    { field: "status", headerName: "Status", minWidth: 130 },
    {
      field: "startedAt",
      headerName: "Started",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "completedAt",
      headerName: "Completed",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
    {
      field: "metadata",
      headerName: "Candidates",
      minWidth: 130,
      valueGetter: (params) => String(params.data?.metadata?.candidateCount ?? 0),
    },
  ];

  return (
    <section className="operator-panel span-2" aria-labelledby="pipeline-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Run pipeline</p>
          <h2 id="pipeline-title">Latest run steps</h2>
        </div>
        <span className={`status ${latestRun ? statusClass(latestRun.status) : "idle"}`}>
          {latestRun?.status ?? "idle"}
        </span>
      </div>
      {latestRun ? (
        <div className="pipeline-stepper">
          {latestSteps.map((step) => (
            <article className="pipeline-step" key={step.id}>
              <span className="pipeline-step-index">{step.order}</span>
              <div>
                <div className="pipeline-step-heading">
                  <strong>{step.label}</strong>
                  <span className={`status ${statusClass(step.status)}`}>{step.status}</span>
                </div>
                <p>{step.message}</p>
                <div className="pipeline-step-meta">
                  <span>Records: {step.recordIds?.length ?? 0}</span>
                  <span>Completed: {formatDateTime(step.completedAt, timeZone)}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="panel-note">No manual or scheduled runs have been recorded yet.</p>
      )}
      <DashboardDataGrid
        rows={runs}
        columns={columns}
        emptyTitle="No runs recorded"
        emptyBody="Manual and scheduled runs will appear here after they start."
        getRowId={(run) => run.id}
        searchPlaceholder="Filter runs"
      />
    </section>
  );
}

function formatDateTime(value: string | null | undefined, timeZone: string): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "not recorded";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(date);
}

function statusClass(status: string): "ok" | "idle" | "blocked" {
  if (["blocked", "failed", "rate_limited"].includes(status)) {
    return "blocked";
  }
  if (["waiting", "idle", "empty"].includes(status)) {
    return "idle";
  }
  return "ok";
}

function KillSwitchControl({ active }: { active: boolean }) {
  const [reason, setReason] = useState("operator stop");
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<
    | { status: "idle" }
    | { status: "submitting" }
    | { status: "done"; message: string }
    | { status: "error"; message: string }
  >({ status: "idle" });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed || active) {
      return;
    }
    setState({ status: "submitting" });
    const result = await dashboardApi<{ active?: boolean; live_disabled?: boolean }>("kill-switch", {
      method: "POST",
      body: JSON.stringify({
        environment: process.env.NEXT_PUBLIC_APP_ENV ?? "local",
        reason,
      }),
    });
    if (!result.ok) {
      setState({ status: "error", message: result.message });
      return;
    }
    setState({
      status: "done",
      message: result.data.live_disabled
        ? "Kill switch active. Live trading is disabled."
        : "Kill switch request accepted.",
    });
  }

  return (
    <form className="danger-zone" onSubmit={onSubmit}>
      <div>
        <p className="section-label">Emergency control</p>
        <h2>Kill Switch</h2>
        <p>
          Stops new live orders and asks the backend to cancel known open live orders.
          Dry-run records can still be reviewed.
        </p>
      </div>
      <label>
        Reason
        <input value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <label className="checkbox-row">
        <input
          checked={confirmed}
          disabled={active}
          type="checkbox"
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>I understand this disables live trading.</span>
      </label>
      <button className="button danger" disabled={!confirmed || active || state.status === "submitting"} type="submit">
        {active ? "Kill switch active" : "Activate kill switch"}
      </button>
      {state.status === "done" || state.status === "error" ? (
        <p className="status-message">{state.message}</p>
      ) : null}
    </form>
  );
}
