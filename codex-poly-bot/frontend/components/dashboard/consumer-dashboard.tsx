"use client";

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
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DashboardSummaryView } from "@/components/dashboard/operator-command-center";
import { FALLBACK_TICK_SUMMARY, type TickSummaryView } from "@/components/dashboard/tick-summary-panel";
import { dashboardApi } from "@/lib/api";
import { CONFIG_PATH_DETAILS, type AllowedConfigPath } from "@/lib/config-paths";

// REQ: REQ-UI-004, REQ-UI-005, REQ-UI-008, REQ-NOT-006, REQ-OBS-005

type ConfigValue = string | boolean | number | string[] | Record<string, unknown>;

type ConfigSnapshot = {
  environment: string;
  version: string;
  settings: Record<string, unknown>;
};

type ConfigUpdateResponse = {
  new_version?: string;
  current_version?: string;
  applies_on_next_loop?: boolean;
};

type SaveState =
  | { status: "idle" }
  | { status: "submitting"; label: string }
  | { status: "saved"; label: string }
  | { status: "error"; message: string };

type SummaryState =
  | { status: "idle" }
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

const DAILY_WINDOW_MINUTES = 24 * 60;
const RECOMMENDATION_DEFAULTS: Partial<Record<AllowedConfigPath, ConfigValue>> = {
  "scanner.polymarket.max_hours_to_resolution": "168",
  "scanner.polymarket.max_spread": "0.05",
  "scanner.alpaca.max_spread": "0.50",
  "scanner.alpaca.min_quote_liquidity": "1",
  "reasoning.polymarket.min_confidence": "0.75",
  "reasoning.alpaca.min_confidence": "0.60",
};

export function ConsumerDashboard({
  summary,
  dailySummary,
  dailySummaryError,
}: {
  summary: DashboardSummaryView;
  dailySummary?: TickSummaryView;
  dailySummaryError?: string;
}) {
  const [settings, setSettings] = useState<Record<string, unknown>>(
    summary.config.settings as Record<string, unknown>,
  );
  const [configVersion, setConfigVersion] = useState(summary.config.version);
  const [expectedVersion, setExpectedVersion] = useState(summary.config.version);
  const [tradeEmailEnabled, setTradeEmailEnabled] = useState(
    valueAtPath(summary.config.settings, "notifications.email_on_trade_placed") !== false,
  );
  const [activePlanId, setActivePlanId] = useState<RecommendationPlan["id"] | null>("balanced");
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });
  const [summaryState, setSummaryState] = useState<SummaryState>(
    dailySummaryError ? { status: "error", message: dailySummaryError } : { status: "idle" },
  );
  const [currentDailySummary, setCurrentDailySummary] = useState<TickSummaryView>(
    dailySummary ?? summary.operations.tickSummary ?? FALLBACK_TICK_SUMMARY,
  );
  const pnlData = useMemo(() => pnlChartData(summary), [summary]);
  const timelineSteps = useMemo(() => tickTimelineSteps(summary), [summary]);
  const lastTick = useMemo(() => lastTickResult(summary), [summary]);
  const plans = useMemo(
    () => recommendationPlans(settings, currentDailySummary, summary),
    [settings, currentDailySummary, summary],
  );
  const activePlan = plans.find((plan) => plan.id === activePlanId) ?? plans[1];
  const generatedAt = formatDateTime(currentDailySummary.generatedAt);

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
    const nextVersion = nextConfigVersion(configVersion);
    const result = await dashboardApi<ConfigUpdateResponse>("config", {
      method: "PUT",
      body: JSON.stringify({
        environment: summary.environment,
        version: nextVersion,
        expected_version: expectedVersion || null,
        patches: patches.map((patch) => ({ op: "replace", path: patch.path, value: patch.value })),
      }),
    });
    if (!result.ok) {
      setSaveState({ status: "error", message: result.message });
      return false;
    }
    const refreshed = await dashboardApi<ConfigSnapshot>("config/current");
    if (refreshed.ok) {
      setSettings(refreshed.data.settings);
      setConfigVersion(refreshed.data.version);
      setExpectedVersion(refreshed.data.version);
      setTradeEmailEnabled(valueAtPath(refreshed.data.settings, "notifications.email_on_trade_placed") !== false);
    } else {
      setSettings((current) =>
        patches.reduce(
          (nextSettings, patch) => valueAtUpdatedPath(nextSettings, patch.path, patch.value),
          current,
        ),
      );
      setConfigVersion(result.data.new_version ?? nextVersion);
      setExpectedVersion(result.data.new_version ?? nextVersion);
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
          <p>{lastTick.body}</p>
        </div>
        <div className={`consumer-status-badge ${lastTick.tone}`}>
          {lastTick.tone === "blocked" ? <CircleAlert aria-hidden="true" size={20} /> : <CheckCircle2 aria-hidden="true" size={20} />}
          <span>{lastTick.label}</span>
        </div>
      </div>

      <div className="consumer-grid">
        <section className="consumer-panel span-2" aria-labelledby="pnl-chart-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Profit and loss</p>
              <h2 id="pnl-chart-title">P&L over time</h2>
            </div>
            <LineChartIcon aria-hidden="true" size={20} />
          </div>
          <div className="consumer-metric-strip">
            <Metric label="Trading P&L" value={formatUsd(summary.economics.trading.totalPnlUsd)} />
            <Metric label="Net after costs" value={formatUsd(summary.economics.profitability.netAfterRecordedCostsUsd)} />
            <Metric label="Open positions" value={String(summary.economics.trading.openPositions)} />
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
                <strong>{formatUsd(summary.economics.trading.totalPnlUsd)}</strong>
                <span>Waiting for more P&L snapshots.</span>
              </div>
            )}
          </div>
        </section>

        <section className="consumer-panel" aria-labelledby="last-tick-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Last tick</p>
              <h2 id="last-tick-title">Result</h2>
            </div>
            <span className={`status ${lastTick.tone}`}>{lastTick.status}</span>
          </div>
          <div className="last-tick-result">
            <strong>{lastTick.headline}</strong>
            <p>{lastTick.detail}</p>
          </div>
          <div className="consumer-metric-list">
            <Metric label="Accepted" value={String(summary.operations.scanner?.acceptedCount ?? 0)} />
            <Metric label="Submitted" value={String(summary.operations.execution?.submittedCount ?? 0)} />
            <Metric label="Simulated" value={String(summary.operations.execution?.simulatedCount ?? 0)} />
          </div>
        </section>

        <section className="consumer-panel span-3" aria-labelledby="timeline-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Tick process</p>
              <h2 id="timeline-title">Five steps</h2>
            </div>
            <span className="status idle">{summary.operations.pipelineRuns[0]?.status ?? "waiting"}</span>
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
          {summaryState.status === "error" ? (
            <p className="status-message blocked">{summaryState.message}</p>
          ) : null}
        </section>

        <section className="consumer-panel" aria-labelledby="notification-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Notifications</p>
              <h2 id="notification-title">Trade emails</h2>
            </div>
            <Bell aria-hidden="true" size={20} />
          </div>
          <label className="consumer-toggle">
            <input
              checked={tradeEmailEnabled}
              onChange={(event) => void updateTradeEmail(event.target.checked)}
              type="checkbox"
            />
            <span>Email me when a real trade is placed</span>
          </label>
          <p className="panel-note">
            {summary.notifications?.recipientCount
              ? `${summary.notifications.recipientCount} recipient configured.`
              : "Add a recipient in Config before emails can send."}
          </p>
        </section>

        <section className="consumer-panel span-3" aria-labelledby="recommendation-title">
          <div className="consumer-panel-heading">
            <div>
              <p className="section-label">Recommendations</p>
              <h2 id="recommendation-title">Change the settings</h2>
            </div>
            <Settings2 aria-hidden="true" size={20} />
          </div>
          <div className="recommendation-options">
            {plans.map((plan) => (
              <article className={`recommendation-option ${plan.id}`} key={plan.id}>
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
                  <button className="button" type="button" onClick={() => void applyPlan(plan)}>
                    Apply
                  </button>
                </div>
              </article>
            ))}
          </div>

          <div className="recommendation-detail">
            <div className="recommendation-detail-heading">
              <strong>{activePlan.title}</strong>
              <button className="button subtle" type="button" onClick={() => void resetDefaults()}>
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
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="consumer-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function pnlChartData(summary: DashboardSummaryView) {
  const snapshots = summary.economics.history.snapshots ?? [];
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
      trading: numberValue(summary.economics.trading.totalPnlUsd),
      net: numberValue(summary.economics.profitability.netAfterRecordedCostsUsd),
    },
  ];
}

function tickTimelineSteps(summary: DashboardSummaryView) {
  const latestRun = summary.operations.pipelineRuns[0];
  const stepByKey = new Map(
    (latestRun?.steps ?? []).map((step) => [step.key, step]),
  );
  return [
    {
      key: "data_fetch",
      label: "Data load",
      status: stepByKey.get("data_fetch")?.status ?? summary.marketData.status,
      message: stepByKey.get("data_fetch")?.message ?? `${summary.marketData.candidateCount ?? 0} candidates loaded`,
    },
    {
      key: "scanner",
      label: "Scan",
      status: stepByKey.get("scanner")?.status ?? summary.operations.scanner?.status ?? "waiting",
      message:
        stepByKey.get("scanner")?.message ??
        `${summary.operations.scanner?.acceptedCount ?? 0} accepted, ${summary.operations.scanner?.rejectedCount ?? 0} rejected`,
    },
    {
      key: "brain",
      label: "Reason",
      status: stepByKey.get("brain")?.status ?? summary.operations.reasoning?.status ?? "waiting",
      message:
        stepByKey.get("brain")?.message ??
        `${summary.operations.reasoning?.scoredCount ?? 0} scored, ${summary.operations.reasoning?.failedCount ?? 0} failed`,
    },
    {
      key: "execution",
      label: "Execute",
      status: stepByKey.get("execution")?.status ?? summary.operations.execution?.status ?? "waiting",
      message:
        stepByKey.get("execution")?.message ??
        `${summary.operations.execution?.submittedCount ?? 0} submitted, ${summary.operations.execution?.simulatedCount ?? 0} simulated`,
    },
    {
      key: "exit",
      label: "Exit",
      status: stepByKey.get("exit")?.status ?? summary.operations.exit?.status ?? "waiting",
      message:
        stepByKey.get("exit")?.message ??
        `${summary.operations.exit?.triggeredCount ?? 0} exit checks triggered`,
    },
  ].map((step) => ({ ...step, tone: statusTone(step.status) }));
}

function lastTickResult(summary: DashboardSummaryView) {
  const latestRun = summary.operations.pipelineRuns[0];
  const execution = summary.operations.execution;
  const scanner = summary.operations.scanner;
  const reasoning = summary.operations.reasoning;
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
    detail: summary.operations.tickSummary?.summaryMarkdown
      ? markdownLines(summary.operations.tickSummary.summaryMarkdown)[0]
      : "No execution intent was submitted in the latest tick.",
    status: latestRun?.status ?? "idle",
    tone: "waiting" as const,
    label: "Monitoring",
  };
}

function recommendationPlans(
  settings: Record<string, unknown>,
  dailySummary: TickSummaryView,
  summary: DashboardSummaryView,
): RecommendationPlan[] {
  const context = recommendationContext(dailySummary, summary);
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

function recommendationContext(dailySummary: TickSummaryView, summary: DashboardSummaryView) {
  const text = [
    dailySummary.summaryMarkdown,
    ...(dailySummary.keyEvents ?? []),
    ...(dailySummary.warnings ?? []),
    summary.operations.scanner?.message ?? "",
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
    return "not generated";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function nextConfigVersion(currentVersion: string): string {
  const match = currentVersion.match(/^(.*?)(\d+)$/);
  if (!match) {
    return `${currentVersion || "v"}-next`;
  }
  return `${match[1]}${Number(match[2]) + 1}`;
}
