"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  EconomicsPanel,
  type EconomicsSummaryView,
} from "@/components/dashboard/economics-panel";
import { ManualRunControl, type ManualRunResult } from "@/components/dashboard/manual-run-control";
import {
  MarketDataPanel,
  type MarketDataPullView,
} from "@/components/dashboard/market-data-panel";
import { dashboardApi } from "@/lib/api";

// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const ORDER_STATES = ["refused", "submitted", "filled", "canceled", "failed", "unknown"] as const;

type OrderState = (typeof ORDER_STATES)[number];

export type OrderEventView = {
  id: string;
  state: OrderState;
  venue: string;
  provider: string;
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
};

const FALLBACK_OPERATIONS: OperationsSummaryView = {
  killSwitch: "unknown",
  openOrders: 0,
  cancelProgress: "0 / 0",
  manualReview: "none",
  degradedVenueStatus: "unavailable",
  manualReviewState: "unknown",
  orderEvents: [],
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
  if (events.length === 0) {
    return (
      <div className="empty-state">
        <strong>{emptyTitle}</strong>
        <p>{emptyBody}</p>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>State</th>
            <th>Venue</th>
            <th>Provider</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <tr key={event.id}>
              <td>{event.id}</td>
              <td>
                <span className={`status ${event.state === "failed" || event.state === "refused" ? "blocked" : "ok"}`}>
                  {event.state}
                </span>
              </td>
              <td>{event.venue}</td>
              <td>{event.provider}</td>
              <td>{event.message ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
