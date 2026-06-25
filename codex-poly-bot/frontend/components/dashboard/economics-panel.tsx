// REQ: REQ-UI-004, REQ-UI-010, REQ-CMP-002, REQ-OBS-005

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";

type AiProviderCostView = {
  provider: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  costUsd: string;
  budgetUsd: string;
  events: number;
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
    message: string;
  };
};

export function EconomicsPanel({ economics }: { economics: EconomicsSummaryView }) {
  const providerColumns: DashboardGridColumn<AiProviderCostView>[] = [
    { field: "provider", headerName: "Provider", minWidth: 140 },
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
  ];

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
          </div>
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
