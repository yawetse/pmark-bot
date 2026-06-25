// REQ: REQ-UI-010

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";

export type ModelProviderName = "claude" | "openai";

type ModelRow = Record<string, unknown>;

export type ModelSummary = {
  provider: ModelProviderName;
  budget?: {
    used_usd?: string;
    limit_usd?: string;
  };
  pnl?: string;
  positions?: ModelRow[];
  decisions?: ModelRow[];
  orders?: ModelRow[];
  degraded_sections?: string[];
};

const EMPTY_SUMMARY: Record<ModelProviderName, ModelSummary> = {
  claude: { provider: "claude", budget: { used_usd: "0.00", limit_usd: "0.00" }, pnl: "0.00" },
  openai: { provider: "openai", budget: { used_usd: "0.00", limit_usd: "0.00" }, pnl: "0.00" },
};

export function ModelSummaryPanel({
  provider,
  summary = EMPTY_SUMMARY[provider],
  loadError,
}: {
  provider: ModelProviderName;
  summary?: ModelSummary;
  loadError?: string;
}) {
  const positions = summary.positions ?? [];
  const decisions = summary.decisions ?? [];
  const orders = summary.orders ?? [];

  return (
    <section className="panel wide-panel">
      <div className="panel-heading">
        <div>
          <p className="section-label">Model provider</p>
          <h1>{provider === "claude" ? "Claude" : "OpenAI"}</h1>
        </div>
        {loadError ? <span className="status blocked">api unavailable</span> : null}
      </div>
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <div className="metric-grid">
        <Metric
          label="Budget used"
          value={`$${summary.budget?.used_usd ?? "0.00"} / $${summary.budget?.limit_usd ?? "0.00"}`}
        />
        <Metric label="P&L" value={`$${summary.pnl ?? "0.00"}`} />
        <Metric label="Positions" value={String(positions.length)} />
        <Metric label="Decisions" value={String(decisions.length)} />
      </div>

      <h2>Positions</h2>
      <ModelRows
        emptyTitle="No positions"
        emptyBody="No open or closed positions have been recorded for this provider."
        rows={positions}
      />

      <h2>Decisions</h2>
      <ModelRows
        emptyTitle="No decisions"
        emptyBody="No scored decisions have been recorded for this provider."
        rows={decisions}
      />

      <h2>Orders</h2>
      <ModelRows
        emptyTitle="No orders"
        emptyBody="No simulated or live orders have been recorded for this provider."
        rows={orders}
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

function ModelRows({
  rows,
  emptyTitle,
  emptyBody,
}: {
  rows: ModelRow[];
  emptyTitle: string;
  emptyBody: string;
}) {
  const normalizedRows = rows.map(normalizeRow);
  const columns = columnsForRows(normalizedRows);

  return (
    <DashboardDataGrid
      rows={normalizedRows}
      columns={columns}
      emptyTitle={emptyTitle}
      emptyBody={emptyBody}
      getRowId={(row) => row.id || row.positionId || JSON.stringify(row)}
      searchPlaceholder="Filter rows"
    />
  );
}

function normalizeRow(row: ModelRow): Record<string, string> {
  return Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key, formatCellValue(value)]),
  );
}

function columnsForRows(rows: Record<string, string>[]): DashboardGridColumn<Record<string, string>>[] {
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return keys.map((key) => ({
    field: key,
    headerName: titleFromKey(key),
    minWidth: key.toLowerCase().includes("message") ? 240 : 140,
  }));
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function titleFromKey(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (value) => value.toUpperCase());
}
