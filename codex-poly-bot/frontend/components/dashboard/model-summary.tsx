// REQ: REQ-UI-010

export type ModelProviderName = "claude" | "openai";

type ModelSummary = {
  provider: ModelProviderName;
  budgetUsd: string;
  pnlUsd: string;
  positions: string[];
  decisions: string[];
};

const MODEL_SUMMARIES: Record<ModelProviderName, ModelSummary> = {
  claude: {
    provider: "claude",
    budgetUsd: "20.00",
    pnlUsd: "0.00",
    positions: ["No open Claude positions"],
    decisions: ["No Claude decisions in current window"],
  },
  openai: {
    provider: "openai",
    budgetUsd: "20.00",
    pnlUsd: "0.00",
    positions: ["No open OpenAI positions"],
    decisions: ["No OpenAI decisions in current window"],
  },
};

export function ModelSummaryPanel({ provider }: { provider: ModelProviderName }) {
  const summary = MODEL_SUMMARIES[provider];
  return (
    <section className="panel">
      <h1>{provider === "claude" ? "Claude" : "OpenAI"}</h1>
      <div className="metric-grid">
        <Metric label="Budget" value={`$${summary.budgetUsd}`} />
        <Metric label="P&L" value={`$${summary.pnlUsd}`} />
        <Metric label="Positions" value={String(summary.positions.length)} />
        <Metric label="Decisions" value={String(summary.decisions.length)} />
      </div>
      <h2>Positions</h2>
      <ul className="status-list">
        {summary.positions.map((position) => (
          <li key={position}>
            <span>{position}</span>
            <span className="status ok">provider-specific</span>
          </li>
        ))}
      </ul>
      <h2>Decisions</h2>
      <ul className="status-list">
        {summary.decisions.map((decision) => (
          <li key={decision}>
            <span>{decision}</span>
            <span className="status ok">provider-specific</span>
          </li>
        ))}
      </ul>
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
