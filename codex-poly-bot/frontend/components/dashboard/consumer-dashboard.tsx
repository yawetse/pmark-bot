"use client";

import Link from "next/link";
import {
  Bell,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  LineChart as LineChartIcon,
  RefreshCw,
  RotateCcw,
  Settings2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { EconomicsSummaryView } from "@/components/dashboard/economics-panel";
import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import { FALLBACK_TICK_SUMMARY, type TickSummaryView } from "@/components/dashboard/tick-summary-panel";
import { dashboardApi, type ApiClientResult } from "@/lib/api";
import { CONFIG_PATH_DETAILS, type AllowedConfigPath } from "@/lib/config-paths";
import { useDashboardRealtime, type TickScheduleView } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-004, REQ-UI-005, REQ-UI-008, REQ-NOT-006, REQ-OBS-005

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
  patches: RecommendationPatch[];
};

type DashboardAction = {
  title: string;
  body: string;
  href?: string;
  linkLabel?: string;
};

type SafetySummary = {
  label: string;
  tone: "ok" | "waiting" | "blocked";
  detail: string;
};

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
  const [economicsState, setEconomicsState] = useState<PanelState<EconomicsSummaryView>>({ status: "loading" });
  const [marketDataState, setMarketDataState] = useState<PanelState<MarketDataPullView>>({ status: "loading" });
  const [tickScheduleState, setTickScheduleState] = useState<PanelState<TickScheduleView>>({ status: "loading" });
  const [notificationsState, setNotificationsState] = useState<PanelState<NotificationSettingsView>>({ status: "loading" });
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [configVersion, setConfigVersion] = useState("");
  const [tradeEmailEnabled, setTradeEmailEnabled] = useState(true);
  const [activePlanId, setActivePlanId] = useState<RecommendationPlan["id"] | null>("balanced");
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
    void loadPanel("economics/summary", setEconomicsState, () => active);
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

    return () => {
      active = false;
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
  const economics = economicsState.status === "ready" ? economicsState.data : null;
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
  const pnlData = useMemo(() => (economics ? pnlChartData(economics) : []), [economics]);
  const timelineSteps = useMemo(
    () => tickTimelineSteps(operations, marketData),
    [operations, marketData],
  );
  const lastTick = useMemo(
    () => lastTickResult(operations, currentDailySummary),
    [operations, currentDailySummary],
  );
  const plans = useMemo(
    () => recommendationPlans(settings, currentDailySummary, operations),
    [settings, currentDailySummary, operations],
  );
  const activePlan = plans.find((plan) => plan.id === activePlanId) ?? plans[1];
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
        setSaveState({ status: "error", message: "Config changed, and the latest version could not be loaded." });
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
    requestedVersion: string;
  }> {
    const requestedVersion = nextConfigVersion(snapshot.version);
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "POST",
      body: JSON.stringify({
        environment: snapshot.environment,
        version: requestedVersion,
        expected_version: expectedVersionFromSnapshot(snapshot) || null,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
      }),
    });
    return { result, requestedVersion };
  }

  async function finalizeConfigSave(
    attempt: {
      result: ApiClientResult<ConfigUpdateResponse>;
      requestedVersion: string;
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
            ? "Config changed while saving. I refreshed it and retried, but it changed again. Try Apply once more."
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
      setConfigVersion(attempt.result.data.new_version ?? attempt.requestedVersion);
    }
    setSaveState({ status: "saved", label: savedLabel });
    return true;
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
              Operate
            </Link>
            <Link className="button subtle" href="/dashboard/config">
              <Settings2 aria-hidden="true" size={16} />
              Configure
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
            <Metric label="Trading mode" value={liveEnabled ? "Live flag on" : "Dry run"} />
            <Metric label="Kill switch" value={operations?.killSwitch ?? "loading"} />
            <Metric label="Active venues" value={activeVenueSummary} />
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
              <h2 id="dashboard-controls-title">What I can do now</h2>
            </div>
            <Settings2 aria-hidden="true" size={20} />
          </div>
          <div className="control-list">
            <DashboardControlLink
              body="Run a dry-run workflow, review open orders, or inspect the kill switch."
              href="/dashboard/operations"
              title="Operate"
            />
            <DashboardControlLink
              body="Change venue, live mode, notification, scanner, and model settings."
              href="/dashboard/config"
              title="Configure"
            />
            <DashboardControlLink
              body="Check credentials, scheduler, notifications, and account readiness."
              href="/dashboard/system"
              title="Verify system"
            />
          </div>
        </section>

        <section className="consumer-panel span-2" aria-labelledby="pnl-chart-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Profit and loss</p>
              <h2 id="pnl-chart-title">P&L over time</h2>
            </div>
            <LineChartIcon aria-hidden="true" size={20} />
          </div>
          {economicsState.status === "loading" ? (
            <PanelLoadingRows />
          ) : economicsState.status === "error" ? (
            <p className="status-message blocked">{economicsState.message}</p>
          ) : (
            <>
              <div className="consumer-metric-strip">
                <Metric label="Trading P&L" value={formatUsd(economicsState.data.trading.totalPnlUsd)} />
                <Metric label="Net after costs" value={formatUsd(economicsState.data.profitability.netAfterRecordedCostsUsd)} />
                <Metric label="Open positions" value={String(economicsState.data.trading.openPositions)} />
              </div>
              <div className="consumer-chart" aria-label="Profit and loss over time">
                {pnlData.length > 1 ? (
                  <ResponsiveContainer height="100%" width="100%">
                    <LineChart data={pnlData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="label" tickLine={false} />
                      <YAxis tickFormatter={(value) => `$${value}`} tickLine={false} width={58} />
                      <Tooltip formatter={(value) => formatUsd(String(value))} />
                      <Line dataKey="trading" dot={false} name="Trading P&L" stroke="var(--accent)" strokeWidth={2.5} />
                      <Line dataKey="net" dot={false} name="Net after costs" stroke="var(--focus)" strokeWidth={2.5} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="consumer-empty-chart">
                    <strong>{formatUsd(economicsState.data.trading.totalPnlUsd)}</strong>
                    <span>Waiting for more P&L snapshots.</span>
                  </div>
                )}
              </div>
            </>
          )}
        </section>

        <section className="consumer-panel" aria-labelledby="last-tick-title">
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
                <Metric label="Accepted" value={String(operationsState.data.scanner?.acceptedCount ?? 0)} />
                <Metric label="Submitted" value={String(operationsState.data.execution?.submittedCount ?? 0)} />
                <Metric label="Simulated" value={String(operationsState.data.execution?.simulatedCount ?? 0)} />
              </div>
            </>
          )}
        </section>

        <section className="consumer-panel span-3" aria-labelledby="timeline-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Tick process</p>
              <h2 id="timeline-title">Five steps</h2>
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
                      : "Add a recipient in Config before emails can send."}
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
              <div className="recommendation-options">
                {plans.map((plan) => (
                  <article
                    aria-current={plan.id === activePlan.id ? "true" : undefined}
                    className={`recommendation-option ${plan.id}`}
                    data-active={plan.id === activePlan.id ? "true" : undefined}
                    key={plan.id}
                  >
                    <div>
                      <span className={`status ${plan.tone}`}>{plan.id}</span>
                      <h3>{plan.title}</h3>
                      <p>{plan.summary}</p>
                    </div>
                    <div className="recommendation-actions">
                      <button className="button subtle" type="button" onClick={() => setActivePlanId(plan.id)}>
                        <ChevronDown aria-hidden="true" size={16} />
                        View detail
                      </button>
                      <button
                        className="button primary recommendation-apply-button"
                        disabled={!canEditConfig}
                        type="button"
                        onClick={() => void applyPlan(plan)}
                      >
                        {saveState.status === "submitting" && activePlan.id === plan.id ? "Applying" : "Apply"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>

              <div className="recommendation-detail">
                <div className="recommendation-detail-heading">
                  <strong>{activePlan.title}</strong>
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
  const mode = liveEnabled ? "live flag on" : "dry run";
  const killSwitch = operations?.killSwitch ?? "loading";
  const nextAction = actionItems[0]?.title.toLowerCase() ?? "monitor the next tick";
  return `Current mode: ${mode}. Kill switch: ${killSwitch}. Active venues: ${activeVenueSummary}. Next step: ${nextAction}.`;
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
      detail: "The kill switch is active. Review Operations before any run or live-mode change.",
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
      label: "live flag on",
      tone: "waiting",
      detail: "Live mode is on. Keep orders, risk gates, notifications, and the kill switch visible while monitoring.",
    };
  }
  return {
    label: "dry run",
    tone: "ok",
    detail: "Live order submission is off. Use this state for scanner, model, and configuration checks.",
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
      linkLabel: "Open system",
    });
  }
  if (operationsState.status === "error") {
    actions.push({
      title: "Recover operations status",
      body: operationsState.message,
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }
  if (operations?.killSwitch === "active") {
    actions.push({
      title: "Review kill switch",
      body: "The emergency control is active. Clear or keep it intentionally before changing run settings.",
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }
  if (activeVenueLabels.length === 0) {
    actions.push({
      title: "Choose an active venue",
      body: "No venue is enabled for scanning or trading. Keep live mode off until the target account is ready.",
      href: "/dashboard/config",
      linkLabel: "Open config",
    });
  }
  if (operations && operations.manualReviewState !== "clear") {
    actions.push({
      title: "Check manual review",
      body: `Manual review is ${operations.manualReviewState}. Confirm the queue before running the next workflow.`,
      href: "/dashboard/operations",
      linkLabel: "Open operations",
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
      linkLabel: "Open config",
    });
  }
  if (actions.length === 0 && !liveEnabled) {
    actions.push({
      title: "Stay in dry run or prepare signoff",
      body: "The current posture is safe for dry-run checks. Use Operations for the next run or Config for a planned change.",
      href: "/dashboard/operations",
      linkLabel: "Open operations",
    });
  }
  if (actions.length === 0) {
    actions.push({
      title: "Monitor the next tick",
      body: "No immediate blocker is visible. Watch the next scheduled loop and review orders after it completes.",
      href: "/dashboard/operations",
      linkLabel: "Open operations",
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="consumer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
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

function pnlChartData(economics: EconomicsSummaryView) {
  const snapshots = economics.history.snapshots ?? [];
  const rows = [...snapshots]
    .filter((snapshot) => snapshot.createdAt)
    .sort((a, b) => new Date(a.createdAt ?? 0).getTime() - new Date(b.createdAt ?? 0).getTime())
    .map((snapshot) => ({
      label: shortDate(snapshot.createdAt),
      trading: numberValue(snapshot.tradingPnlUsd),
      net: numberValue(snapshot.netAfterRecordedCostsUsd),
    }));
  if (rows.length) {
    return rows;
  }
  return [
    {
      label: "Now",
      trading: numberValue(economics.trading.totalPnlUsd),
      net: numberValue(economics.profitability.netAfterRecordedCostsUsd),
    },
  ];
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
      label: "Data load",
      status: stepByKey.get("data_fetch")?.status ?? marketData?.status ?? "loading",
      message: stepByKey.get("data_fetch")?.message ?? (
        marketData ? `${marketData.candidateCount ?? 0} candidates loaded` : "Loading market data."
      ),
    },
    {
      key: "scanner",
      label: "Scan",
      status: stepByKey.get("scanner")?.status ?? operations?.scanner?.status ?? "loading",
      message:
        stepByKey.get("scanner")?.message ??
        (operations
          ? `${operations.scanner?.acceptedCount ?? 0} accepted, ${operations.scanner?.rejectedCount ?? 0} rejected`
          : "Loading scanner results."),
    },
    {
      key: "brain",
      label: "Reason",
      status: stepByKey.get("brain")?.status ?? operations?.reasoning?.status ?? "loading",
      message:
        stepByKey.get("brain")?.message ??
        (operations
          ? `${operations.reasoning?.scoredCount ?? 0} scored, ${operations.reasoning?.failedCount ?? 0} failed`
          : "Loading reasoning results."),
    },
    {
      key: "execution",
      label: "Execute",
      status: stepByKey.get("execution")?.status ?? operations?.execution?.status ?? "loading",
      message:
        stepByKey.get("execution")?.message ??
        (operations
          ? `${operations.execution?.submittedCount ?? 0} submitted, ${operations.execution?.simulatedCount ?? 0} simulated`
          : "Loading execution results."),
    },
    {
      key: "exit",
      label: "Exit",
      status: stepByKey.get("exit")?.status ?? operations?.exit?.status ?? "loading",
      message:
        stepByKey.get("exit")?.message ??
        (operations
          ? `${operations.exit?.triggeredCount ?? 0} exit checks triggered`
          : "Loading exit results."),
    },
  ].map((step) => ({ ...step, tone: statusTone(step.status) }));
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
      title: "The bot is finding trades in dry run",
      body: "The latest tick produced simulated orders. Live execution still depends on the live flag and venue gates.",
      headline: "Dry-run order simulated",
      detail: `${execution?.simulatedCount ?? 0} simulated order intent recorded.`,
      status: latestRun?.status ?? execution?.status ?? "simulated",
      tone: "waiting" as const,
      label: "Dry run",
    };
  }
  if ((scanner?.acceptedCount ?? 0) === 0 && (scanner?.candidateCount ?? 0) > 0) {
    return {
      title: "No candidate passed the scan",
      body: "The latest tick loaded candidates but the scanner rejected them before scoring.",
      headline: "Scanner blocked the tick",
      detail: `${scanner?.rejectedCount ?? 0} rejected candidates and no accepted candidates.`,
      status: scanner?.status ?? "no_candidates",
      tone: "blocked" as const,
      label: "Blocked",
    };
  }
  if ((reasoning?.failedCount ?? 0) > 0 && (reasoning?.scoredCount ?? 0) === 0) {
    return {
      title: "Reasoning did not produce usable scores",
      body: "Candidates reached the reasoning step, but scoring did not produce approved outputs.",
      headline: "Reasoning blocked the tick",
      detail: `${reasoning?.failedCount ?? 0} failed prompt attempts.`,
      status: reasoning?.status ?? "failed",
      tone: "blocked" as const,
      label: "Blocked",
    };
  }
  return {
    title: "No trade was placed",
    body: "The bot stayed inside its current pass conditions and did not create a live order.",
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
  const profile = (id: RecommendationPlan["id"], title: string, tone: RecommendationPlan["tone"], summaryText: string, scale: number, confidenceDrop: number): RecommendationPlan => ({
    id,
    title,
    tone,
    summary: summaryText,
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
      "Small scanner relaxation. Keeps confidence gates unchanged and focuses on markets near the current policy.",
      1.1,
      0,
    ),
    profile(
      "balanced",
      "Balanced",
      "waiting",
      "Moderate scanner relaxation with a small confidence adjustment. This is the best first test if candidates are repeatedly rejected.",
      1.25,
      0.03,
    ),
    profile(
      "aggressive",
      "Aggressive",
      "blocked",
      "Wider scanner window and lower confidence thresholds. Use this when you want more candidates for dry-run review.",
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
      : "Allows slightly wider Polymarket spreads before reasoning.",
    alpacaSpread: text.includes("alpaca") || text.includes("spread")
      ? "Recent ticks mention Alpaca or spread gating, so this allows more stock quotes through scan."
      : "Allows more stock quotes through the scanner before reasoning.",
    liquidity: text.includes("liquidity")
      ? "Recent ticks mention liquidity, so this lowers the quote liquidity requirement."
      : "Lowers the quote liquidity gate for more dry-run candidates.",
    confidence: "Slightly lowers the scoring pass line without changing risk or live-trading gates.",
  };
}

function patchFor(
  settings: Record<string, unknown>,
  path: AllowedConfigPath,
  nextValue: string,
  why: string,
): RecommendationPatch {
  return {
    path,
    currentValue: valueAtPath(settings, path) as ConfigValue | null,
    nextValue,
    why,
  };
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

function formatUsd(value: string | number | null | undefined): string {
  const parsed = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: Math.abs(parsed) < 1 ? 4 : 2,
  }).format(Number.isFinite(parsed) ? parsed : 0);
}

function shortDate(value: string | null | undefined): string {
  if (!value) {
    return "Now";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Now";
  }
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(date);
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

function nextConfigVersion(currentVersion: string): string {
  const match = /^v(\d+)$/.exec(currentVersion);
  if (match) {
    return `v${Number(match[1]) + 1}`;
  }
  return `ui-${Date.now()}`;
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
