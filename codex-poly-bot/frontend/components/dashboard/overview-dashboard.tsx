"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Check,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  DollarSign,
  HeartPulse,
  RotateCcw,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import { dashboardApi, type ApiClientResult } from "@/lib/api";
import type { AllowedConfigPath } from "@/lib/config-paths";
import {
  deriveOverviewState,
  type OverviewState,
} from "@/lib/dashboard-overview-state";
import {
  useDashboardRealtime,
  type DashboardRealtimeSnapshot,
  type TickScheduleView,
} from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-017, REQ-UI-018, REQ-UI-019, REQ-UI-025, REQ-UI-026

type ConfigValue = string | boolean | number | string[] | Record<string, unknown>;

type ConfigSnapshot = {
  environment: string;
  version: string;
  settings: Record<string, unknown>;
};

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
};

type NotificationSettingsView = {
  state?: string;
  recipientCount?: number;
};

type OverviewBundle = {
  config: ConfigSnapshot;
  operations: OperationsSummaryView;
  marketData: MarketDataPullView;
  tickSchedule: TickScheduleView;
  notifications: NotificationSettingsView;
};

type PanelState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

type Recommendation = {
  id: "tighten" | "current" | "loosen";
  title: string;
  summary: string;
  effect: string;
  tradeoff: string;
  path?: AllowedConfigPath;
  currentValue?: ConfigValue;
  nextValue?: ConfigValue;
};

type PendingRecommendation = Recommendation & {
  path: AllowedConfigPath;
  currentValue: ConfigValue;
  nextValue: ConfigValue;
};

type UndoChange = {
  label: string;
  path: AllowedConfigPath;
  previousValue: ConfigValue;
  appliedValue: ConfigValue;
};

type MutationState =
  | { status: "idle" }
  | { status: "saving"; message: string }
  | { status: "saved"; message: string }
  | { status: "error"; message: string };

const FALLBACK_SCHEDULE: TickScheduleView = {
  environment: "local",
  generatedAt: new Date(0).toISOString(),
  intervalSeconds: 900,
  lastTickAt: null,
  lastTickStatus: null,
  lastTickRunId: null,
  lastTickSource: "none",
  lastHeartbeatAt: null,
  heartbeatStatus: null,
  ageSeconds: null,
  nextTickAt: new Date(0).toISOString(),
  secondsUntilNextTick: 0,
  due: false,
  source: "waiting for scheduler",
};

export function OverviewDashboard() {
  const [config, setConfig] = useState<PanelState<ConfigSnapshot>>({ status: "loading" });
  const [operations, setOperations] = useState<PanelState<OperationsSummaryView>>({ status: "loading" });
  const [marketData, setMarketData] = useState<PanelState<MarketDataPullView>>({ status: "loading" });
  const [schedule, setSchedule] = useState<PanelState<TickScheduleView>>({ status: "loading" });
  const [notifications, setNotifications] = useState<PanelState<NotificationSettingsView>>({ status: "loading" });
  const [pendingRecommendation, setPendingRecommendation] = useState<PendingRecommendation | null>(null);
  const [undoChange, setUndoChange] = useState<UndoChange | null>(null);
  const [mutation, setMutation] = useState<MutationState>({ status: "idle" });
  const [configRefreshError, setConfigRefreshError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void loadOverviewBundle({
      active: () => active,
      setConfig,
      setOperations,
      setMarketData,
      setSchedule,
      setNotifications,
    });
    return () => {
      active = false;
    };
  }, []);

  const onRealtimeSnapshot = useCallback((snapshot: DashboardRealtimeSnapshot) => {
    setOperations({ status: "ready", data: snapshot.operations });
    setMarketData({ status: "ready", data: snapshot.marketData });
    setSchedule({ status: "ready", data: snapshot.tickSchedule });
  }, []);
  const initialLoadComplete = [config, operations, marketData, schedule, notifications].every(
    (state) => state.status === "ready",
  );
  const realtime = useDashboardRealtime({
    onSnapshot: onRealtimeSnapshot,
    enabled: initialLoadComplete,
  });

  const configData = config.status === "ready" ? config.data : null;
  const operationData = operations.status === "ready" ? operations.data : null;
  const marketDataValue = marketData.status === "ready" ? marketData.data : null;
  const scheduleData = schedule.status === "ready" ? schedule.data : FALLBACK_SCHEDULE;
  const notificationData = notifications.status === "ready" ? notifications.data : null;
  const settings = configData?.settings ?? {};
  const liveEnabled = booleanValue(valueAtPath(settings, "live_enabled"));
  const activeVenueLabels = enabledVenueLabels(settings);
  const criticalErrors = [
    ...panelErrors([config, operations, marketData, schedule, notifications]),
    ...(configRefreshError ? [configRefreshError] : []),
  ];
  const overview = useMemo(
    () =>
      deriveOverviewState({
        operations: operationData,
        marketData: marketDataValue,
        activeVenueLabels,
        configReady: config.status === "ready",
        notificationsReady: notifications.status === "ready"
          ? notifications.data.state !== "blocked" &&
            (notifications.data.recipientCount ?? 0) > 0
          : null,
        criticalErrors,
      }),
    [activeVenueLabels, config.status, criticalErrors, marketDataValue, notificationData, notifications, operationData],
  );
  const recommendations = useMemo(
    () => recommendationOptions(overview, settings),
    [overview, settings],
  );
  const loading = [config, operations, marketData, schedule, notifications].some(
    (state) => state.status === "loading",
  );

  async function applyRecommendation() {
    if (!pendingRecommendation || !configData) {
      return;
    }
    setUndoChange(null);
    setMutation({ status: "saving", message: `Applying ${pendingRecommendation.title.toLowerCase()}.` });
    const saved = await submitConfigPatch(
      configData,
      pendingRecommendation.path,
      pendingRecommendation.nextValue,
    );
    if (!saved.ok) {
      setMutation({ status: "error", message: configError(saved) });
      setPendingRecommendation(null);
      return;
    }
    const appliedRecommendation = pendingRecommendation;
    const updatedConfig = configSnapshotAfterSave(
      configData,
      appliedRecommendation.path,
      appliedRecommendation.nextValue,
      saved.data,
    );
    setConfig({ status: "ready", data: updatedConfig });
    setUndoChange({
      label: appliedRecommendation.title,
      path: appliedRecommendation.path,
      previousValue: appliedRecommendation.currentValue,
      appliedValue: appliedRecommendation.nextValue,
    });
    setMutation({ status: "saved", message: `${appliedRecommendation.title} saved. It applies on the next loop.` });
    setPendingRecommendation(null);
    await refreshConfig();
  }

  async function undoRecommendation() {
    if (!undoChange || config.status !== "ready") {
      return;
    }
    const change = undoChange;
    setUndoChange(null);
    setMutation({ status: "saving", message: `Undoing ${change.label.toLowerCase()}.` });
    const saved = await submitConfigPatch(config.data, change.path, change.previousValue);
    if (!saved.ok) {
      setMutation({ status: "error", message: configError(saved, "Undo was not applied.") });
      return;
    }
    await refreshConfig();
    setMutation({ status: "saved", message: `${change.label} was undone. The prior value applies on the next loop.` });
  }

  async function refreshConfig(): Promise<ConfigSnapshot | null> {
    const result = await dashboardApi<ConfigSnapshot>("config/current");
    if (!result.ok) {
      setConfigRefreshError(`The setting saved, but the latest config could not be reloaded. ${result.message}`);
      return null;
    }
    setConfigRefreshError(null);
    setConfig({ status: "ready", data: result.data });
    return result.data;
  }

  return (
    <div className="overview-page" aria-labelledby="overview-title">
      <header className="overview-heading">
        <div>
          <p className="section-label">Overview</p>
          <h1 id="overview-title">Does anything need me right now?</h1>
          <p>Current operating state from the latest saved and realtime checks.</p>
        </div>
        <span className={`overview-connection ${realtime.status}`}>
          <span aria-hidden="true" />
          {realtime.status === "connected" ? "Live updates" : realtime.status === "offline" ? "Updates offline" : "Connecting"}
        </span>
      </header>

      {loading ? (
        <section className="overview-state-card loading" aria-busy="true" aria-label="Loading current dashboard state">
          <div className="overview-state-icon"><Activity aria-hidden="true" size={20} /></div>
          <div><h2>Loading the latest check</h2><p>Current settings and operation results are being combined.</p></div>
        </section>
      ) : (
        <OverviewStateCard
          overview={overview}
          recommendations={recommendations}
          onChooseRecommendation={(recommendation) => {
            if (recommendation.path && recommendation.currentValue !== undefined && recommendation.nextValue !== undefined) {
              setPendingRecommendation(recommendation as PendingRecommendation);
            }
          }}
        />
      )}

      {criticalErrors.length && (
        overview.kind !== "attention" || !overview.blockers.some((blocker) => blocker.key === "data")
      ) ? (
        <p className="overview-degraded-note" role="status">
          <CircleAlert aria-hidden="true" size={16} />
          Some current data is unavailable. Valid results remain visible. {criticalErrors[0]}
        </p>
      ) : null}

      {mutation.status !== "idle" ? (
        <div className={`overview-mutation ${mutation.status}`} aria-live="polite">
          <span>{mutation.message}</span>
          {undoChange && mutation.status === "saved" ? (
            <button className="button subtle" onClick={() => void undoRecommendation()} type="button">
              <RotateCcw aria-hidden="true" size={15} /> Undo
            </button>
          ) : null}
        </div>
      ) : null}

      <section className="overview-monitoring" aria-labelledby="overview-monitoring-title">
        <div className="overview-section-heading">
          <div>
            <p className="section-label">Current state</p>
            <h2 id="overview-monitoring-title">How things are running</h2>
          </div>
        </div>
        <div className="overview-fact-grid">
          <OverviewFact
            detail={liveEnabled ? "Real orders still require every safety gate." : "Orders are recorded as practice only."}
            label="Mode"
            value={config.status === "error" ? "Unavailable" : liveEnabled ? "Real money allowed" : "Simulation"}
          />
          <OverviewFact
            detail="Markets enabled for the next check."
            label="Active markets"
            value={config.status === "error" ? "Unavailable" : activeVenueLabels.join(", ") || "None"}
          />
          <OverviewFact
            detail={scheduleData.lastTickStatus ?? "No result recorded"}
            label="Last check"
            value={formatDateTime(scheduleData.lastTickAt)}
          />
          <OverviewFact
            detail={`Runs about every ${scheduleData.intervalSeconds ?? 900} seconds.`}
            label="Next check"
            value={formatDateTime(scheduleData.nextTickAt)}
          />
        </div>
      </section>

      <section className="overview-recent" aria-labelledby="overview-recent-title">
        <div>
          <p className="section-label">Recent result</p>
          <h2 id="overview-recent-title">{recentResult(operationData).title}</h2>
          <p>{recentResult(operationData).body}</p>
        </div>
        <Link className="overview-text-link" href="/dashboard/activity">
          See full activity <ArrowRight aria-hidden="true" size={15} />
        </Link>
      </section>

      <section className="overview-explore" aria-labelledby="overview-explore-title">
        <div className="overview-section-heading">
          <div>
            <p className="section-label">Next</p>
            <h2 id="overview-explore-title">Explore more</h2>
          </div>
          <Link className="overview-health-link" href="/dashboard/system">
            <HeartPulse aria-hidden="true" size={15} /> System health
          </Link>
        </div>
        <div className="overview-link-grid">
          <ExploreLink href="/dashboard/performance" icon={BarChart3} title="Performance" body="Review venue-confirmed results." />
          <ExploreLink href="/dashboard/config" icon={SlidersHorizontal} title="Settings" body="Change common rules and alerts." />
          <ExploreLink href="/dashboard/help" icon={CircleHelp} title="Help" body="See the five-step process." />
        </div>
      </section>

      <RecommendationDialog
        recommendation={pendingRecommendation}
        onCancel={() => setPendingRecommendation(null)}
        onConfirm={() => void applyRecommendation()}
        saving={mutation.status === "saving"}
      />
    </div>
  );
}

function OverviewStateCard({
  overview,
  recommendations,
  onChooseRecommendation,
}: {
  overview: OverviewState;
  recommendations: Recommendation[];
  onChooseRecommendation: (recommendation: Recommendation) => void;
}) {
  const Icon = overview.kind === "live" ? DollarSign : overview.kind === "clear" ? CheckCircle2 : CircleAlert;
  return (
    <section className={`overview-state-card ${overview.kind}`} aria-labelledby="overview-state-title">
      <div className="overview-state-header">
        <div className="overview-state-icon"><Icon aria-hidden="true" size={20} /></div>
        <div>
          <p className="section-label">Right now</p>
          <h2 id="overview-state-title">{overview.title}</h2>
          <p>{overview.body}</p>
        </div>
      </div>
      {overview.kind === "attention" ? (
        <div className="overview-attention-list">
          {overview.blockers.map((blocker) => (
            <article key={blocker.key}>
              <div><strong>{blocker.title}</strong><p>{blocker.body}</p></div>
              <Link className="button primary" href={blocker.href}>{blocker.linkLabel}</Link>
            </article>
          ))}
        </div>
      ) : null}
      {overview.kind === "live" ? (
        <div className="overview-live-detail">
          <div><span>Market</span><strong>{overview.order?.instrumentId ?? "Latest submitted order"}</strong></div>
          <div><span>Side</span><strong>{overview.order?.side ?? "Submitted"}</strong></div>
          <div><span>Amount</span><strong>{formatUsd(overview.order?.notionalUsd)}</strong></div>
          <Link className="button primary" href="/dashboard/activity">View activity</Link>
        </div>
      ) : null}
      {overview.kind === "attention" && recommendations.length ? (
        <div className="overview-recommendations" aria-labelledby="overview-recommendations-title">
          <div>
            <p className="section-label">Recommended settings</p>
            <h3 id="overview-recommendations-title">Choose how strict the next check should be</h3>
          </div>
          <div className="overview-recommendation-grid">
            {recommendations.map((recommendation) => (
              <article className={recommendation.id === "current" ? "current" : ""} key={recommendation.id}>
                <div>
                  <span className="overview-plan-label">{recommendation.id === "current" ? "In use" : recommendation.id}</span>
                  <h4>{recommendation.title}</h4>
                  <p>{recommendation.summary}</p>
                </div>
                <dl><div><dt>Effect</dt><dd>{recommendation.effect}</dd></div><div><dt>Tradeoff</dt><dd>{recommendation.tradeoff}</dd></div></dl>
                <button
                  className={`button ${recommendation.id === "current" ? "subtle" : "primary"}`}
                  disabled={recommendation.id === "current"}
                  onClick={() => onChooseRecommendation(recommendation)}
                  type="button"
                >
                  {recommendation.id === "current" ? <Check aria-hidden="true" size={15} /> : <Settings2 aria-hidden="true" size={15} />}
                  {recommendation.id === "current" ? "Current setting" : "Use this"}
                </button>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RecommendationDialog({
  recommendation,
  onCancel,
  onConfirm,
  saving,
}: {
  recommendation: PendingRecommendation | null;
  onCancel: () => void;
  onConfirm: () => void;
  saving: boolean;
}) {
  if (!recommendation) {
    return null;
  }
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content overview-confirm-dialog" aria-describedby="recommendation-confirm-body">
          <div className="dialog-heading">
            <Settings2 aria-hidden="true" size={22} />
            <div>
              <Dialog.Title>Confirm {recommendation.title.toLowerCase()}</Dialog.Title>
              <Dialog.Description id="recommendation-confirm-body">
                This audited setting change applies on the next loop. You can undo it until another setting changes or you leave this page.
              </Dialog.Description>
            </div>
          </div>
          <div className="overview-confirm-values">
            <div><span>Current</span><strong>{formatConfigValue(recommendation.currentValue)}</strong></div>
            <ArrowRight aria-hidden="true" size={18} />
            <div><span>Proposed</span><strong>{formatConfigValue(recommendation.nextValue)}</strong></div>
          </div>
          <p className="panel-note">Setting: {recommendation.path}</p>
          <div className="dialog-actions">
            <button className="button subtle" disabled={saving} onClick={onCancel} type="button"><X aria-hidden="true" size={15} /> Cancel</button>
            <button className="button primary" disabled={saving} onClick={onConfirm} type="button">{saving ? "Applying" : "Confirm change"}</button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function OverviewFact({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="overview-fact"><span>{label}</span><strong>{value}</strong><p>{detail}</p></article>;
}

function ExploreLink({ href, icon: Icon, title, body }: { href: string; icon: typeof Activity; title: string; body: string }) {
  return <Link className="overview-link-card" href={href}><Icon aria-hidden="true" size={19} /><div><strong>{title}</strong><span>{body}</span></div><ArrowRight aria-hidden="true" size={16} /></Link>;
}

function recommendationOptions(overview: OverviewState, settings: Record<string, unknown>): Recommendation[] {
  if (overview.kind !== "attention") {
    return [];
  }
  const blocker = overview.blockers.find((item) => item.recommendationPath);
  const path = blocker?.recommendationPath;
  if (!path) {
    return [];
  }
  const alpaca = path.includes("alpaca");
  const spread = path.includes("max_spread");
  const fallback = spread ? (alpaca ? 0.5 : 0.05) : alpaca ? 0.6 : 0.75;
  const rawCurrent = valueAtPath(settings, path);
  const current = finiteNumber(rawCurrent, fallback);
  const step = spread ? (alpaca ? 0.05 : 0.01) : 0.05;
  const min = spread ? (alpaca ? 0.01 : 0) : 0;
  const max = spread ? (alpaca ? 5 : 0.2) : 1;
  const tighter = spread ? clamp(current - step, min, max) : clamp(current + step, min, max);
  const looser = spread ? clamp(current + step, min, max) : clamp(current - step, min, max);
  return [
    {
      id: "tighten",
      title: "Tighten",
      summary: spread ? "Allow only narrower spreads." : "Require more model confidence.",
      effect: spread ? "Fewer markets pass the price-quality rule." : "Fewer scores can move forward.",
      tradeoff: "The next check may find fewer candidates.",
      path,
      currentValue: typedNumber(rawCurrent, current),
      nextValue: typedNumber(rawCurrent, tighter),
    },
    {
      id: "current",
      title: "Keep current",
      summary: `Leave ${pathLabel(path)} at ${formatConfigValue(typedNumber(rawCurrent, current))}.`,
      effect: "No config change.",
      tradeoff: "The same gate remains for the next check.",
    },
    {
      id: "loosen",
      title: "Loosen",
      summary: spread ? "Allow a slightly wider spread." : "Allow a slightly lower confidence score.",
      effect: "More candidates can reach later checks.",
      tradeoff: "Lower-quality candidates may move forward, while risk gates still apply.",
      path,
      currentValue: typedNumber(rawCurrent, current),
      nextValue: typedNumber(rawCurrent, looser),
    },
  ];
}

function configSnapshotAfterSave(
  snapshot: ConfigSnapshot,
  path: AllowedConfigPath,
  value: ConfigValue,
  response: ConfigUpdateResponse,
): ConfigSnapshot {
  return {
    ...snapshot,
    version: response.new_version ?? response.current_version ?? snapshot.version,
    settings: valueAtUpdatedPath(snapshot.settings, path, value),
  };
}

function valueAtUpdatedPath(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  value: ConfigValue,
): Record<string, unknown> {
  const next = structuredClone(settings);
  const segments = path.split(".");
  let current = next;
  for (const segment of segments.slice(0, -1)) {
    const child = current[segment];
    current[segment] = child && typeof child === "object" && !Array.isArray(child) ? child : {};
    current = current[segment] as Record<string, unknown>;
  }
  current[segments.at(-1) ?? path] = value;
  return next;
}

function recentResult(operations: OperationsSummaryView | null): { title: string; body: string } {
  if (!operations) return { title: "Latest result unavailable", body: "Activity data has not loaded." };
  if ((operations.execution?.submittedCount ?? 0) > 0) return { title: "A real order was submitted", body: `${operations.execution?.submittedCount ?? 0} live order${operations.execution?.submittedCount === 1 ? "" : "s"} reached submission.` };
  if ((operations.execution?.simulatedCount ?? 0) > 0) return { title: "Practice orders were recorded", body: `${operations.execution?.simulatedCount ?? 0} simulated order${operations.execution?.simulatedCount === 1 ? "" : "s"} passed the current checks.` };
  if ((operations.scanner?.acceptedCount ?? 0) > 0) return { title: "Markets reached model scoring", body: `${operations.scanner?.acceptedCount ?? 0} candidate${operations.scanner?.acceptedCount === 1 ? "" : "s"} passed market filters.` };
  return { title: "No order was placed", body: operations.pipelineRuns[0]?.status ? `The latest check ended with status ${operations.pipelineRuns[0].status}.` : "No completed check is available yet." };
}

async function loadOverviewBundle({
  active,
  setConfig,
  setOperations,
  setMarketData,
  setSchedule,
  setNotifications,
}: {
  active: () => boolean;
  setConfig: (state: PanelState<ConfigSnapshot>) => void;
  setOperations: (state: PanelState<OperationsSummaryView>) => void;
  setMarketData: (state: PanelState<MarketDataPullView>) => void;
  setSchedule: (state: PanelState<TickScheduleView>) => void;
  setNotifications: (state: PanelState<NotificationSettingsView>) => void;
}) {
  const result = await dashboardApi<OverviewBundle>("dashboard/overview");
  if (!active()) return;
  if (!result.ok) {
    const error = { status: "error" as const, message: result.message };
    setConfig(error);
    setOperations(error);
    setMarketData(error);
    setSchedule(error);
    setNotifications(error);
    return;
  }
  setConfig({ status: "ready", data: result.data.config });
  setOperations({ status: "ready", data: result.data.operations });
  setMarketData({ status: "ready", data: result.data.marketData });
  setSchedule({ status: "ready", data: result.data.tickSchedule });
  setNotifications({ status: "ready", data: result.data.notifications });
}

async function submitConfigPatch(snapshot: ConfigSnapshot, path: AllowedConfigPath, value: ConfigValue): Promise<ApiClientResult<ConfigUpdateResponse>> {
  return dashboardApi<ConfigUpdateResponse>("config", {
    method: "POST",
    body: JSON.stringify({ environment: snapshot.environment, expected_version: snapshot.version === "bootstrap" ? null : snapshot.version, patches: [{ op: "replace", path, value }] }),
  });
}

function panelErrors(states: Array<PanelState<unknown>>): string[] {
  return [...new Set(states.flatMap((state) => state.status === "error" ? [state.message] : []))];
}

function enabledVenueLabels(settings: Record<string, unknown>): string[] {
  return [
    ["Polymarket US", "venues.polymarket_us.enabled"],
    ["Polymarket International", "venues.polymarket_international.enabled"],
    ["Alpaca", "venues.alpaca.enabled"],
  ].filter(([, path]) => booleanValue(valueAtPath(settings, path))).map(([label]) => label);
}

function valueAtPath(source: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined, source);
}

function booleanValue(value: unknown): boolean { return value === true || value === "true"; }
function finiteNumber(value: unknown, fallback: number): number { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : fallback; }
function clamp(value: number, min: number, max: number): number { return Math.min(max, Math.max(min, Number(value.toFixed(4)))); }
function typedNumber(source: unknown, value: number): ConfigValue { return typeof source === "string" ? String(value) : value; }
function pathLabel(path: AllowedConfigPath): string { return path.includes("spread") ? "maximum spread" : "minimum confidence"; }
function formatConfigValue(value: ConfigValue): string { if (typeof value === "boolean") return value ? "On" : "Off"; if (Array.isArray(value)) return value.join(", "); if (value && typeof value === "object") return JSON.stringify(value); return String(value); }
function formatUsd(value: string | null | undefined): string { const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(number) : "Unavailable"; }
function formatDateTime(value: string | null | undefined): string { if (!value) return "Not recorded"; const parsed = new Date(value); return Number.isNaN(parsed.getTime()) || parsed.getTime() === 0 ? "Not recorded" : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(parsed); }
function configError(result: Extract<ApiClientResult<ConfigUpdateResponse>, { ok: false }>, prefix?: string): string { const conflict = result.status === 409 ? "Settings changed elsewhere. Reload before trying again." : result.message; return prefix ? `${prefix} ${conflict}` : conflict; }
