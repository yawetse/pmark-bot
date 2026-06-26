"use client";

// REQ: REQ-UI-004, REQ-UI-010, REQ-CMP-002, REQ-OBS-005

import { useState } from "react";

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { dashboardApi } from "@/lib/api";

type AiProviderCostView = {
  provider: string;
  models: string[];
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  costUsd: string;
  budgetUsd: string;
  events: number;
  importedEvents: number;
  estimatedEvents: number;
  usageSources: string[];
  costSources: string[];
  latestAt?: string | null;
  latestImportStatus: string;
  latestImportMessage?: string | null;
};

type AiUsageImportRunView = {
  id: string;
  environment: string;
  provider: string;
  status: string;
  source: string;
  periodStart?: string | null;
  periodEnd?: string | null;
  importedCount: number;
  errorCode?: string | null;
  message?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  createdAt?: string | null;
};

type EconomicsSnapshotView = {
  id: string;
  environment: string;
  monthKey: string;
  createdAt?: string | null;
  tradingPnlUsd: string;
  aiCostUsd: string;
  aiPromptTokens: number;
  aiCompletionTokens: number;
  aiTotalTokens: number;
  awsDailyCostUsd: string;
  awsMonthToDateCostUsd: string;
  awsSource: string;
  awsScope: string;
  awsEstimated: boolean;
  netAfterRecordedCostsUsd: string;
  status: string;
};

export type EconomicsSummaryView = {
  environment: string;
  generatedAt: string;
  trading: {
    realizedPnlUsd: string;
    unrealizedPnlUsd: string;
    totalPnlUsd: string;
    openPositions: number;
    closedPositions: number;
    orderEvents: number;
  };
  ai: {
    providers: AiProviderCostView[];
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    totalCostUsd: string;
    source: string;
    freshness: {
      latestUsageAt?: string | null;
      latestImportAt?: string | null;
      status: string;
    };
    imports: {
      source: string;
      count: number;
      runs: AiUsageImportRunView[];
    };
    errorState: {
      status: string;
      message?: string | null;
      latestRunId?: string | null;
      errorCode?: string | null;
    };
  };
  aws: {
    monthlyInfraCostUsd: string;
    monthToDateCostUsd: string;
    dailyInfraCostEstimateUsd: string;
    dailyInfraCostUsd: string;
    fallbackMonthlyCostUsd: string;
    fallbackDailyCostUsd: string;
    source: string;
    scope: string;
    periodStart: string | null;
    periodEnd: string | null;
    monthPeriodStart: string | null;
    monthPeriodEnd: string | null;
    estimated: boolean;
    message: string;
  };
  profitability: {
    netAfterRecordedCostsUsd: string;
    status: "profitable" | "losing" | "flat";
    costBasis: string;
  };
  history: {
    source: string;
    stored: boolean;
    latestSnapshotId: string | null;
    monthKey: string;
    snapshotsThisMonth: number;
    snapshots: EconomicsSnapshotView[];
    message: string;
  };
};

export function EconomicsPanel({ economics }: { economics: EconomicsSummaryView }) {
  const [importRuns, setImportRuns] = useState<AiUsageImportRunView[]>(economics.ai.imports?.runs ?? []);
  const [importState, setImportState] = useState<
    | { status: "idle" }
    | { status: "submitting"; provider: string }
    | { status: "done"; message: string }
    | { status: "error"; message: string }
  >({ status: "idle" });
  const providerColumns: DashboardGridColumn<AiProviderCostView>[] = [
    { field: "provider", headerName: "Provider", minWidth: 140 },
    {
      field: "models",
      headerName: "Models",
      minWidth: 180,
      valueGetter: (params) => params.data?.models?.join(", ") ?? "",
    },
    {
      field: "totalTokens",
      headerName: "Tokens",
      minWidth: 140,
      valueFormatter: (params) => formatNumber(Number(params.value ?? 0)),
    },
    {
      field: "costUsd",
      headerName: "Cost",
      minWidth: 120,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    {
      field: "budgetUsd",
      headerName: "Budget",
      minWidth: 120,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    { field: "events", headerName: "Events", minWidth: 120 },
    { field: "importedEvents", headerName: "Imported", minWidth: 120 },
    { field: "estimatedEvents", headerName: "Estimated", minWidth: 120 },
    {
      field: "usageSources",
      headerName: "Usage source",
      minWidth: 180,
      valueGetter: (params) => params.data?.usageSources?.join(", ") ?? "",
    },
    {
      field: "costSources",
      headerName: "Cost source",
      minWidth: 180,
      valueGetter: (params) => params.data?.costSources?.join(", ") ?? "",
    },
    { field: "latestImportStatus", headerName: "Import status", minWidth: 150 },
  ];
  const importColumns: DashboardGridColumn<AiUsageImportRunView>[] = [
    { field: "provider", headerName: "Provider", minWidth: 120 },
    { field: "status", headerName: "Status", minWidth: 130 },
    { field: "importedCount", headerName: "Rows", minWidth: 110 },
    { field: "source", headerName: "Source", minWidth: 220 },
    { field: "errorCode", headerName: "Error", minWidth: 180 },
    { field: "message", headerName: "Message", minWidth: 260 },
    { field: "completedAt", headerName: "Completed", minWidth: 190 },
  ];
  const historyColumns: DashboardGridColumn<EconomicsSnapshotView>[] = [
    { field: "createdAt", headerName: "Snapshot", minWidth: 190 },
    {
      field: "aiTotalTokens",
      headerName: "Tokens",
      minWidth: 120,
      valueFormatter: (params) => formatNumber(Number(params.value ?? 0)),
    },
    {
      field: "aiCostUsd",
      headerName: "AI cost",
      minWidth: 120,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    {
      field: "awsDailyCostUsd",
      headerName: "AWS daily",
      minWidth: 130,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    {
      field: "tradingPnlUsd",
      headerName: "Trading P&L",
      minWidth: 140,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    {
      field: "netAfterRecordedCostsUsd",
      headerName: "Net",
      minWidth: 120,
      valueFormatter: (params) => formatUsd(String(params.value ?? "0")),
    },
    { field: "awsSource", headerName: "AWS source", minWidth: 190 },
    { field: "status", headerName: "Status", minWidth: 120 },
  ];

  async function triggerProviderImport(provider: string) {
    setImportState({ status: "submitting", provider });
    const result = await dashboardApi<AiUsageImportRunView>("economics/ai-usage-import", {
      method: "POST",
      body: JSON.stringify({ environment: economics.environment, provider }),
    });
    if (!result.ok) {
      setImportState({ status: "error", message: result.message });
      return;
    }
    setImportRuns((current) => [result.data, ...current.filter((run) => run.id !== result.data.id)]);
    setImportState({ status: "done", message: result.data.message ?? "Provider usage import finished." });
  }

  return (
    <section className="operator-panel span-2" aria-labelledby="economics-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Profitability</p>
          <h2 id="economics-title">Costs and P&L</h2>
        </div>
        <span className={`status ${economics.profitability.status === "losing" ? "blocked" : "ok"}`}>
          {economics.profitability.status}
        </span>
      </div>
      <div className="metric-grid compact">
        <Metric label="Trading P&L" value={formatUsd(economics.trading.totalPnlUsd)} />
        <Metric label="AI cost" value={formatUsd(economics.ai.totalCostUsd)} />
        <Metric label="AWS daily cost" value={formatUsd(economics.aws.dailyInfraCostEstimateUsd)} />
        <Metric label="Net after costs" value={formatUsd(economics.profitability.netAfterRecordedCostsUsd)} />
      </div>
      <div className="economics-grid">
        <div className="economics-block">
          <h3>Token spend</h3>
          <div className="metric-strip">
            <Metric label="Prompt tokens" value={formatNumber(economics.ai.promptTokens)} />
            <Metric label="Completion tokens" value={formatNumber(economics.ai.completionTokens)} />
            <Metric label="Total tokens" value={formatNumber(economics.ai.totalTokens)} />
            <Metric label="Freshness" value={economics.ai.freshness?.status ?? "unknown"} />
          </div>
          <p className="panel-note">
            Latest usage: {formatDateTime(economics.ai.freshness?.latestUsageAt)}.
            Latest provider import: {formatDateTime(economics.ai.freshness?.latestImportAt)}.
            Import state: {economics.ai.errorState?.status ?? "unknown"}.
          </p>
        </div>
        <div className="economics-block">
          <h3>AWS billing</h3>
          <div className="metric-strip">
            <Metric label="MTD cost" value={formatUsd(economics.aws.monthToDateCostUsd)} />
            <Metric label="Scope" value={economics.aws.scope} />
            <Metric label="Period" value={formatPeriod(economics.aws.periodStart, economics.aws.periodEnd)} />
            <Metric label="Snapshots" value={String(economics.history.snapshotsThisMonth)} />
          </div>
          <p className="panel-note">{economics.aws.message}</p>
        </div>
      </div>
      <div className="economics-grid">
        <div className="economics-block">
          <h3>Trading</h3>
          <div className="metric-strip">
            <Metric label="Realized" value={formatUsd(economics.trading.realizedPnlUsd)} />
            <Metric label="Unrealized" value={formatUsd(economics.trading.unrealizedPnlUsd)} />
            <Metric label="Orders" value={String(economics.trading.orderEvents)} />
          </div>
        </div>
      </div>
      <DashboardDataGrid
        rows={economics.ai.providers}
        columns={providerColumns}
        emptyTitle="No token spend recorded"
        emptyBody="The backend has not recorded provider token usage rows yet."
        getRowId={(provider) => provider.provider}
        pageSize={10}
        searchPlaceholder="Filter providers"
      />
      <div className="economics-block">
        <h3>Provider usage imports</h3>
        <div className="manual-run-actions" role="group" aria-label="AI usage provider imports">
          {["openai", "claude"].map((provider) => (
            <button
              className="button"
              disabled={importState.status === "submitting"}
              key={provider}
              type="button"
              onClick={() => triggerProviderImport(provider)}
            >
              {importState.status === "submitting" && importState.provider === provider
                ? "Importing"
                : `Import ${provider}`}
            </button>
          ))}
        </div>
        {importState.status === "done" ? <p className="status-message">{importState.message}</p> : null}
        {importState.status === "error" ? <p className="status-message">{importState.message}</p> : null}
      </div>
      <DashboardDataGrid
        rows={importRuns}
        columns={importColumns}
        emptyTitle="No provider usage imports"
        emptyBody="Provider-side token usage imports will appear here after they run."
        getRowId={(run) => run.id}
        pageSize={10}
        searchPlaceholder="Filter provider usage imports"
      />
      <DashboardDataGrid
        rows={economics.history.snapshots ?? []}
        columns={historyColumns}
        emptyTitle="No cost history"
        emptyBody="Economics snapshots will appear after summary reads store monthly profitability history."
        getRowId={(snapshot) => snapshot.id}
        pageSize={10}
        searchPlaceholder="Filter cost history"
      />
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

function formatUsd(value: string): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "$0.00";
  }
  return new Intl.NumberFormat("en-US", {
    currency: "USD",
    style: "currency",
  }).format(parsed);
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatPeriod(start: string | null, end: string | null): string {
  if (!start || !end) {
    return "fallback";
  }
  return `${start} to ${end}`;
}

function formatDateTime(value?: string | null): string {
  if (!value) {
    return "not recorded";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "not recorded";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}
