"use client";

// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type ComparisonMetricView = {
  group: string;
  metric: string;
  value: string | null;
  caveat: string | null;
};

export type ComparisonSummaryView = {
  metrics: ComparisonMetricView[];
  degraded_sections?: string[];
};

export function ComparisonView({
  summary = { metrics: [] },
  loadError,
}: {
  summary?: ComparisonSummaryView;
  loadError?: string;
}) {
  const metricValue = (name: string) =>
    summary.metrics.find((metric) => metric.metric.toLowerCase().includes(name))?.value ??
    "Unavailable";
  const chartData = summary.metrics
    .map((metric) => ({
      caveat: metric.caveat,
      group: metric.group,
      metric: metric.metric,
      value: parseMetricValue(metric.value),
    }))
    .filter((metric) => metric.value !== null)
    .slice(0, 8);
  const columns: DashboardGridColumn<ComparisonMetricView>[] = [
    { field: "group", headerName: "Group", minWidth: 180 },
    { field: "metric", headerName: "Metric", minWidth: 180 },
    {
      field: "value",
      headerName: "Value",
      minWidth: 140,
      valueFormatter: (params) => params.value ?? "Unavailable",
    },
    { field: "caveat", headerName: "Caveat", minWidth: 240 },
  ];

  return (
    <section className="panel wide-panel">
      <div className="panel-heading">
        <div>
          <p className="section-label">Performance</p>
          <h1>Comparison</h1>
        </div>
        {loadError ? <span className="status blocked">api unavailable</span> : null}
      </div>
      <p className="panel-note">
        Compares Claude and OpenAI across venues once positions, fills, model cost,
        and drawdown records exist.
      </p>
      <div className="comparison-summary-grid" aria-label="Provider comparison summary">
        <div>
          <span>P&L</span>
          <strong>{metricValue("p&l")}</strong>
          <small>Provider return after recorded orders</small>
        </div>
        <div>
          <span>win rate</span>
          <strong>{metricValue("win")}</strong>
          <small>Completed trade outcomes</small>
        </div>
        <div>
          <span>drawdown</span>
          <strong>{metricValue("drawdown")}</strong>
          <small>Risk adjusted downside</small>
        </div>
        <div>
          <span>model cost</span>
          <strong>{metricValue("cost")}</strong>
          <small>Recorded provider spend</small>
        </div>
      </div>
      <div className="comparison-chart-panel" aria-label="Provider comparison chart">
        <div>
          <span>Metric chart</span>
          <strong>{chartData.length ? `${chartData.length} metrics` : "No numeric metrics"}</strong>
          <small>Numeric comparison values render here before exact caveats in the grid.</small>
        </div>
        {chartData.length ? (
          <div className="dashboard-chart">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData} margin={{ bottom: 0, left: 0, right: 8, top: 8 }}>
                <CartesianGrid stroke="var(--surface-strong)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="metric" tickLine={false} tickMargin={8} />
                <YAxis tickLine={false} width={42} />
                <Tooltip content={<ComparisonTooltip />} cursor={false} />
                <Bar dataKey="value" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="panel-note">No numeric comparison metrics are available yet.</p>
        )}
      </div>
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <DashboardDataGrid
        rows={summary.metrics}
        columns={columns}
        emptyTitle="No comparison metrics yet"
        emptyBody="The app needs recorded decisions, orders, position changes, and model costs before it can calculate P&L, win rate, drawdown, or return to risk."
        getRowId={(metric) => `${metric.group}-${metric.metric}`}
        title="Comparison detail"
        description="Use the grid for exact metric caveats after the summary indicates where to look."
        searchPlaceholder="Filter metrics"
      />
    </section>
  );
}

function ComparisonTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { caveat?: string | null; group?: string; metric?: string; value?: number | null } }>;
}) {
  if (!active || !payload?.length) {
    return null;
  }
  const row = payload[0]?.payload;
  if (!row) {
    return null;
  }
  return (
    <div className="chart-tooltip">
      <strong>{row.metric}</strong>
      <span>
        {row.group}: {row.value}
      </span>
      {row.caveat ? <small>{row.caveat}</small> : null}
    </div>
  );
}

function parseMetricValue(value: string | null): number | null {
  if (!value) {
    return null;
  }
  const parsed = Number(value.replace(/[$,%]/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}
