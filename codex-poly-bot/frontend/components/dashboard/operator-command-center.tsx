import {
  LoopMonitor,
  type LoopObservabilityView,
} from "@/components/dashboard/loop-monitor";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import type { StatusItem } from "@/components/dashboard/status-overview";
import type { WalletCredentialView } from "@/components/dashboard/wallet-status";

// REQ: REQ-UI-004, REQ-UI-005, REQ-UI-008, REQ-UI-010, REQ-UI-011, REQ-OBS-005

type ModelProviderSummary = {
  provider: string;
  positions?: unknown[];
  decisions?: unknown[];
  orders?: unknown[];
  budget?: {
    used_usd?: string;
    limit_usd?: string;
  };
  pnl?: string;
};

export type DashboardSummaryView = {
  environment: string;
  generated_at: string;
  status: {
    health: string;
    kill_switch_active: boolean;
    items: StatusItem[];
    worker?: {
      state?: string;
      value?: string;
      lastHeartbeatAt?: string | null;
      ageSeconds?: number | null;
    };
  };
  config: {
    version: string;
    settings: {
      default_selected_venue?: string;
      live_enabled?: boolean;
      trading_loop_interval_seconds?: number;
      venues?: Record<string, { enabled?: boolean }>;
    };
  };
  wallet: {
    credentials: WalletCredentialView[];
  };
  models: {
    providers: ModelProviderSummary[];
  };
  operations: OperationsSummaryView;
  notifications?: {
    state?: string;
    value?: string;
    recipientCount?: number;
  };
  loop: LoopObservabilityView;
  audit?: {
    items?: unknown[];
  };
};

export function OperatorCommandCenter({ summary }: { summary: DashboardSummaryView }) {
  const settings = summary.config.settings;
  const statusItems = summary.status.items;
  const selectedVenue = settings.default_selected_venue ?? "unknown";
  const selectedVenueEnabled = Boolean(settings.venues?.[selectedVenue]?.enabled);
  const liveEnabled = Boolean(settings.live_enabled);
  const credentialBlockers = summary.wallet.credentials.filter(
    (credential) => credential.requiredForLive !== false && !credential.present,
  );
  const blockedStatusItems = statusItems.filter((item) => item.state === "blocked");
  const openOrders = summary.operations.orderEvents.filter(
    (event) => !["filled", "canceled", "failed", "refused"].includes(event.state),
  );
  const recentOrders = summary.operations.orderEvents.slice(0, 5);
  const mode = resolveMode({
    liveEnabled,
    selectedVenueEnabled,
    killSwitchActive: summary.status.kill_switch_active,
    blockerCount: credentialBlockers.length + blockedStatusItems.length,
  });
  const nextActions = buildNextActions({
    liveEnabled,
    selectedVenue,
    selectedVenueEnabled,
    credentialBlockers,
    blockedStatusItems,
    notificationState: summary.notifications?.state,
    openOrders: openOrders.length,
  });
  const totals = modelTotals(summary.models.providers);

  return (
    <section className="operator-board" aria-labelledby="operator-title">
      <div className="operator-hero">
        <div>
          <p className="section-label">Current state</p>
          <h1 id="operator-title">{mode.title}</h1>
          <p>{mode.body}</p>
        </div>
        <div className={`mode-card ${mode.state}`}>
          <span>{mode.label}</span>
          <strong>{liveEnabled ? "Live flag on" : "Dry run"}</strong>
          <small>
            {selectedVenue} {selectedVenueEnabled ? "enabled" : "disabled"}
          </small>
        </div>
      </div>

      <LoopMonitor loop={summary.loop} />

      <div className="operator-grid">
        <section className="operator-panel span-2" aria-labelledby="running-title">
          <div className="panel-heading">
            <div>
              <p className="section-label">What is running</p>
              <h2 id="running-title">Runtime status</h2>
            </div>
            <span className={`status ${summary.status.health === "ok" ? "ok" : "blocked"}`}>
              {summary.status.health}
            </span>
          </div>
          <div className="status-card-grid">
            {statusItems.map((item) => (
              <article className="status-card" key={item.label}>
                <span className={`status-dot ${item.state}`} aria-hidden="true" />
                <div>
                  <strong>{item.label}</strong>
                  <p>{item.value}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="operator-panel" aria-labelledby="next-title">
          <p className="section-label">What happens next</p>
          <h2 id="next-title">Next actions</h2>
          <ol className="action-list">
            {nextActions.map((action) => (
              <li key={action.title}>
                <strong>{action.title}</strong>
                <span>{action.body}</span>
                {action.href ? (
                  <a className="inline-link" href={action.href}>
                    {action.linkLabel}
                  </a>
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        <section className="operator-panel" aria-labelledby="pending-title">
          <p className="section-label">Trades and orders</p>
          <h2 id="pending-title">Pending activity</h2>
          <div className="metric-strip">
            <Metric label="Open orders" value={String(openOrders.length)} />
            <Metric label="Recent events" value={String(summary.operations.orderEvents.length)} />
            <Metric label="Audit rows" value={String(summary.audit?.items?.length ?? 0)} />
          </div>
          {recentOrders.length > 0 ? (
            <div className="compact-list">
              {recentOrders.map((event) => (
                <div className="compact-row" key={event.id}>
                  <span>{event.id}</span>
                  <strong>{event.state}</strong>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No orders recorded"
              body="The backend has not recorded simulated or live orders in the current data store."
            />
          )}
        </section>

        <section className="operator-panel span-2" aria-labelledby="performance-title">
          <div className="panel-heading">
            <div>
              <p className="section-label">Performance</p>
              <h2 id="performance-title">Model and trade results</h2>
            </div>
            <a className="button" href="/dashboard/comparison">
              Compare models
            </a>
          </div>
          <div className="metric-grid compact">
            <Metric label="Realized P&L" value={formatUsd(totals.pnl)} />
            <Metric label="Open positions" value={String(totals.positions)} />
            <Metric label="Orders" value={String(totals.orders)} />
            <Metric label="Model spend" value={`${formatUsd(totals.budgetUsed)} / ${formatUsd(totals.budgetLimit)}`} />
          </div>
          <p className="panel-note">
            Performance stays empty until the bot records decisions, simulated orders,
            fills, or position updates through the backend.
          </p>
        </section>

        <section className="operator-panel" aria-labelledby="controls-title">
          <p className="section-label">Available controls</p>
          <h2 id="controls-title">What you can do</h2>
          <div className="control-list">
            <ControlLink
              href="/dashboard/config"
              title="Change configuration"
              body="Set venues, live mode, risk limits, model budgets, symbols, and notifications. Saves apply on the next loop."
            />
            <ControlLink
              href="/dashboard/operations"
              title="Manage operations"
              body="Review order state, manual review state, degraded venues, and the kill switch."
            />
            <ControlLink
              href="/dashboard/system"
              title="Check system readiness"
              body="Confirm credentials, worker heartbeat, notification readiness, and account status."
            />
          </div>
        </section>
      </div>
    </section>
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

function ControlLink({
  href,
  title,
  body,
}: {
  href: string;
  title: string;
  body: string;
}) {
  return (
    <a className="control-link" href={href}>
      <strong>{title}</strong>
      <span>{body}</span>
    </a>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function resolveMode({
  liveEnabled,
  selectedVenueEnabled,
  killSwitchActive,
  blockerCount,
}: {
  liveEnabled: boolean;
  selectedVenueEnabled: boolean;
  killSwitchActive: boolean;
  blockerCount: number;
}) {
  if (killSwitchActive) {
    return {
      title: "Live trading is stopped",
      body: "The kill switch is active. New live orders should not be created while this state is active.",
      label: "Stopped",
      state: "blocked",
    };
  }
  if (!liveEnabled) {
    return {
      title: "The bot is in dry-run mode",
      body: "No live orders will be submitted. Readiness checks and simulated activity can still be recorded.",
      label: "Monitor mode",
      state: "neutral",
    };
  }
  if (!selectedVenueEnabled || blockerCount > 0) {
    return {
      title: "Live trading is gated",
      body: "The live flag is on, but one or more required gates still block order submission.",
      label: "Action needed",
      state: "blocked",
    };
  }
  return {
    title: "Live trading can run",
    body: "Live mode and the selected venue are enabled. Keep risk limits, orders, and the kill switch visible.",
    label: "Live enabled",
    state: "ok",
  };
}

function buildNextActions({
  liveEnabled,
  selectedVenue,
  selectedVenueEnabled,
  credentialBlockers,
  blockedStatusItems,
  notificationState,
  openOrders,
}: {
  liveEnabled: boolean;
  selectedVenue: string;
  selectedVenueEnabled: boolean;
  credentialBlockers: WalletCredentialView[];
  blockedStatusItems: StatusItem[];
  notificationState?: string;
  openOrders: number;
}) {
  const actions: Array<{
    title: string;
    body: string;
    href?: string;
    linkLabel?: string;
  }> = [];

  if (!selectedVenueEnabled) {
    actions.push({
      title: "Decide whether to enable a venue",
      body: `${selectedVenue} is selected but disabled, so the app should not scan, score, or trade there.`,
      href: "/dashboard/config",
      linkLabel: "Open config",
    });
  }

  if (credentialBlockers.length > 0) {
    actions.push({
      title: "Clear credential blockers",
      body: `${credentialBlockers.length} live credential or account requirement is not ready.`,
      href: "/dashboard/system",
      linkLabel: "Open system",
    });
  }

  if (notificationState === "blocked") {
    actions.push({
      title: "Set notification recipients",
      body: "Alerts and daily digests need approved recipients and SES identity before live operation.",
      href: "/dashboard/config",
      linkLabel: "Open config",
    });
  }

  if (openOrders > 0) {
    actions.push({
      title: "Review open orders",
      body: `${openOrders} order is still open or waiting for a terminal state.`,
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }

  if (actions.length === 0 && !liveEnabled) {
    actions.push({
      title: "Stay in dry run or prepare signoff",
      body: "Dry run is the current safe mode. Use Config only when you are ready to change venue, risk, or live settings.",
      href: "/dashboard/config",
      linkLabel: "Review config",
    });
  }

  if (actions.length === 0) {
    actions.push({
      title: "Monitor the next loop",
      body: "No immediate blocker is visible. Watch orders, audit events, and performance after the next loop.",
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }

  const firstBlockedStatus = blockedStatusItems.find(
    (item) => !["Venue", "Wallet", "Notification"].includes(item.label),
  );
  if (firstBlockedStatus && actions.length < 4) {
    actions.push({
      title: `Check ${firstBlockedStatus.label.toLowerCase()}`,
      body: firstBlockedStatus.value,
      href: "/dashboard/system",
      linkLabel: "Open system",
    });
  }

  return actions.slice(0, 4);
}

function modelTotals(providers: ModelProviderSummary[]) {
  return providers.reduce(
    (totals, provider) => ({
      pnl: totals.pnl + numberFromString(provider.pnl),
      positions: totals.positions + (provider.positions?.length ?? 0),
      orders: totals.orders + (provider.orders?.length ?? 0),
      budgetUsed: totals.budgetUsed + numberFromString(provider.budget?.used_usd),
      budgetLimit: totals.budgetLimit + numberFromString(provider.budget?.limit_usd),
    }),
    { pnl: 0, positions: 0, orders: 0, budgetUsed: 0, budgetLimit: 0 },
  );
}

function numberFromString(value?: string): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}
