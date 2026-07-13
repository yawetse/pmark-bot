"use client";

import Link from "next/link";
import {
  Bell,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  RefreshCw,
  RotateCcw,
  Settings2,
} from "lucide-react";
import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type {
  OperationsSummaryView,
  ScannerCandidateView,
} from "@/components/dashboard/operations-view";
import { FALLBACK_TICK_SUMMARY, type TickSummaryView } from "@/components/dashboard/tick-summary-panel";
import {
  VenuePortfolioPanel,
  type VenuePortfolioView,
} from "@/components/dashboard/venue-portfolio-panel";
import { dashboardApi, type ApiClientResult } from "@/lib/api";
import { CONFIG_PATH_DETAILS, type AllowedConfigPath } from "@/lib/config-paths";
import { useDashboardRealtime, type TickScheduleView } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-004, REQ-UI-005, REQ-UI-008, REQ-UI-012, REQ-NOT-006, REQ-OBS-005

type ConfigValue = string | boolean | number | string[] | Record<string, unknown>;

type ConfigSnapshot = {
  environment: string;
  username?: string | null;
  config_owner?: string;
  version: string;
  settings: Record<string, unknown>;
};

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
  applies_on_next_loop?: boolean;
};

type NotificationSettingsView = {
  environment: string;
  state?: string;
  value?: string;
  recipientCount?: number;
  settings?: Record<string, unknown>;
};

type PanelState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

type SaveState =
  | { status: "idle" }
  | { status: "submitting"; label: string }
  | { status: "saved"; label: string }
  | { status: "error"; message: string };

type SummaryState =
  | { status: "loading" }
  | { status: "submitting" }
  | { status: "done" }
  | { status: "error"; message: string };

type RecommendationPatch = {
  path: AllowedConfigPath;
  currentValue: ConfigValue | null;
  nextValue: ConfigValue;
  why: string;
};

type RecommendationPlan = {
  id: "conservative" | "balanced" | "aggressive";
  title: string;
  tone: "ok" | "waiting" | "blocked";
  summary: string;
  effect: string;
  risk: string;
  patches: RecommendationPatch[];
};

type TradeUnblockRecommendation = {
  title: string;
  body: string;
  primaryBlocker: string;
  patches: RecommendationPatch[];
  notes: string[];
};

type DashboardAction = {
  title: string;
  body: string;
  href?: string;
  linkLabel?: string;
};

type LastTickFunnelAction =
  | {
      type: "patch";
      label: string;
      savedLabel: string;
      path: AllowedConfigPath;
      currentValue: ConfigValue | null;
      nextValue: ConfigValue;
      detail: string;
    }
  | {
      type: "link";
      label: string;
      href: string;
      detail: string;
    };

type LastTickFunnelStage = {
  key: string;
  label: string;
  status: string;
  tone: "ok" | "waiting" | "blocked";
  entered: number;
  passed: number;
  blocked: number;
  enteredLabel: string;
  passedLabel: string;
  blockedLabel: string;
  reason: string;
  detail: string;
  action: LastTickFunnelAction;
};

type SafetySummary = {
  label: string;
  tone: "ok" | "waiting" | "blocked";
  detail: string;
};

const CYCLE_GUIDE_STEPS = [
  {
    title: "Collect prices",
    body: "The app pulls the latest market prices, spreads, and available liquidity.",
  },
  {
    title: "Find candidates",
    body: "Markets that fit your filter settings move forward. The rest stop before any model runs.",
  },
  {
    title: "Score the trade",
    body: "The app checks direction, confidence, and risk controls before an order plan is created.",
  },
  {
    title: "Simulate or submit",
    body: "Simulation records a practice order. Live mode can submit only when every gate is clear.",
  },
  {
    title: "Monitor exits",
    body: "Open positions are checked for stop, target, and closing rules.",
  },
] as const;

const DAILY_WINDOW_MINUTES = 24 * 60;
const FALLBACK_TICK_SCHEDULE: TickScheduleView = {
  environment: "local",
  generatedAt: new Date(0).toISOString(),
  intervalSeconds: 60,
  lastTickAt: null,
  lastTickStatus: null,
  lastTickRunId: null,
  lastTickSource: "none",
  lastHeartbeatAt: null,
  heartbeatStatus: null,
  ageSeconds: null,
  nextTickAt: new Date(Date.now() + 60_000).toISOString(),
  secondsUntilNextTick: 60,
  due: false,
  source: "waiting for scheduler",
};
const RECOMMENDATION_DEFAULTS: Partial<Record<AllowedConfigPath, ConfigValue>> = {
  "scanner.polymarket.max_hours_to_resolution": "168",
  "scanner.polymarket.max_spread": "0.05",
  "scanner.alpaca.max_spread": "0.50",
  "scanner.alpaca.min_quote_liquidity": "1",
  "reasoning.polymarket.min_confidence": "0.75",
  "reasoning.alpaca.min_confidence": "0.60",
};

export function ConsumerDashboard() {
  const [configState, setConfigState] = useState<PanelState<ConfigSnapshot>>({ status: "loading" });
  const [operationsState, setOperationsState] = useState<PanelState<OperationsSummaryView>>({ status: "loading" });
  const [portfolioState, setPortfolioState] = useState<PanelState<VenuePortfolioView>>({ status: "loading" });
  const [marketDataState, setMarketDataState] = useState<PanelState<MarketDataPullView>>({ status: "loading" });
  const [tickScheduleState, setTickScheduleState] = useState<PanelState<TickScheduleView>>({ status: "loading" });
  const [notificationsState, setNotificationsState] = useState<PanelState<NotificationSettingsView>>({ status: "loading" });
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [configVersion, setConfigVersion] = useState("");
  const [tradeEmailEnabled, setTradeEmailEnabled] = useState(true);
  const [activePlanId, setActivePlanId] = useState<RecommendationPlan["id"] | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [summaryState, setSummaryState] = useState<SummaryState>({ status: "loading" });
  const [currentDailySummary, setCurrentDailySummary] = useState<TickSummaryView>(FALLBACK_TICK_SUMMARY);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    let active = true;

    void dashboardApi<ConfigSnapshot>("config/current").then((result) => {
      if (!active) {
        return;
      }
      if (result.ok) {
        commitConfigSnapshot(result.data);
      } else {
        setConfigState({ status: "error", message: result.message });
      }
    });

    void loadPanel("operations/summary", setOperationsState, () => active);
    void loadPanel("portfolio", setPortfolioState, () => active);
    void loadPanel("market-data/latest", setMarketDataState, () => active);
    void loadPanel("operations/tick-schedule", setTickScheduleState, () => active);
    void loadPanel("notifications/settings", setNotificationsState, () => active);

    void dashboardApi<TickSummaryView>(`operations/tick-summary?window_minutes=${DAILY_WINDOW_MINUTES}`).then((result) => {
      if (!active) {
        return;
      }
      if (result.ok) {
        setCurrentDailySummary(result.data);
        setSummaryState({ status: "done" });
      } else {
        setSummaryState({ status: "error", message: result.message });
      }
    });

    const portfolioInterval = window.setInterval(() => {
      void loadPanel("portfolio", setPortfolioState, () => active);
    }, 60_000);

    return () => {
      active = false;
      window.clearInterval(portfolioInterval);
    };
  }, []);

  useEffect(() => {
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  const handleRealtimeSnapshot = useCallback((snapshot: {
    operations: OperationsSummaryView;
    marketData: MarketDataPullView;
    tickSchedule: TickScheduleView;
  }) => {
    setOperationsState({ status: "ready", data: snapshot.operations });
    setMarketDataState({ status: "ready", data: snapshot.marketData });
    setTickScheduleState({ status: "ready", data: snapshot.tickSchedule });
  }, []);

  const realtime = useDashboardRealtime({ onSnapshot: handleRealtimeSnapshot });

  const operations = operationsState.status === "ready" ? operationsState.data : null;
  const marketData = marketDataState.status === "ready" ? marketDataState.data : null;
  const tickSchedule = tickScheduleState.status === "ready" ? tickScheduleState.data : null;
  const notifications = notificationsState.status === "ready" ? notificationsState.data : null;
  const liveEnabled = useMemo(() => booleanConfigValue(valueAtPath(settings, "live_enabled")), [settings]);
  const activeVenueLabels = useMemo(() => enabledVenueLabels(settings), [settings]);
  const activeVenueSummary = useMemo(
    () => (activeVenueLabels.length ? activeVenueLabels.join(", ") : "none"),
    [activeVenueLabels],
  );
  const safetySummary = useMemo(
    () =>
      dashboardSafetySummary({
        configState,
        operationsState,
        operations,
        liveEnabled,
        activeVenueLabels,
      }),
    [activeVenueLabels, configState, liveEnabled, operations, operationsState],
  );
  const actionItems = useMemo(
    () =>
      dashboardActionItems({
        configState,
        operationsState,
        notificationsState,
        operations,
        notifications,
        liveEnabled,
        activeVenueLabels,
      }),
    [activeVenueLabels, configState, liveEnabled, notifications, notificationsState, operations, operationsState],
  );
  const heroSummary = useMemo(
    () =>
      dashboardHeroSummary({
        liveEnabled,
        operations,
        activeVenueSummary,
        actionItems,
      }),
    [actionItems, activeVenueSummary, liveEnabled, operations],
  );
  const countdownSeconds = useMemo(() => secondsUntilTick(tickSchedule, nowMs), [tickSchedule, nowMs]);
  const countdownDue = countdownSeconds !== null && countdownSeconds <= 0;
  const timelineSteps = useMemo(
    () => tickTimelineSteps(operations, marketData),
    [operations, marketData],
  );
  const funnelStages = useMemo(
    () => lastTickFunnelStages(settings, operations, marketData, liveEnabled, activeVenueLabels),
    [activeVenueLabels, liveEnabled, marketData, operations, settings],
  );
  const funnelSummary = useMemo(() => lastTickFunnelSummary(funnelStages), [funnelStages]);
  const lastTick = useMemo(
    () => lastTickResult(operations, currentDailySummary),
    [operations, currentDailySummary],
  );
  const plans = useMemo(
    () => recommendationPlans(settings, currentDailySummary, operations),
    [settings, currentDailySummary, operations],
  );
  const tradeUnblock = useMemo(
    () => tradeUnblockRecommendation(settings, currentDailySummary, operations),
    [settings, currentDailySummary, operations],
  );
  const inferredPlanId = useMemo(() => inferredRecommendationPlanId(settings), [settings]);
  const activePlan = plans.find((plan) => plan.id === (activePlanId ?? inferredPlanId)) ?? plans[1];
  const generatedAt = formatDateTime(currentDailySummary.generatedAt);
  const canEditConfig = configState.status === "ready" && saveState.status !== "submitting";

  function commitConfigSnapshot(snapshot: ConfigSnapshot) {
    setConfigState({ status: "ready", data: snapshot });
    setSettings(snapshot.settings);
    setConfigVersion(snapshot.version);
    setTradeEmailEnabled(valueAtPath(snapshot.settings, "notifications.email_on_trade_placed") !== false);
  }

  async function refreshConfigSnapshot(): Promise<ConfigSnapshot | null> {
    const result = await dashboardApi<ConfigSnapshot>("config/current");
    if (!result.ok) {
      setConfigState({ status: "error", message: result.message });
      return null;
    }
    commitConfigSnapshot(result.data);
    return result.data;
  }

  async function refreshDailySummary() {
    setSummaryState({ status: "submitting" });
    const result = await dashboardApi<TickSummaryView>("operations/tick-summary", {
      method: "POST",
      body: JSON.stringify({ window_minutes: DAILY_WINDOW_MINUTES }),
    });
    if (!result.ok) {
      setSummaryState({ status: "error", message: result.message });
      return;
    }
    setCurrentDailySummary(result.data);
    setSummaryState({ status: "done" });
  }

  async function applyPlan(plan: RecommendationPlan) {
    setActivePlanId(plan.id);
    await saveConfigPatches(
      plan.patches.map((patch) => ({ path: patch.path, value: patch.nextValue })),
      `${plan.title} applied`,
    );
  }

  async function applyTradeUnblockRecommendation(recommendation: TradeUnblockRecommendation) {
    await saveConfigPatches(
      recommendation.patches.map((patch) => ({ path: patch.path, value: patch.nextValue })),
      "Candidate settings saved",
    );
  }

  async function resetDefaults() {
    const patches = Object.entries(RECOMMENDATION_DEFAULTS).map(([path, value]) => ({
      path: path as AllowedConfigPath,
      value: value as ConfigValue,
    }));
    await saveConfigPatches(patches, "Defaults restored");
  }

  async function updateTradeEmail(nextValue: boolean) {
    const priorValue = tradeEmailEnabled;
    setTradeEmailEnabled(nextValue);
    const saved = await saveConfigPatches(
      [{ path: "notifications.email_on_trade_placed", value: nextValue }],
      nextValue ? "Trade email enabled" : "Trade email disabled",
    );
    if (!saved) {
      setTradeEmailEnabled(priorValue);
    }
  }

  async function saveConfigPatches(
    patches: Array<{ path: AllowedConfigPath; value: ConfigValue }>,
    savedLabel: string,
  ): Promise<boolean> {
    setSaveState({ status: "submitting", label: savedLabel });
    const latestSnapshot = await refreshConfigSnapshot();
    if (!latestSnapshot) {
      setSaveState({ status: "error", message: "Could not load the latest config before saving." });
      return false;
    }

    const firstAttempt = await submitConfigPatches(latestSnapshot, patches);
    if (!firstAttempt.result.ok && firstAttempt.result.status === 409) {
      const conflictSnapshot = await refreshConfigSnapshot();
      if (!conflictSnapshot) {
        setSaveState({ status: "error", message: "Settings changed, and the latest version could not be loaded." });
        return false;
      }
      const retry = await submitConfigPatches(conflictSnapshot, patches);
      return finalizeConfigSave(retry, patches, savedLabel, true);
    }
    return finalizeConfigSave(firstAttempt, patches, savedLabel, false);
  }

  async function submitConfigPatches(
    snapshot: ConfigSnapshot,
    patches: Array<{ path: AllowedConfigPath; value: ConfigValue }>,
  ): Promise<{
    result: ApiClientResult<ConfigUpdateResponse>;
    requestedVersion: string | null;
  }> {
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: snapshot.environment,
        expected_version: expectedVersionFromSnapshot(snapshot) || null,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
      }),
    });
    return { result, requestedVersion: null };
  }

  async function finalizeConfigSave(
    attempt: {
      result: ApiClientResult<ConfigUpdateResponse>;
      requestedVersion: string | null;
    },
    patches: Array<{ path: AllowedConfigPath; value: ConfigValue }>,
    savedLabel: string,
    retried: boolean,
  ): Promise<boolean> {
    if (!attempt.result.ok) {
      setSaveState({
        status: "error",
        message:
          retried && attempt.result.status === 409
            ? "Settings changed while saving. I refreshed them and retried, but they changed again. Try Apply once more."
            : readableConfigError(attempt.result.message),
      });
      return false;
    }

    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (refreshed.ok) {
      commitConfigSnapshot(refreshed.data);
    } else {
      setSettings((current) =>
        patches.reduce(
          (nextSettings, patch) => valueAtUpdatedPath(nextSettings, patch.path, patch.value),
          current,
        ),
      );
      setConfigVersion(attempt.result.data.new_version ?? attempt.requestedVersion ?? configVersion);
    }
    setSaveState({ status: "saved", label: savedLabel });
    return true;
  }

  async function applyFunnelAction(stage: LastTickFunnelStage) {
    if (stage.action.type !== "patch") {
      return;
    }
    await saveConfigPatches(
      [{ path: stage.action.path, value: stage.action.nextValue }],
      stage.action.savedLabel,
    );
  }

  return (
    <section className="consumer-dashboard" aria-labelledby="consumer-dashboard-title">
      <div className="consumer-hero">
        <div>
          <p className="section-label">Dashboard</p>
          <h1 id="consumer-dashboard-title">{lastTick.title}</h1>
          <div className="summary-copy">
            <p>{lastTick.body}</p>
            <p>{heroSummary}</p>
          </div>
          <div className="guide-actions" aria-label="Primary dashboard controls">
            <Link className="button primary" href="/dashboard/operations">
              <RefreshCw aria-hidden="true" size={16} />
              Run
            </Link>
            <Link className="button subtle" href="/dashboard/config">
              <Settings2 aria-hidden="true" size={16} />
              Settings
            </Link>
            <Link className="button subtle" href="/dashboard/system">
              <CheckCircle2 aria-hidden="true" size={16} />
              Verify system
            </Link>
          </div>
        </div>
        <div className={`consumer-status-badge ${lastTick.tone}`}>
          {lastTick.tone === "blocked" ? <CircleAlert aria-hidden="true" size={20} /> : <CheckCircle2 aria-hidden="true" size={20} />}
          <span>{lastTick.label}</span>
        </div>
      </div>

      <div className="consumer-tick-strip" aria-label="Tick timing">
        <TickTimingMetric
          label="Last tick"
          value={formatDateTime(tickSchedule?.lastTickAt)}
          detail={tickSchedule?.lastTickRunId ? `Run ${tickSchedule.lastTickRunId}` : tickSourceLabel(tickSchedule)}
        />
        <TickTimingMetric
          label="Last status"
          value={tickSchedule?.lastTickStatus ?? "not recorded"}
          detail={tickSchedule?.lastTickSource === "worker_heartbeat" ? "Using worker heartbeat until a tick is recorded." : "Latest recorded tick result."}
        />
        <TickTimingMetric
          label="Next tick"
          value={formatDateTime(tickSchedule?.nextTickAt)}
          detail={`Every ${tickSchedule?.intervalSeconds ?? FALLBACK_TICK_SCHEDULE.intervalSeconds}s`}
        />
        <TickTimingMetric
          label="Countdown"
          value={formatCountdown(countdownSeconds)}
          detail={countdownDue || tickSchedule?.due ? "Due now" : realtime.message}
          tone={realtime.status === "connected" ? "ok" : realtime.status === "offline" ? "blocked" : "waiting"}
        />
      </div>

      <section className="consumer-panel span-3 tick-funnel-panel" aria-labelledby="tick-funnel-title">
        <div className="consumer-panel-heading tick-funnel-heading">
          <div>
            <p className="section-label">Last tick funnel</p>
            <h2 id="tick-funnel-title">{lastTick.tone === "ok" ? "How the trade passed" : "Why no trade happened"}</h2>
            <p>{funnelSummary}</p>
          </div>
          <span className={`status ${lastTick.tone}`}>{lastTick.status}</span>
        </div>
        <LastTickFunnel
          canEditConfig={canEditConfig}
          onApplyStageAction={applyFunnelAction}
          saveState={saveState}
          stages={funnelStages}
        />
        {saveState.status === "submitting" ? (
          <p className="status-message waiting">Saving {saveState.label.toLowerCase()}.</p>
        ) : null}
        {saveState.status === "saved" ? (
          <p className="status-message ok">{saveState.label}. Changes apply on the next loop.</p>
        ) : null}
        {saveState.status === "error" ? (
          <p className="status-message blocked">{saveState.message}</p>
        ) : null}
      </section>

      <section className="consumer-cycle-guide" aria-labelledby="cycle-guide-title">
        <div className="cycle-guide-heading">
          <div>
            <p className="section-label">How it works</p>
            <h2 id="cycle-guide-title">One trading cycle, five checks</h2>
          </div>
          <p>
            A cycle is one full pass through market data, trade scoring, order handling,
            and exit monitoring.
          </p>
        </div>
        <div className="cycle-guide-list">
          {CYCLE_GUIDE_STEPS.map((step, index) => (
            <article className="cycle-guide-card" key={step.title}>
              <span>{index + 1}</span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.body}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <div className="consumer-grid">
        <section className="consumer-panel" aria-labelledby="dashboard-safety-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Safety</p>
              <h2 id="dashboard-safety-title">Current mode</h2>
            </div>
            <span className={`status ${safetySummary.tone}`}>{safetySummary.label}</span>
          </div>
          <div className="consumer-metric-list">
            <Metric
              detail={liveEnabled ? "The setting allows live orders if every gate is clear." : "Orders are recorded as simulations only."}
              label="Trading mode"
              value={liveEnabled ? "Live setting on" : "Simulation only"}
            />
            <Metric
              detail={operations?.killSwitch === "active" ? "Emergency stop is blocking new live orders." : "Emergency stop is not blocking the cycle."}
              label="Emergency stop"
              value={operations?.killSwitch ?? "loading"}
            />
            <Metric
              detail={activeVenueSummary === "none" ? "No venue can receive orders." : "These venues can be checked for trades."}
              label="Active venues"
              value={activeVenueSummary}
            />
          </div>
          <p className="panel-note">{safetySummary.detail}</p>
        </section>

        <section className="consumer-panel" aria-labelledby="dashboard-actions-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Action needed</p>
              <h2 id="dashboard-actions-title">Next operator step</h2>
            </div>
            <span className={`status ${actionItems.length ? "waiting" : "ok"}`}>
              {actionItems.length ? `${actionItems.length} item${actionItems.length === 1 ? "" : "s"}` : "clear"}
            </span>
          </div>
          <ol className="action-list">
            {actionItems.map((action) => (
              <li key={action.title}>
                <strong>{action.title}</strong>
                <span>{action.body}</span>
                {action.href ? (
                  <Link className="inline-link" href={action.href}>
                    {action.linkLabel}
                  </Link>
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        <section className="consumer-panel" aria-labelledby="dashboard-controls-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Primary controls</p>
              <h2 id="dashboard-controls-title">Common actions</h2>
            </div>
            <Settings2 aria-hidden="true" size={20} />
          </div>
          <div className="control-list">
            <DashboardControlLink
              body="Run a simulation cycle, review orders, and use the emergency stop."
              href="/dashboard/operations"
              title="Run or review"
            />
            <DashboardControlLink
              body="Change venues, live mode, notifications, market filters, and model limits."
              href="/dashboard/config"
              title="Change settings"
            />
            <DashboardControlLink
              body="Check credentials, scheduler heartbeat, notifications, and account readiness."
              href="/dashboard/system"
              title="Check readiness"
            />
          </div>
        </section>

        {portfolioState.status === "loading" ? (
          <section className="consumer-panel span-3" aria-labelledby="portfolio-loading-title">
            <div className="consumer-panel-heading">
              <div>
                <p className="section-label">Actual portfolio</p>
                <h2 id="portfolio-loading-title">Loading venue-confirmed performance</h2>
              </div>
            </div>
            <PanelLoadingRows />
          </section>
        ) : portfolioState.status === "error" ? (
          <section className="consumer-panel span-3" aria-labelledby="portfolio-error-title">
            <div className="consumer-panel-heading">
              <div>
                <p className="section-label">Actual portfolio</p>
                <h2 id="portfolio-error-title">Portfolio unavailable</h2>
              </div>
            </div>
            <p className="status-message blocked">{portfolioState.message}</p>
          </section>
        ) : (
          <VenuePortfolioPanel portfolio={portfolioState.data} />
        )}

        <section className="consumer-panel span-3" aria-labelledby="last-tick-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Last tick</p>
              <h2 id="last-tick-title">Result</h2>
            </div>
            <span className={`status ${lastTick.tone}`}>{lastTick.status}</span>
          </div>
          {operationsState.status === "loading" ? (
            <PanelLoadingRows compact />
          ) : operationsState.status === "error" ? (
            <p className="status-message blocked">{operationsState.message}</p>
          ) : (
            <>
              <div className="last-tick-result">
                <strong>{lastTick.headline}</strong>
                <p>{lastTick.detail}</p>
              </div>
              <div className="consumer-metric-list">
                <Metric label="Passed filters" value={String(operationsState.data.scanner?.acceptedCount ?? 0)} />
                <Metric label="Real orders" value={String(operationsState.data.execution?.submittedCount ?? 0)} />
                <Metric label="Practice orders" value={String(operationsState.data.execution?.simulatedCount ?? 0)} />
              </div>
            </>
          )}
        </section>

        <section className="consumer-panel span-3" aria-labelledby="timeline-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Latest cycle</p>
              <h2 id="timeline-title">What happened last time</h2>
            </div>
            <span className="status idle">{operations?.pipelineRuns[0]?.status ?? "loading"}</span>
          </div>
          <div className="consumer-timeline">
            {timelineSteps.map((step, index) => (
              <article className={`timeline-step ${step.tone}`} key={step.key}>
                <span className="timeline-index">{index + 1}</span>
                <div>
                  <strong>{step.label}</strong>
                  <span>{step.message}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="consumer-panel span-2" aria-labelledby="daily-summary-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Daily summary</p>
              <h2 id="daily-summary-title">What is happening</h2>
            </div>
            <button
              className="icon-button"
              disabled={summaryState.status === "submitting"}
              onClick={refreshDailySummary}
              title="Run summary now"
              type="button"
            >
              <RefreshCw aria-hidden="true" size={17} />
            </button>
          </div>
          {summaryState.status === "loading" ? (
            <PanelLoadingRows />
          ) : (
            <>
              <div className="summary-copy">
                {markdownLines(currentDailySummary.summaryMarkdown).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
              {currentDailySummary.warnings?.length ? (
                <div className="summary-warnings">
                  {currentDailySummary.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                </div>
              ) : null}
              <div className="summary-footer">
                <span>Generated {generatedAt}</span>
                <span>{currentDailySummary.model ?? "model unavailable"}</span>
              </div>
            </>
          )}
          {summaryState.status === "submitting" ? (
            <p className="status-message waiting">Generating summary.</p>
          ) : null}
          {summaryState.status === "error" ? (
            <p className="status-message blocked">{summaryState.message}</p>
          ) : null}
        </section>

        <section className="consumer-panel notification-panel" aria-labelledby="notification-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Notifications</p>
              <h2 id="notification-title">Trade emails</h2>
            </div>
            <Bell aria-hidden="true" size={20} />
          </div>
          {configState.status === "loading" ? (
            <PanelLoadingRows compact />
          ) : configState.status === "error" ? (
            <p className="status-message blocked">{configState.message}</p>
          ) : (
            <>
              <label className="consumer-toggle">
                <input
                  checked={tradeEmailEnabled}
                  disabled={!canEditConfig}
                  onChange={(event) => void updateTradeEmail(event.target.checked)}
                  type="checkbox"
                />
                <span>Email me when a real trade is placed</span>
              </label>
              <p className="panel-note">
                {notificationsState.status === "loading"
                  ? "Loading recipients."
                  : notificationsState.status === "error"
                    ? notificationsState.message
                    : notifications?.recipientCount
                      ? `${notifications.recipientCount} recipient configured.`
                      : "Add a recipient in Settings before emails can send."}
              </p>
            </>
          )}
        </section>

        <section className="consumer-panel span-3" aria-labelledby="recommendation-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Recommendations</p>
              <h2 id="recommendation-title">Change the settings</h2>
            </div>
            <Settings2 aria-hidden="true" size={20} />
          </div>
          {configState.status === "loading" ? (
            <PanelLoadingRows />
          ) : configState.status === "error" ? (
            <p className="status-message blocked">{configState.message}</p>
          ) : (
            <>
              {tradeUnblock ? (
                <div className="trade-unblock-card">
                  <div className="trade-unblock-heading">
                    <div>
                      <span className="status blocked">{tradeUnblock.primaryBlocker}</span>
                      <strong>{tradeUnblock.title}</strong>
                      <p>{tradeUnblock.body}</p>
                    </div>
                    <CircleAlert aria-hidden="true" size={22} />
                  </div>
                  {tradeUnblock.patches.length ? (
                    <div className="trade-unblock-patches" aria-label="Suggested setting changes">
                      {tradeUnblock.patches.map((patch) => (
                        <div key={`unblock-${patch.path}`}>
                          <span>{CONFIG_PATH_DETAILS[patch.path].label}</span>
                          <strong>
                            {formatConfigValue(patch.currentValue)} to {formatConfigValue(patch.nextValue)}
                          </strong>
                          <small>{patch.why}</small>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {tradeUnblock.notes.length ? (
                    <ul className="trade-unblock-notes">
                      {tradeUnblock.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  ) : null}
                  <div className="recommendation-actions">
                    <button
                      className="button primary recommendation-apply-button"
                      disabled={!canEditConfig || !tradeUnblock.patches.length}
                      type="button"
                      onClick={() => void applyTradeUnblockRecommendation(tradeUnblock)}
                    >
                      {saveState.status === "submitting" && saveState.label === "Candidate settings saved"
                        ? "Applying"
                        : "Allow more candidates"}
                    </button>
                    <Link className="button subtle" href="/dashboard/scenario">
                      Review what-if
                    </Link>
                  </div>
                </div>
              ) : null}

              <div className="recommendation-options">
                {plans.map((plan) => {
                  const selected = plan.id === activePlan.id;
                  return (
                    <article
                      aria-current={selected ? "true" : undefined}
                      className={`recommendation-option ${plan.id}`}
                      data-active={selected ? "true" : undefined}
                      key={plan.id}
                    >
                      <div>
                        <div className="recommendation-option-header">
                          <span className={`status ${plan.tone}`}>{plan.id}</span>
                          {selected ? (
                            <span className="selected-plan-badge">
                              <CheckCircle2 aria-hidden="true" size={14} />
                              Selected
                            </span>
                          ) : null}
                        </div>
                        <h3>{plan.title}</h3>
                        <p>{plan.summary}</p>
                        <dl className="recommendation-impact">
                          <div>
                            <dt>Effect</dt>
                            <dd>{plan.effect}</dd>
                          </div>
                          <div>
                            <dt>Tradeoff</dt>
                            <dd>{plan.risk}</dd>
                          </div>
                        </dl>
                      </div>
                      <div className="recommendation-actions">
                        <button
                          aria-pressed={selected}
                          className="button subtle recommendation-view-button"
                          type="button"
                          onClick={() => setActivePlanId(plan.id)}
                        >
                          {selected ? (
                            <CheckCircle2 aria-hidden="true" size={16} />
                          ) : (
                            <ChevronDown aria-hidden="true" size={16} />
                          )}
                          {selected ? "Viewing" : "View detail"}
                        </button>
                        <button
                          aria-label={`Apply ${plan.title} settings`}
                          className="button primary recommendation-apply-button"
                          disabled={!canEditConfig}
                          type="button"
                          onClick={() => void applyPlan(plan)}
                        >
                          {saveState.status === "submitting" && activePlan.id === plan.id ? "Applying" : "Apply"}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>

              <div className="recommendation-detail">
                <div className="recommendation-detail-heading">
                  <div>
                    <strong>{activePlan.title} preview</strong>
                    <p>
                      These settings save to runtime config and apply on the next loop.
                    </p>
                  </div>
                  <button className="button subtle" disabled={!canEditConfig} type="button" onClick={() => void resetDefaults()}>
                    <RotateCcw aria-hidden="true" size={16} />
                    Reset defaults
                  </button>
                </div>
                <div className="recommendation-table">
                  <div className="recommendation-row header">
                    <span>Setting</span>
                    <span>Current</span>
                    <span>New</span>
                    <span>Why</span>
                  </div>
                  {activePlan.patches.map((patch) => (
                    <div className="recommendation-row" key={`${activePlan.id}-${patch.path}`}>
                      <span>{CONFIG_PATH_DETAILS[patch.path].label}</span>
                      <span>{formatConfigValue(patch.currentValue)}</span>
                      <span>{formatConfigValue(patch.nextValue)}</span>
                      <span>{patch.why}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
          {saveState.status === "submitting" ? (
            <p className="status-message waiting">Saving {saveState.label.toLowerCase()}.</p>
          ) : null}
          {saveState.status === "saved" ? (
            <p className="status-message ok">{saveState.label}. Changes apply on the next loop.</p>
          ) : null}
          {saveState.status === "error" ? (
            <p className="status-message blocked">{saveState.message}</p>
          ) : null}
          {configVersion ? <p className="panel-note">Config version {configVersion}</p> : null}
        </section>
      </div>
    </section>
  );
}

function DashboardControlLink({
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

function LastTickFunnel({
  stages,
  canEditConfig,
  saveState,
  onApplyStageAction,
}: {
  stages: LastTickFunnelStage[];
  canEditConfig: boolean;
  saveState: SaveState;
  onApplyStageAction: (stage: LastTickFunnelStage) => void;
}) {
  const maxCount = Math.max(
    1,
    ...stages.map((stage) => Math.max(stage.entered, stage.passed, stage.blocked)),
  );

  return (
    <div className="tick-funnel-grid" aria-label="Last tick gate counts">
      {stages.map((stage) => {
        const applying =
          saveState.status === "submitting" &&
          stage.action.type === "patch" &&
          saveState.label === stage.action.savedLabel;
        const style = {
          "--pass-width": funnelWidth(stage.passed, maxCount),
          "--blocked-width": funnelWidth(stage.blocked, maxCount),
        } as CSSProperties;

        return (
          <article className={`tick-funnel-stage ${stage.tone}`} key={stage.key} style={style}>
            <div className="funnel-stage-heading">
              <div>
                <span>{stage.enteredLabel}</span>
                <strong>{stage.label}</strong>
              </div>
              <span className={`status ${stage.tone}`}>{stage.status}</span>
            </div>
            <div className="funnel-flow-track" aria-hidden="true">
              <span className="funnel-flow-pass" />
              <span className="funnel-flow-blocked" />
            </div>
            <dl className="funnel-stage-counts">
              <div>
                <dt>In</dt>
                <dd>{formatWhole(stage.entered)}</dd>
              </div>
              <div>
                <dt>{stage.passedLabel}</dt>
                <dd>{formatWhole(stage.passed)}</dd>
              </div>
              <div>
                <dt>{stage.blockedLabel}</dt>
                <dd>{formatWhole(stage.blocked)}</dd>
              </div>
            </dl>
            <div className="funnel-stage-copy">
              <strong>{stage.reason}</strong>
              <p>{stage.detail}</p>
            </div>
            <div className="funnel-stage-action">
              {stage.action.type === "patch" ? (
                <>
                  <div className="funnel-setting-change">
                    <span>{CONFIG_PATH_DETAILS[stage.action.path].label}</span>
                    <strong>
                      {formatConfigValue(stage.action.currentValue)} to {formatConfigValue(stage.action.nextValue)}
                    </strong>
                  </div>
                  <button
                    className="button primary funnel-action-button"
                    disabled={!canEditConfig || applying}
                    onClick={() => onApplyStageAction(stage)}
                    type="button"
                  >
                    {applying ? "Applying" : stage.action.label}
                  </button>
                </>
              ) : (
                <>
                  <p>{stage.action.detail}</p>
                  <Link className="button subtle funnel-action-button" href={stage.action.href}>
                    {stage.action.label}
                  </Link>
                </>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function dashboardHeroSummary({
  liveEnabled,
  operations,
  activeVenueSummary,
  actionItems,
}: {
  liveEnabled: boolean;
  operations: OperationsSummaryView | null;
  activeVenueSummary: string;
  actionItems: DashboardAction[];
}): string {
  const mode = liveEnabled ? "live setting on" : "simulation only";
  const killSwitch = friendlyEmergencyStopStatus(operations?.killSwitch);
  const nextAction = actionItems[0]?.title.toLowerCase() ?? "monitor the next tick";
  return `Current mode: ${mode}. Emergency stop: ${killSwitch}. Active venues: ${activeVenueSummary}. Next step: ${nextAction}.`;
}

function dashboardSafetySummary({
  configState,
  operationsState,
  operations,
  liveEnabled,
  activeVenueLabels,
}: {
  configState: PanelState<ConfigSnapshot>;
  operationsState: PanelState<OperationsSummaryView>;
  operations: OperationsSummaryView | null;
  liveEnabled: boolean;
  activeVenueLabels: string[];
}): SafetySummary {
  if (configState.status === "loading" || operationsState.status === "loading") {
    return {
      label: "loading",
      tone: "waiting",
      detail: "Loading config and operations gates before showing the current run posture.",
    };
  }
  if (configState.status === "error" || operationsState.status === "error") {
    return {
      label: "blocked",
      tone: "blocked",
      detail: "One or more dashboard APIs could not load. Check backend health before changing run settings.",
    };
  }
  if (operations?.killSwitch === "active") {
    return {
      label: "stopped",
      tone: "blocked",
      detail: "The emergency stop is active. Open Run before any cycle or live-mode change.",
    };
  }
  if (liveEnabled && activeVenueLabels.length === 0) {
    return {
      label: "gated",
      tone: "blocked",
      detail: "Live mode is enabled, but no venue is active. Enable a venue only after account and risk checks are ready.",
    };
  }
  if (liveEnabled) {
    return {
      label: "live setting on",
      tone: "waiting",
      detail: "Live mode is on. Keep orders, risk controls, notifications, and the emergency stop visible while monitoring.",
    };
  }
  return {
    label: "simulation only",
    tone: "ok",
    detail: "Live order submission is off. Use this state for market filters, model checks, and settings changes.",
  };
}

function dashboardActionItems({
  configState,
  operationsState,
  notificationsState,
  operations,
  notifications,
  liveEnabled,
  activeVenueLabels,
}: {
  configState: PanelState<ConfigSnapshot>;
  operationsState: PanelState<OperationsSummaryView>;
  notificationsState: PanelState<NotificationSettingsView>;
  operations: OperationsSummaryView | null;
  notifications: NotificationSettingsView | null;
  liveEnabled: boolean;
  activeVenueLabels: string[];
}): DashboardAction[] {
  const actions: DashboardAction[] = [];

  if (configState.status === "error") {
    actions.push({
      title: "Recover config status",
      body: configState.message,
      href: "/dashboard/system",
      linkLabel: "Open health",
    });
  }
  if (operationsState.status === "error") {
    actions.push({
      title: "Recover operations status",
      body: operationsState.message,
      href: "/dashboard/operations",
      linkLabel: "Open run page",
    });
  }
  if (operations?.killSwitch === "active") {
    actions.push({
      title: "Review emergency stop",
      body: "The emergency control is active. Clear or keep it intentionally before changing run settings.",
      href: "/dashboard/operations",
      linkLabel: "Open run page",
    });
  }
  if (activeVenueLabels.length === 0) {
    actions.push({
      title: "Choose an active venue",
      body: "No venue is enabled for market checks or trading. Keep live mode off until the target account is ready.",
      href: "/dashboard/config",
      linkLabel: "Open settings",
    });
  }
  if (operations && operations.manualReviewState !== "clear") {
    actions.push({
      title: "Check approval queue",
      body: `The approval queue is ${operations.manualReviewState}. Confirm it before running the next cycle.`,
      href: "/dashboard/operations",
      linkLabel: "Open run page",
    });
  }
  if ((operations?.openOrders ?? 0) > 0) {
    actions.push({
      title: "Review open orders",
      body: `${operations?.openOrders ?? 0} order${operations?.openOrders === 1 ? "" : "s"} still need a terminal state.`,
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }
  if (notificationsState.status === "error" || (notificationsState.status === "ready" && !notificationsReady(notifications))) {
    actions.push({
      title: "Confirm notifications",
      body:
        notificationsState.status === "error"
          ? notificationsState.message
          : "Trade alerts need at least one recipient before live operation.",
      href: "/dashboard/config",
      linkLabel: "Open settings",
    });
  }
  if (actions.length === 0 && !liveEnabled) {
    actions.push({
      title: "Stay in simulation or prepare signoff",
      body: "The current mode is safe for simulation checks. Use Run for the next cycle or Settings for a planned change.",
      href: "/dashboard/operations",
      linkLabel: "Open run page",
    });
  }
  if (actions.length === 0) {
    actions.push({
      title: "Monitor the next tick",
      body: "No immediate blocker is visible. Watch the next scheduled loop and review orders after it completes.",
      href: "/dashboard/operations",
      linkLabel: "Open run page",
    });
  }

  return actions.slice(0, 3);
}

function enabledVenueLabels(settings: Record<string, unknown>): string[] {
  return [
    ["Polymarket US", "venues.polymarket_us.enabled"],
    ["Polymarket International", "venues.polymarket_international.enabled"],
    ["Alpaca", "venues.alpaca.enabled"],
  ]
    .filter(([, path]) => booleanConfigValue(valueAtPath(settings, path)))
    .map(([label]) => label);
}

function booleanConfigValue(value: unknown): boolean {
  return value === true || value === "true";
}

function notificationsReady(notifications: NotificationSettingsView | null): boolean {
  if (!notifications) {
    return false;
  }
  if (notifications.state === "blocked") {
    return false;
  }
  return (notifications.recipientCount ?? 0) > 0;
}

async function loadPanel<T>(
  path: string,
  setState: (state: PanelState<T>) => void,
  isActive: () => boolean,
) {
  const result = await dashboardApi<T>(path);
  if (!isActive()) {
    return;
  }
  setState(result.ok ? { status: "ready", data: result.data } : { status: "error", message: result.message });
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="consumer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function TickTimingMetric({
  label,
  value,
  detail,
  tone = "idle",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "ok" | "waiting" | "blocked" | "idle";
}) {
  return (
    <div className={`tick-timing-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function PanelLoadingRows({ compact = false }: { compact?: boolean }) {
  return (
    <div className="loading-panel" aria-busy="true" aria-label="loading">
      <div className="loading-row-list">
        <div className="loading-row">
          <span className="loading-dot" />
          <span className="loading-line" />
        </div>
        <div className="loading-row">
          <span className="loading-dot" />
          <span className="loading-line medium" />
        </div>
        {compact ? null : (
          <div className="loading-row">
            <span className="loading-dot" />
            <span className="loading-line short" />
          </div>
        )}
      </div>
    </div>
  );
}

function tickTimelineSteps(
  operations: OperationsSummaryView | null,
  marketData: MarketDataPullView | null,
) {
  const latestRun = operations?.pipelineRuns[0];
  const stepByKey = new Map(
    (latestRun?.steps ?? []).map((step) => [step.key, step]),
  );
  return [
    {
      key: "data_fetch",
      label: "Collect prices",
      status: stepByKey.get("data_fetch")?.status ?? marketData?.status ?? "loading",
      message: stepByKey.get("data_fetch")?.message ?? (
        marketData ? `${marketData.candidateCount ?? 0} candidates loaded` : "Loading market data."
      ),
    },
    {
      key: "scanner",
      label: "Find candidates",
      status: stepByKey.get("scanner")?.status ?? operations?.scanner?.status ?? "loading",
      message:
        stepByKey.get("scanner")?.message ??
        (operations
          ? `${operations.scanner?.acceptedCount ?? 0} accepted, ${operations.scanner?.rejectedCount ?? 0} rejected`
          : "Loading market filter results."),
    },
    {
      key: "brain",
      label: "Score trade",
      status: stepByKey.get("brain")?.status ?? operations?.reasoning?.status ?? "loading",
      message:
        stepByKey.get("brain")?.message ??
        (operations
          ? `${operations.reasoning?.scoredCount ?? 0} scored, ${operations.reasoning?.failedCount ?? 0} failed`
          : "Loading model scoring results."),
    },
    {
      key: "execution",
      label: "Handle order",
      status: stepByKey.get("execution")?.status ?? operations?.execution?.status ?? "loading",
      message:
        stepByKey.get("execution")?.message ??
        (operations
          ? `${operations.execution?.submittedCount ?? 0} submitted, ${operations.execution?.simulatedCount ?? 0} simulated`
          : "Loading execution results."),
    },
    {
      key: "exit",
      label: "Monitor exit",
      status: stepByKey.get("exit")?.status ?? operations?.exit?.status ?? "loading",
      message:
        stepByKey.get("exit")?.message ??
        (operations
          ? `${operations.exit?.triggeredCount ?? 0} exit checks triggered`
          : "Loading exit results."),
    },
  ].map((step) => ({ ...step, tone: statusTone(step.status) }));
}

function lastTickFunnelStages(
  settings: Record<string, unknown>,
  operations: OperationsSummaryView | null,
  marketData: MarketDataPullView | null,
  liveEnabled: boolean,
  activeVenueLabels: string[],
): LastTickFunnelStage[] {
  const marketCandidates = marketDataCandidateCount(marketData);
  const venueCandidateBreakdown = marketDataVenueBreakdown(marketData);
  const scanner = operations?.scanner;
  const reasoning = operations?.reasoning;
  const strategyConsensus = operations?.strategyConsensus;
  const execution = operations?.execution;

  const scannerEntered = Math.max(scanner?.candidateCount ?? 0, marketCandidates);
  const scannerPassed = scanner?.acceptedCount ?? 0;
  const scannerBlocked = Math.max(scanner?.rejectedCount ?? 0, scannerEntered - scannerPassed);
  const scannerReason = mostCommonReason(scanner?.candidates.map((candidate) => candidate.refusalReason));

  const reasoningEntered = Math.max(reasoning?.promptCount ?? 0, scannerPassed);
  const reasoningPassed = reasoning?.scoredCount ?? 0;
  const reasoningBlocked = Math.max(
    (reasoning?.skippedCount ?? 0) + (reasoning?.failedCount ?? 0),
    reasoningEntered - reasoningPassed,
  );
  const reasoningReason = mostCommonReason(reasoning?.outputs.map((output) => output.refusalReason));

  const consensusEntered = Math.max(strategyConsensus?.voteCount ?? 0, reasoningPassed);
  const consensusPassed = strategyConsensus?.approvedCount ?? 0;
  const consensusBlocked = Math.max(strategyConsensus?.refusedCount ?? 0, consensusEntered - consensusPassed);
  const consensusReason = mostCommonReason([
    ...(strategyConsensus?.votes.map((vote) => vote.refusalReason) ?? []),
    ...(strategyConsensus?.outputs.map((output) => output.refusalReason) ?? []),
  ]);

  const orderEntered = Math.max(execution?.intentCount ?? 0, consensusPassed);
  const orderPassed = (execution?.submittedCount ?? 0) + (execution?.simulatedCount ?? 0);
  const orderBlocked = Math.max(execution?.refusedCount ?? 0, orderEntered - orderPassed);
  const orderReason = mostCommonReason(execution?.intents.map((intent) => intent.refusalReason));

  const submittedCount = execution?.submittedCount ?? 0;
  const simulatedCount = execution?.simulatedCount ?? 0;
  const liveOrderEntered = Math.max(submittedCount + simulatedCount + orderBlocked, orderPassed, orderEntered);
  const liveOrderBlocked = Math.max(orderBlocked + simulatedCount, liveOrderEntered - submittedCount);

  return [
    buildFunnelStage({
      key: "market-data",
      label: "Market data",
      status: marketData?.status ?? (operations ? "idle" : "loading"),
      entered: marketCandidates,
      passed: marketCandidates,
      blocked: 0,
      enteredLabel: "priced records",
      passedLabel: "Pulled",
      blockedLabel: "Not pulled",
      reason:
        marketCandidates > 0
          ? `${formatWhole(marketCandidates)} priced candidate${marketCandidates === 1 ? "" : "s"} entered the tick${venueCandidateBreakdown ? `: ${venueCandidateBreakdown}` : ""}.`
          : "No priced candidate reached the scanner.",
      detail: marketData?.message ?? "Waiting for the latest market data pull.",
      action:
        activeVenueLabels.length === 0
          ? linkFunnelAction(
              "/dashboard/config",
              "Choose venue",
              "No active venue can provide market records until one is enabled.",
            )
          : marketCandidates === 0
            ? linkFunnelAction(
                "/dashboard/operations",
                "Run cycle",
                "Run a manual cycle to pull fresh market records.",
              )
            : patchFunnelAction(
                settings,
                "scanner.polymarket.market_data_limit",
                nextMarketDataLimit(settings),
                "Raise cap",
                "Candidate cap updated",
                "Raise the Polymarket active-market cap for the next pull.",
              ),
    }),
    buildFunnelStage({
      key: "scanner",
      label: "Market filters",
      status: scanner?.status ?? (operations ? "idle" : "loading"),
      entered: scannerEntered,
      passed: scannerPassed,
      blocked: scannerBlocked,
      enteredLabel: "records checked",
      passedLabel: "Passed",
      blockedLabel: "Filtered",
      reason:
        scannerBlocked > 0
          ? `${formatWhole(scannerBlocked)} stopped in scanner filters.`
          : "No scanner rejection is visible in the latest tick.",
      detail:
        scannerReason.count > 0
          ? `Main reason: ${scannerReason.reason}.`
          : scanner?.message ?? "Scanner output has not been recorded yet.",
      action:
        scannerEntered > 0 && scannerBlocked > 0
          ? scannerFilterAction(settings, scannerReason.reason, scanner?.candidates ?? [])
          : linkFunnelAction(
              "/dashboard/operations",
              scannerPassed > 0 ? "Review candidates" : "Run cycle",
              "The Run page shows scanner records after a manual or scheduled cycle.",
            ),
    }),
    buildFunnelStage({
      key: "reasoning",
      label: "Model scoring",
      status: reasoning?.status ?? (operations ? "idle" : "loading"),
      entered: reasoningEntered,
      passed: reasoningPassed,
      blocked: reasoningBlocked,
      enteredLabel: "prompts",
      passedLabel: "Scored",
      blockedLabel: "Skipped",
      reason:
        reasoningBlocked > 0
          ? `${formatWhole(reasoningBlocked)} prompt${reasoningBlocked === 1 ? "" : "s"} did not produce a score.`
          : "Model scoring did not stop the latest tick.",
      detail:
        reasoningReason.count > 0
          ? `Main reason: ${reasoningReason.reason}.`
          : reasoning?.message ?? "Model scoring output has not been recorded yet.",
      action:
        reasoningEntered === 0
          ? linkFunnelAction(
              "/dashboard/operations",
              "Review scoring",
              "Model scoring starts after scanner candidates pass.",
            )
          : (reasoning?.skippedCount ?? 0) > 0
            ? patchFunnelAction(
                settings,
                "reasoning.max_prompts_per_provider_per_run",
                nextPromptCap(settings),
                "Raise prompt cap",
                "Prompt cap updated",
                "Allow more scanner survivors to reach each model provider.",
              )
            : patchFunnelAction(
                settings,
                "reasoning.polymarket.min_confidence",
                lowerRatioSetting(settings, "reasoning.polymarket.min_confidence", 0.75, 0.03, 0.62),
                "Lower confidence",
                "Confidence gate updated",
                "Let more scored Polymarket candidates continue to strategy checks.",
              ),
    }),
    buildFunnelStage({
      key: "strategy",
      label: "Strategy consensus",
      status: strategyConsensus?.status ?? (operations ? "idle" : "loading"),
      entered: consensusEntered,
      passed: consensusPassed,
      blocked: consensusBlocked,
      enteredLabel: "votes",
      passedLabel: "Approved",
      blockedLabel: "Refused",
      reason:
        consensusBlocked > 0
          ? `${formatWhole(consensusBlocked)} strategy vote${consensusBlocked === 1 ? "" : "s"} did not approve.`
          : "Strategy consensus did not block the latest tick.",
      detail:
        consensusReason.count > 0
          ? `Main reason: ${consensusReason.reason}.`
          : strategyConsensus?.message ?? "Strategy consensus output has not been recorded yet.",
      action:
        consensusEntered > 0 && consensusBlocked > 0
          ? strategyAction(settings)
          : linkFunnelAction(
              "/dashboard/operations",
              consensusPassed > 0 ? "Review approvals" : "Review votes",
              "The Run page shows each strategy vote and approval record.",
            ),
    }),
    buildFunnelStage({
      key: "execution",
      label: "Risk and order plan",
      status: execution?.status ?? (operations ? "idle" : "loading"),
      entered: orderEntered,
      passed: orderPassed,
      blocked: orderBlocked,
      enteredLabel: "approved signals",
      passedLabel: "Order plans",
      blockedLabel: "Refused",
      reason:
        orderBlocked > 0
          ? `${formatWhole(orderBlocked)} order intent${orderBlocked === 1 ? "" : "s"} refused before venue submission.`
          : "Risk checks did not refuse an order plan.",
      detail:
        orderReason.count > 0
          ? `Main reason: ${orderReason.reason}.`
          : execution?.message ?? "Execution output has not been recorded yet.",
      action:
        orderEntered > 0 && orderBlocked > 0
          ? linkFunnelAction(
              "/dashboard/config",
              "Review risk",
              "Position size, loss, slippage, and live-mode settings are controlled in Settings.",
            )
          : linkFunnelAction(
              "/dashboard/operations",
              orderPassed > 0 ? "Review order plans" : "Review execution",
              "The Run page shows execution records after a signal reaches order planning.",
            ),
    }),
    buildFunnelStage({
      key: "live-order",
      label: "Live order",
      status: submittedCount > 0 ? "submitted" : simulatedCount > 0 ? "simulated" : execution?.status ?? "idle",
      entered: liveOrderEntered,
      passed: submittedCount,
      blocked: liveOrderBlocked,
      enteredLabel: "order outcomes",
      passedLabel: "Submitted",
      blockedLabel: liveEnabled ? "Not submitted" : "Simulated",
      reason:
        submittedCount > 0
          ? `${formatWhole(submittedCount)} live order${submittedCount === 1 ? "" : "s"} submitted.`
          : simulatedCount > 0
            ? `${formatWhole(simulatedCount)} order${simulatedCount === 1 ? "" : "s"} stayed in simulation.`
            : "No live order was submitted.",
      detail: liveEnabled
        ? "Live mode is on, but order submission still depends on venue, risk, and emergency-stop gates."
        : "Live mode is off, so any approved order remains a practice order.",
      action: linkFunnelAction(
        submittedCount > 0 ? "/dashboard/operations" : "/dashboard/config",
        submittedCount > 0 ? "Open orders" : "Review live mode",
        submittedCount > 0
          ? "Order details are recorded on the Run page."
          : "Live mode should only be changed after account, risk, notification, and dry-run checks pass.",
      ),
    }),
  ];
}

function buildFunnelStage(
  stage: Omit<LastTickFunnelStage, "tone">,
): LastTickFunnelStage {
  return {
    ...stage,
    tone: funnelStageTone(stage.status, stage.entered, stage.passed, stage.blocked),
  };
}

function lastTickFunnelSummary(stages: LastTickFunnelStage[]): string {
  const firstStage = stages[0];
  const finalStage = stages[stages.length - 1];
  if ((finalStage?.passed ?? 0) > 0) {
    return `${formatWhole(firstStage.entered)} market record${firstStage.entered === 1 ? "" : "s"} entered the last tick and ${formatWhole(finalStage.passed)} live order${finalStage.passed === 1 ? "" : "s"} reached the venue.`;
  }
  const hardStop = stages.find((stage) => stage.entered > 0 && stage.passed === 0 && stage.blocked > 0);
  if (hardStop) {
    return `${formatWhole(firstStage.entered)} market record${firstStage.entered === 1 ? "" : "s"} entered the last tick. The first hard stop was ${hardStop.label.toLowerCase()}: ${hardStop.detail}`;
  }
  return `${formatWhole(firstStage.entered)} market record${firstStage.entered === 1 ? "" : "s"} entered the last tick and no live order was submitted.`;
}

function patchFunnelAction(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  nextValue: ConfigValue,
  label: string,
  savedLabel: string,
  detail: string,
): LastTickFunnelAction {
  return {
    type: "patch",
    label,
    savedLabel,
    path,
    currentValue: valueAtPath(settings, path) as ConfigValue | null,
    nextValue,
    detail,
  };
}

function linkFunnelAction(href: string, label: string, detail: string): LastTickFunnelAction {
  return {
    type: "link",
    href,
    label,
    detail,
  };
}

function scannerFilterAction(
  settings: Record<string, unknown>,
  reason: string,
  candidates: ScannerCandidateView[],
): LastTickFunnelAction {
  const lowerReason = reason.toLowerCase();
  const mostlyAlpaca =
    candidates.some((candidate) => candidate.venue.toLowerCase().includes("alpaca")) &&
    !candidates.some((candidate) => candidate.venue.toLowerCase().includes("polymarket"));

  if (mostlyAlpaca || lowerReason.includes("quote")) {
    return patchFunnelAction(
      settings,
      "scanner.alpaca.max_spread",
      higherRatioSetting(settings, "scanner.alpaca.max_spread", 0.5, 0.1, 1),
      "Widen stock spread",
      "Stock spread updated",
      "Allow wider stock quotes to reach model scoring.",
    );
  }
  if (lowerReason.includes("liquidity")) {
    return patchFunnelAction(
      settings,
      "scanner.polymarket.min_liquidity",
      lowerPositiveSetting(settings, "scanner.polymarket.min_liquidity", 500, 0.8, 1),
      "Lower liquidity",
      "Liquidity gate updated",
      "Allow lower-liquidity Polymarket markets through the scanner.",
    );
  }
  if (lowerReason.includes("depth")) {
    return patchFunnelAction(
      settings,
      "scanner.polymarket.min_depth",
      lowerPositiveSetting(settings, "scanner.polymarket.min_depth", 500, 0.8, 1),
      "Lower depth",
      "Depth gate updated",
      "Allow thinner Polymarket order books through the scanner.",
    );
  }
  if (lowerReason.includes("volume")) {
    return patchFunnelAction(
      settings,
      "scanner.polymarket.min_volume",
      lowerPositiveSetting(settings, "scanner.polymarket.min_volume", 1000, 0.8, 0),
      "Lower volume",
      "Volume gate updated",
      "Allow lower-volume Polymarket markets through the scanner.",
    );
  }
  if (lowerReason.includes("hour") || lowerReason.includes("resolution")) {
    return patchFunnelAction(
      settings,
      "scanner.polymarket.max_hours_to_resolution",
      higherRatioSetting(settings, "scanner.polymarket.max_hours_to_resolution", 168, 24, 336),
      "Extend window",
      "Resolution window updated",
      "Allow markets farther from resolution through the scanner.",
    );
  }
  return patchFunnelAction(
    settings,
    "scanner.polymarket.max_spread",
    higherRatioSetting(settings, "scanner.polymarket.max_spread", 0.05, 0.01, 0.1),
    "Widen spread",
    "Spread gate updated",
    "Allow slightly wider Polymarket spreads through the scanner.",
  );
}

function strategyAction(settings: Record<string, unknown>): LastTickFunnelAction {
  if (!booleanConfigValue(valueAtPath(settings, "strategies.convergence.enabled"))) {
    return patchFunnelAction(
      settings,
      "strategies.convergence.enabled",
      true,
      "Enable convergence",
      "Convergence strategy enabled",
      "Add convergence votes to future scored candidates.",
    );
  }
  if (!booleanConfigValue(valueAtPath(settings, "strategies.arbitrage.enabled"))) {
    return patchFunnelAction(
      settings,
      "strategies.arbitrage.enabled",
      true,
      "Enable arbitrage",
      "Arbitrage strategy enabled",
      "Add arbitrage votes to future scored candidates.",
    );
  }
  return linkFunnelAction(
    "/dashboard/operations",
    "Review votes",
    "The Run page shows each strategy vote and refusal reason.",
  );
}

function marketDataCandidateCount(marketData: MarketDataPullView | null): number {
  if (!marketData) {
    return 0;
  }
  const venuePulls = marketData.venues?.length ? marketData.venues : [marketData];
  const declaredCount = venuePulls.reduce((total, venuePull) => total + (venuePull.candidateCount ?? 0), 0);
  const rowCount = venuePulls.reduce((total, venuePull) => total + (venuePull.candidates?.length ?? 0), 0);
  return Math.max(declaredCount, rowCount);
}

function marketDataVenueBreakdown(marketData: MarketDataPullView | null): string {
  if (!marketData) {
    return "";
  }
  const venuePulls = marketData.venues?.length ? marketData.venues : [marketData];
  if (venuePulls.length < 2) {
    return "";
  }
  return venuePulls
    .map((venuePull) => {
      const count = Math.max(venuePull.candidateCount ?? 0, venuePull.candidates?.length ?? 0);
      return `${formatWhole(count)} ${marketDataVenueLabel(venuePull.venue)}`;
    })
    .join(", ");
}

function marketDataVenueLabel(venue: string): string {
  const normalized = venue.trim().toLowerCase();
  if (normalized === "polymarket_us") {
    return "Polymarket US";
  }
  if (normalized === "polymarket_international") {
    return "Polymarket International";
  }
  if (normalized === "alpaca") {
    return "Alpaca";
  }
  return venue;
}

function mostCommonReason(values: Array<string | null | undefined> | undefined): { reason: string; count: number } {
  const counts = new Map<string, number>();
  for (const value of values ?? []) {
    const reason = normalizeReason(value);
    if (!reason) {
      continue;
    }
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  const [reason, count] = [...counts.entries()].sort((left, right) => right[1] - left[1])[0] ?? ["not recorded", 0];
  return { reason, count };
}

function normalizeReason(value: string | null | undefined): string {
  const reason = (value ?? "").trim();
  if (!reason || ["none", "null", "undefined", "n/a"].includes(reason.toLowerCase())) {
    return "";
  }
  return reason;
}

function nextMarketDataLimit(settings: Record<string, unknown>): number {
  const current = numberValue(valueAtPath(settings, "scanner.polymarket.market_data_limit"), 5);
  return Math.min(250, Math.max(Math.floor(current) + 5, Math.ceil(current * 2), 10));
}

function nextPromptCap(settings: Record<string, unknown>): number {
  const current = numberValue(valueAtPath(settings, "reasoning.max_prompts_per_provider_per_run"), 100);
  return Math.max(Math.floor(current) + 10, Math.ceil(current * 1.25));
}

function higherRatioSetting(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  minimumIncrease: number,
  max: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.min(max, Math.max(current + minimumIncrease, current * 1.25)));
}

function lowerPositiveSetting(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  scale: number,
  min: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.max(min, current * scale));
}

function lowerRatioSetting(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  drop: number,
  min: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.max(min, current - drop));
}

function funnelStageTone(
  status: string,
  entered: number,
  passed: number,
  blocked: number,
): "ok" | "waiting" | "blocked" {
  if (entered > 0 && passed === 0 && blocked > 0) {
    return "blocked";
  }
  if (passed > 0) {
    return "ok";
  }
  return statusTone(status);
}

function funnelWidth(value: number, max: number): string {
  if (value <= 0) {
    return "0%";
  }
  return `${Math.max(7, Math.min(100, (value / max) * 100)).toFixed(2)}%`;
}

function formatWhole(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Math.max(0, Math.round(value)));
}

function lastTickResult(
  operations: OperationsSummaryView | null,
  tickSummary: TickSummaryView,
) {
  if (!operations) {
    return {
      title: "Loading latest tick",
      body: "Panels will fill in as each status check returns.",
      headline: "Loading",
      detail: "Waiting for operations data.",
      status: "loading",
      tone: "waiting" as const,
      label: "Loading",
    };
  }
  const latestRun = operations.pipelineRuns[0];
  const execution = operations.execution;
  const scanner = operations.scanner;
  const reasoning = operations.reasoning;
  if ((execution?.submittedCount ?? 0) > 0) {
    return {
      title: "A trade was submitted",
      body: "The latest tick reached live submission and created a venue order.",
      headline: "Trade submitted",
      detail: `${execution?.submittedCount ?? 0} order submitted in the latest execution summary.`,
      status: latestRun?.status ?? execution?.status ?? "submitted",
      tone: "ok" as const,
      label: "Trade placed",
    };
  }
  if ((execution?.simulatedCount ?? 0) > 0) {
    return {
      title: "The app is finding trades in simulation",
      body: "The latest tick produced simulated orders. Live execution still depends on the live setting and venue checks.",
      headline: "Practice order simulated",
      detail: `${execution?.simulatedCount ?? 0} simulated order intent recorded.`,
      status: latestRun?.status ?? execution?.status ?? "simulated",
      tone: "waiting" as const,
      label: "Simulation",
    };
  }
  if ((scanner?.acceptedCount ?? 0) === 0 && (scanner?.candidateCount ?? 0) > 0) {
    return {
      title: "No market passed the filters",
      body: "The latest tick loaded markets, but the market filters rejected them before scoring.",
      headline: "Market filters blocked the tick",
      detail: `${scanner?.rejectedCount ?? 0} rejected candidates and no accepted candidates.`,
      status: scanner?.status ?? "no_candidates",
      tone: "blocked" as const,
      label: "Blocked",
    };
  }
  if ((reasoning?.failedCount ?? 0) > 0 && (reasoning?.scoredCount ?? 0) === 0) {
    return {
      title: "Model scoring did not produce usable scores",
      body: "Candidates reached model scoring, but the app did not receive approved outputs.",
      headline: "Model scoring blocked the tick",
      detail: `${reasoning?.failedCount ?? 0} failed prompt attempts.`,
      status: reasoning?.status ?? "failed",
      tone: "blocked" as const,
      label: "Blocked",
    };
  }
  return {
    title: "No trade was placed",
    body: "The app followed your current settings and did not create a live order.",
    headline: "No order submitted",
    detail: tickSummary.summaryMarkdown
      ? markdownLines(tickSummary.summaryMarkdown)[0]
      : "No execution intent was submitted in the latest tick.",
    status: latestRun?.status ?? "idle",
    tone: "waiting" as const,
    label: "Monitoring",
  };
}

function recommendationPlans(
  settings: Record<string, unknown>,
  dailySummary: TickSummaryView,
  operations: OperationsSummaryView | null,
): RecommendationPlan[] {
  const context = recommendationContext(dailySummary, operations);
  const profile = (
    id: RecommendationPlan["id"],
    title: string,
    tone: RecommendationPlan["tone"],
    summaryText: string,
    effect: string,
    risk: string,
    scale: number,
    confidenceDrop: number,
  ): RecommendationPlan => ({
    id,
    title,
    tone,
    summary: summaryText,
    effect,
    risk,
    patches: [
      patchFor(settings, "scanner.polymarket.max_hours_to_resolution", profileValue(settings, "scanner.polymarket.max_hours_to_resolution", 168, scale, 336, 12), context.resolution),
      patchFor(settings, "scanner.polymarket.max_spread", profileValue(settings, "scanner.polymarket.max_spread", 0.05, scale, 0.10, 0.005), context.spread),
      patchFor(settings, "scanner.alpaca.max_spread", profileValue(settings, "scanner.alpaca.max_spread", 0.5, scale, 1.0, 0.05), context.alpacaSpread),
      patchFor(settings, "scanner.alpaca.min_quote_liquidity", inverseProfileValue(settings, "scanner.alpaca.min_quote_liquidity", 1, scale, 0.25), context.liquidity),
      patchFor(settings, "reasoning.polymarket.min_confidence", confidenceValue(settings, "reasoning.polymarket.min_confidence", 0.75, confidenceDrop, 0.62), context.confidence),
      patchFor(settings, "reasoning.alpaca.min_confidence", confidenceValue(settings, "reasoning.alpaca.min_confidence", 0.6, confidenceDrop, 0.50), context.confidence),
    ],
  });
  return [
    profile(
      "conservative",
      "Conservative",
      "ok",
      "Small filter change. Keeps confidence settings unchanged and focuses on markets near the current policy.",
      "Small change",
      "Lowest chance of noisy candidates",
      1.1,
      0,
    ),
    profile(
      "balanced",
      "Balanced",
      "waiting",
      "Moderate filter change with a small confidence adjustment. This is the best first test if candidates are repeatedly rejected.",
      "Moderate change",
      "More candidates to review",
      1.25,
      0.03,
    ),
    profile(
      "aggressive",
      "Aggressive",
      "blocked",
      "Wider filter window and lower confidence thresholds. Use this when you want more candidates for simulation review.",
      "Largest change",
      "Most false positives",
      1.5,
      0.06,
    ),
  ];
}

function recommendationContext(dailySummary: TickSummaryView, operations: OperationsSummaryView | null) {
  const text = [
    dailySummary.summaryMarkdown,
    ...(dailySummary.keyEvents ?? []),
    ...(dailySummary.warnings ?? []),
    operations?.scanner?.message ?? "",
  ].join(" ").toLowerCase();
  return {
    resolution: text.includes("resolution") || text.includes("too far")
      ? "Recent ticks mention resolution gating, so this expands the allowed resolution window."
      : "Expands the resolution window so more otherwise valid markets can pass scan.",
    spread: text.includes("spread")
      ? "Recent ticks mention spread gating, so this allows slightly wider Polymarket spreads."
      : "Allows slightly wider Polymarket spreads before model scoring.",
    alpacaSpread: text.includes("alpaca") || text.includes("spread")
      ? "Recent ticks mention Alpaca or spread gating, so this allows more stock quotes through scan."
      : "Allows more stock quotes through market filters before model scoring.",
    liquidity: text.includes("liquidity")
      ? "Recent ticks mention liquidity, so this lowers the quote liquidity requirement."
      : "Lowers the quote liquidity gate for more simulation candidates.",
    confidence: "Slightly lowers the scoring pass line without changing risk or live-trading gates.",
  };
}

function tradeUnblockRecommendation(
  settings: Record<string, unknown>,
  dailySummary: TickSummaryView,
  operations: OperationsSummaryView | null,
): TradeUnblockRecommendation | null {
  const scannerCandidates = operations?.scanner?.candidates ?? [];
  const rejected = scannerCandidates.filter((candidate) => candidate.status === "rejected");
  const counts = rejectionCounts(rejected);
  const text = [
    dailySummary.summaryMarkdown,
    ...(dailySummary.keyEvents ?? []),
    ...(dailySummary.warnings ?? []),
    operations?.scanner?.message ?? "",
  ].join(" ").toLowerCase();
  const patches = new Map<AllowedConfigPath, RecommendationPatch>();
  const notes: string[] = [];
  const putPatch = (patch: RecommendationPatch) => {
    patches.set(patch.path, patch);
  };

  const polymarketResolutionRejected = rejected.filter(
    (candidate) => isVenue(candidate, "polymarket") && normalizedReason(candidate) === "resolution too far",
  );
  if (polymarketResolutionRejected.length || text.includes("resolution too far")) {
    const currentHours = numberValue(valueAtPath(settings, "scanner.polymarket.max_hours_to_resolution"), 168);
    const observedHours = maxCandidateNumber(polymarketResolutionRejected, [
      "hoursToResolution",
      "metrics.hoursToResolution",
    ]);
    const nextHours = Math.min(
      720,
      observedHours === null
        ? currentHours < 336
          ? 336
          : currentHours + 168
        : roundUpToStep(observedHours + 24, 12),
    );
    if (nextHours > currentHours) {
      putPatch(
        patchFor(
          settings,
          "scanner.polymarket.max_hours_to_resolution",
          trimNumber(nextHours),
          `Raises the Polymarket resolution window from ${trimNumber(currentHours)} hours so farther-out markets can reach reasoning.`,
        ),
      );
    } else {
      notes.push("Polymarket max hours is already at the dashboard limit. Review market selection before widening risk.");
    }
  }

  const alpacaQuoteRejected = rejected.filter(
    (candidate) => isVenue(candidate, "alpaca") && normalizedReason(candidate) === "quote liquidity below minimum",
  );
  if (alpacaQuoteRejected.length) {
    const current = numberValue(valueAtPath(settings, "scanner.alpaca.min_quote_liquidity"), 1);
    const observed = minCandidateNumber(alpacaQuoteRejected, ["liquidity"]);
    const next = Math.max(0.25, observed === null ? current / 2 : observed);
    if (next < current) {
      putPatch(
        patchFor(
          settings,
          "scanner.alpaca.min_quote_liquidity",
          trimNumber(next),
          "Lowers the stock quote liquidity gate for scanner diagnosis.",
        ),
      );
    }
  }

  const alpacaSpreadRejected = rejected.filter(
    (candidate) => isVenue(candidate, "alpaca") && normalizedReason(candidate) === "spread too wide",
  );
  if (alpacaSpreadRejected.length) {
    const current = numberValue(valueAtPath(settings, "scanner.alpaca.max_spread"), 0.5);
    const observed = maxCandidateNumber(alpacaSpreadRejected, ["spread"]);
    const next = Math.min(5, observed === null ? current + 0.25 : roundUpToStep(observed + 0.05, 0.01));
    if (next > current) {
      putPatch(
        patchFor(
          settings,
          "scanner.alpaca.max_spread",
          trimNumber(next),
          "Allows wider stock quotes through the scanner before model scoring.",
        ),
      );
    }
  }

  const historyRejected = rejected.filter(
    (candidate) => isVenue(candidate, "alpaca") && normalizedReason(candidate) === "insufficient historical bars",
  );
  if (historyRejected.length) {
    const current = numberValue(valueAtPath(settings, "scanner.alpaca.min_history_bars"), 2);
    if (current > 2) {
      putPatch(
        patchFor(
          settings,
          "scanner.alpaca.min_history_bars",
          2,
          "Restores the stock history requirement to the supported two-bar minimum.",
        ),
      );
    } else {
      notes.push("Alpaca history bars are a data freshness issue, not a setting to loosen below 2 for live use.");
    }
  }

  const strategyRejected = rejected.filter(
    (candidate) => isVenue(candidate, "alpaca") && normalizedReason(candidate) === "no stock strategy threshold met",
  );
  if (strategyRejected.length) {
    for (const [path, value] of [
      ["scanner.alpaca.strategies.momentum.min_change_pct", "0.005"],
      ["scanner.alpaca.strategies.mean_reversion.min_deviation_pct", "0.01"],
      ["scanner.alpaca.strategies.gap.min_gap_pct", "0.0075"],
      ["scanner.alpaca.strategies.liquidity.min_volume", "50000"],
      ["scanner.alpaca.strategies.volatility.min_range_pct", "0.01"],
      ["scanner.alpaca.strategies.unusual_volume.min_ratio", "1.2"],
    ] as Array<[AllowedConfigPath, string]>) {
      const current = numberValue(valueAtPath(settings, path), Number(value));
      const next = Number(value);
      if (Number.isFinite(current) && current > next) {
        putPatch(
          patchFor(
            settings,
            path,
            value,
            "Lowers stock strategy scanner thresholds so more symbols can reach model scoring.",
          ),
        );
      }
    }
  }

  const symbolRejected = rejected.filter(
    (candidate) => isVenue(candidate, "alpaca") && normalizedReason(candidate) === "symbol outside universe",
  );
  if (symbolRejected.length) {
    notes.push("Some Alpaca symbols are outside the configured universe. Add the symbol or preset in Settings if you want them scanned.");
  }

  const finalPatches = [...patches.values()].filter((patch) => !sameConfigValue(patch.currentValue, patch.nextValue));
  if (!finalPatches.length && !notes.length) {
    return null;
  }

  return {
    title: "Update settings to allow more candidates",
    body:
      finalPatches.length > 0
        ? "The latest scanner output points to settings that are still too restrictive. These changes apply to your saved config on the next loop and do not bypass model, risk, credential, or market-hours gates."
        : "The latest scanner output points to a blocker that needs data or universe cleanup before settings can help.",
    primaryBlocker: topRejectionLabel(counts) ?? "scanner blocked",
    patches: finalPatches,
    notes,
  };
}

function friendlyEmergencyStopStatus(value: string | null | undefined): string {
  if (!value) {
    return "loading";
  }
  if (value === "active") {
    return "active";
  }
  if (value === "inactive") {
    return "off";
  }
  return value;
}

function inferredRecommendationPlanId(settings: Record<string, unknown>): RecommendationPlan["id"] {
  const maxResolutionHours = numberValue(
    valueAtPath(settings, "scanner.polymarket.max_hours_to_resolution"),
    168,
  );
  const maxPolymarketSpread = numberValue(valueAtPath(settings, "scanner.polymarket.max_spread"), 0.05);
  const maxAlpacaSpread = numberValue(valueAtPath(settings, "scanner.alpaca.max_spread"), 0.5);
  const minQuoteLiquidity = numberValue(valueAtPath(settings, "scanner.alpaca.min_quote_liquidity"), 1);
  const polymarketConfidence = numberValue(valueAtPath(settings, "reasoning.polymarket.min_confidence"), 0.75);
  const alpacaConfidence = numberValue(valueAtPath(settings, "reasoning.alpaca.min_confidence"), 0.6);

  if (
    maxResolutionHours >= 240 ||
    maxPolymarketSpread >= 0.07 ||
    maxAlpacaSpread >= 0.75 ||
    minQuoteLiquidity <= 0.67 ||
    polymarketConfidence <= 0.7 ||
    alpacaConfidence <= 0.55
  ) {
    return "aggressive";
  }
  if (
    maxResolutionHours >= 200 ||
    maxPolymarketSpread >= 0.058 ||
    maxAlpacaSpread >= 0.6 ||
    minQuoteLiquidity <= 0.8 ||
    polymarketConfidence <= 0.73 ||
    alpacaConfidence <= 0.58
  ) {
    return "balanced";
  }
  if (
    maxResolutionHours > 168 ||
    maxPolymarketSpread > 0.05 ||
    maxAlpacaSpread > 0.5 ||
    minQuoteLiquidity < 1 ||
    polymarketConfidence < 0.75 ||
    alpacaConfidence < 0.6
  ) {
    return "conservative";
  }
  return "balanced";
}

function patchFor(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  nextValue: ConfigValue,
  why: string,
): RecommendationPatch {
  return {
    path,
    currentValue: valueAtPath(settings, path) as ConfigValue | null,
    nextValue,
    why,
  };
}

function rejectionCounts(candidates: ScannerCandidateView[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const candidate of candidates) {
    const reason = normalizedReason(candidate);
    if (!reason) {
      continue;
    }
    const venue = isVenue(candidate, "alpaca")
      ? "Alpaca"
      : isVenue(candidate, "polymarket")
        ? "Polymarket"
        : "Scanner";
    const key = `${venue}: ${reason}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return counts;
}

function topRejectionLabel(counts: Map<string, number>): string | null {
  let top: { label: string; count: number } | null = null;
  for (const [label, count] of counts) {
    if (top === null || count > top.count) {
      top = { label, count };
    }
  }
  return top ? `${top.label} (${top.count})` : null;
}

function normalizedReason(candidate: ScannerCandidateView): string {
  return String(candidate.refusalReason ?? "").trim().toLowerCase();
}

function isVenue(candidate: ScannerCandidateView, venue: "alpaca" | "polymarket"): boolean {
  return String(candidate.venue ?? "").toLowerCase().includes(venue);
}

function maxCandidateNumber(candidates: ScannerCandidateView[], paths: string[]): number | null {
  const values = candidates
    .flatMap((candidate) => paths.map((path) => numberFromCandidate(candidate, path)))
    .filter((value): value is number => value !== null);
  return values.length ? Math.max(...values) : null;
}

function minCandidateNumber(candidates: ScannerCandidateView[], paths: string[]): number | null {
  const values = candidates
    .flatMap((candidate) => paths.map((path) => numberFromCandidate(candidate, path)))
    .filter((value): value is number => value !== null);
  return values.length ? Math.min(...values) : null;
}

function numberFromCandidate(candidate: ScannerCandidateView, path: string): number | null {
  const value = valueAtPath(candidate, path);
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function roundUpToStep(value: number, step: number): number {
  return Math.ceil(value / step) * step;
}

function sameConfigValue(currentValue: ConfigValue | null, nextValue: ConfigValue): boolean {
  if (currentValue === null || currentValue === undefined) {
    return false;
  }
  return String(currentValue) === String(nextValue);
}

function profileValue(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  scale: number,
  max: number,
  floorIncrease: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.min(max, Math.max(current + floorIncrease, current * scale)));
}

function inverseProfileValue(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  scale: number,
  min: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.max(min, current / scale));
}

function confidenceValue(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  fallback: number,
  drop: number,
  min: number,
): string {
  const current = numberValue(valueAtPath(settings, path), fallback);
  return trimNumber(Math.max(min, current - drop));
}

function statusTone(status: string): "ok" | "waiting" | "blocked" {
  if (["blocked", "failed", "error", "refused", "rate_limited"].includes(status)) {
    return "blocked";
  }
  if (["completed", "ok", "pulled", "summarized", "submitted"].includes(status)) {
    return "ok";
  }
  return "waiting";
}

function markdownLines(value: string | null | undefined): string[] {
  const lines = (value ?? "")
    .split("\n")
    .map((line) => line.trim().replace(/^[-*]\s+/, ""))
    .filter(Boolean);
  return lines.length ? lines : ["No summary text is available yet."];
}

function valueAtPath(source: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, part) => {
    if (!current || typeof current !== "object" || !(part in current)) {
      return null;
    }
    return (current as Record<string, unknown>)[part];
  }, source);
}

function valueAtUpdatedPath(
  source: Record<string, unknown>,
  path: string,
  value: ConfigValue,
): Record<string, unknown> {
  const parts = path.split(".");
  const copy = structuredClone(source);
  let current: Record<string, unknown> = copy;
  for (const part of parts.slice(0, -1)) {
    const child = current[part];
    if (!child || typeof child !== "object" || Array.isArray(child)) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
  current[parts[parts.length - 1]] = value;
  return copy;
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function trimNumber(value: number): string {
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function formatConfigValue(value: ConfigValue | null): string {
  if (value === null || value === undefined) {
    return "not set";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatCountdown(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "unknown";
  }
  if (seconds <= 0) {
    return "due now";
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes === 0) {
    return `${remainder}s`;
  }
  return `${minutes}m ${remainder}s`;
}

function secondsUntilTick(schedule: TickScheduleView | null, nowMs: number): number | null {
  if (!schedule) {
    return null;
  }

  const nextTickMs = schedule.nextTickAt ? new Date(schedule.nextTickAt).getTime() : Number.NaN;
  if (Number.isFinite(nextTickMs)) {
    return Math.max(0, Math.ceil((nextTickMs - nowMs) / 1000));
  }

  if (typeof schedule.secondsUntilNextTick === "number") {
    return Math.max(0, schedule.secondsUntilNextTick);
  }
  return null;
}

function tickSourceLabel(schedule: TickScheduleView | null): string {
  if (!schedule || schedule.lastTickSource === "none") {
    return "Waiting for the first tick.";
  }
  if (schedule.lastTickSource === "worker_heartbeat") {
    return "No tick recorded yet. Showing heartbeat time.";
  }
  return schedule.source ?? "Pipeline run recorded.";
}

function expectedVersionFromSnapshot(snapshot: ConfigSnapshot): string {
  return snapshot.version === "bootstrap" ? "" : snapshot.version;
}

function readableConfigError(message: string): string {
  try {
    const parsed = JSON.parse(message) as { message?: string };
    return parsed.message ?? message;
  } catch {
    return message;
  }
}
