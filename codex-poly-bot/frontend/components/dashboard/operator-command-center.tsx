"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  EconomicsPanel,
  type EconomicsSummaryView,
} from "@/components/dashboard/economics-panel";
import {
  EmptyState,
  MetricCard,
  MetricGrid,
  Panel,
} from "@/components/dashboard/dashboard-primitives";
import {
  LoopMonitor,
  type LoopObservabilityView,
} from "@/components/dashboard/loop-monitor";
import {
  ManualRunControl,
  type ManualRunResult,
} from "@/components/dashboard/manual-run-control";
import {
  MarketDataPanel,
  type MarketDataPullView,
} from "@/components/dashboard/market-data-panel";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import {
  FALLBACK_TICK_SUMMARY,
  TickSummaryPanel,
  type TickSummaryView,
} from "@/components/dashboard/tick-summary-panel";
import {
  applyDashboardTheme,
  PreferencesPanel,
  type UserPreferencesView,
} from "@/components/dashboard/preferences-panel";
import type { StatusItem } from "@/components/dashboard/status-overview";
import type { WalletCredentialView } from "@/components/dashboard/wallet-status";
import { dashboardApi } from "@/lib/api";

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
  preferences: UserPreferencesView;
  marketData: MarketDataPullView;
  economics: EconomicsSummaryView;
  loop: LoopObservabilityView;
  audit?: {
    items?: unknown[];
  };
};

export function OperatorCommandCenter({ summary }: { summary: DashboardSummaryView }) {
  const settings = summary.config.settings;
  const [preferences, setPreferences] = useState(summary.preferences.settings);
  const [marketData, setMarketData] = useState(summary.marketData);
  const [tickSummary, setTickSummary] = useState<TickSummaryView>(
    summary.operations.tickSummary ?? FALLBACK_TICK_SUMMARY,
  );
  const displayTimeZone = useResolvedTimeZone(preferences.timeZone);
  const statusItems = summary.status.items;
  const selectedVenue = settings.default_selected_venue ?? "unknown";
  const activeVenues = Object.entries(settings.venues ?? {})
    .filter(([, venue]) => Boolean(venue?.enabled))
    .map(([venue]) => venue);
  const activeVenueNames = activeVenues.length ? activeVenues.join(", ") : "none";
  const activeVenuesReady = activeVenues.length > 0;
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
    activeVenuesReady,
    killSwitchActive: summary.status.kill_switch_active,
    blockerCount: credentialBlockers.length + blockedStatusItems.length,
  });
  const nextActions = buildNextActions({
    liveEnabled,
    selectedVenue,
    activeVenuesReady,
    activeVenueNames,
    credentialBlockers,
    blockedStatusItems,
    notificationState: summary.notifications?.state,
    openOrders: openOrders.length,
  });

  useEffect(() => {
    applyDashboardTheme(preferences.theme);
  }, [preferences.theme]);

  function onManualRunAccepted(result: ManualRunResult) {
    setMarketData(result.marketDataPull);
    void refreshTickSummary();
  }

  async function refreshTickSummary() {
    const result = await dashboardApi<OperationsSummaryView>("operations/summary");
    if (result.ok) {
      setTickSummary(result.data.tickSummary ?? FALLBACK_TICK_SUMMARY);
    }
  }

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
            {activeVenueNames} active
          </small>
        </div>
      </div>

      <div className="state-summary-strip" aria-label="Current gate summary">
        <MetricCard
          label="Active venues"
          value={activeVenueNames}
          detail={`Default: ${selectedVenue}`}
        />
        <MetricCard
          label="Live mode"
          value={liveEnabled ? "Enabled" : "Dry run"}
          detail={summary.status.kill_switch_active ? "Kill switch active" : "Kill switch clear"}
        />
        <MetricCard
          label="Open orders"
          value={String(openOrders.length)}
          detail={`${summary.operations.orderEvents.length} recent events`}
        />
        <MetricCard
          label="Blockers"
          value={String(credentialBlockers.length + blockedStatusItems.length)}
          detail={blockedStatusItems[0]?.label ?? "No extra status blocker"}
        />
      </div>

      <div className="priority-grid">
        <Panel eyebrow="What happens next" title="Next actions" className="priority-panel">
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
        </Panel>

        <ManualRunControl environment={summary.environment} onAccepted={onManualRunAccepted} />

        <PreferencesPanel preferences={preferences} onSaved={setPreferences} />
      </div>

      <LoopMonitor loop={summary.loop} timeZone={displayTimeZone} />

      <div className="operator-grid">
        <Panel
          eyebrow="What is running"
          title="Runtime status"
          status={summary.status.health}
          statusTone={summary.status.health === "ok" ? "ok" : "blocked"}
          className="span-2"
        >
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
        </Panel>

        <TickSummaryPanel
          summary={tickSummary}
          timeZone={displayTimeZone}
        />

        <MarketDataPanel marketData={marketData} timeZone={displayTimeZone} />

        <Panel eyebrow="Trades and orders" title="Pending activity">
          <MetricGrid compact>
            <MetricCard label="Open orders" value={String(openOrders.length)} />
            <MetricCard label="Recent events" value={String(summary.operations.orderEvents.length)} />
            <MetricCard label="Audit rows" value={String(summary.audit?.items?.length ?? 0)} />
          </MetricGrid>
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
        </Panel>

        <EconomicsPanel economics={summary.economics} />

        <Panel eyebrow="Available controls" title="What you can do">
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
        </Panel>
      </div>
    </section>
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
    <Link className="control-link" href={href}>
      <strong>{title}</strong>
      <span>{body}</span>
    </Link>
  );
}

function resolveMode({
  liveEnabled,
  activeVenuesReady,
  killSwitchActive,
  blockerCount,
}: {
  liveEnabled: boolean;
  activeVenuesReady: boolean;
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
  if (!activeVenuesReady || blockerCount > 0) {
    return {
      title: "Live trading is gated",
      body: "The live flag is on, but one or more required gates still block order submission.",
      label: "Action needed",
      state: "blocked",
    };
  }
  return {
    title: "Live trading can run",
    body: "Live mode and active venues are enabled. Keep risk limits, orders, and the kill switch visible.",
    label: "Live enabled",
    state: "ok",
  };
}

function buildNextActions({
  liveEnabled,
  selectedVenue,
  activeVenuesReady,
  activeVenueNames,
  credentialBlockers,
  blockedStatusItems,
  notificationState,
  openOrders,
}: {
  liveEnabled: boolean;
  selectedVenue: string;
  activeVenuesReady: boolean;
  activeVenueNames: string;
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

  if (!activeVenuesReady) {
    actions.push({
      title: "Enable at least one venue",
      body: `No active venue is enabled. The default venue is ${selectedVenue}, and active venues are ${activeVenueNames}.`,
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
