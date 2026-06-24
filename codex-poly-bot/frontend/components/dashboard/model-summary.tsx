// REQ: REQ-UI-010

export type ModelProviderName = "claude" | "openai";

export type ModelSummary = {
  provider: ModelProviderName;
  budget?: {
    used_usd?: string;
    limit_usd?: string;
  };
  pnl?: string;
  positions?: unknown[];
  decisions?: unknown[];
  orders?: unknown[];
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
  rows: unknown[];
  emptyTitle: string;
  emptyBody: string;
}) {
  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <strong>{emptyTitle}</strong>
        <p>{emptyBody}</p>
      </div>
    );
  }

  return (
    <ul className="status-list">
      {rows.map((row, index) => (
        <li key={index}>
          <span>{formatRow(row)}</span>
          <span className="status ok">recorded</span>
        </li>
      ))}
    </ul>
  );
}

function formatRow(row: unknown): string {
  if (typeof row === "string") {
    return row;
  }
  if (row && typeof row === "object") {
    return JSON.stringify(row);
  }
  return String(row);
}
