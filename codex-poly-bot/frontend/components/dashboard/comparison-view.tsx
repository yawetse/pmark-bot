// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";

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
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <DashboardDataGrid
        rows={summary.metrics}
        columns={columns}
        emptyTitle="No comparison metrics yet"
        emptyBody="The app needs recorded decisions, orders, position changes, and model costs before it can calculate P&L, win rate, drawdown, or return to risk."
        getRowId={(metric) => `${metric.group}-${metric.metric}`}
        searchPlaceholder="Filter metrics"
      />
    </section>
  );
}
