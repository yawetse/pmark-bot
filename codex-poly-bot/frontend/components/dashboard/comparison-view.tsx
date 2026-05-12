// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

type ComparisonMetricView = {
  group: string;
  metric: string;
  value: string | null;
  caveat: string | null;
};

const COMPARISON_METRICS: ComparisonMetricView[] = [
  {
    group: "Claude / Polymarket US",
    metric: "realized_pnl",
    value: null,
    caveat: "No eligible data",
  },
  {
    group: "OpenAI / Alpaca",
    metric: "return_to_risk",
    value: null,
    caveat: "Drawdown is zero",
  },
];

export function ComparisonView() {
  return (
    <section className="panel">
      <h1>Comparison</h1>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Group</th>
              <th>Metric</th>
              <th>Value</th>
              <th>Caveat</th>
            </tr>
          </thead>
          <tbody>
            {COMPARISON_METRICS.map((metric) => (
              <tr key={`${metric.group}-${metric.metric}`}>
                <td>{metric.group}</td>
                <td>{metric.metric}</td>
                <td>{metric.value ?? "Unavailable"}</td>
                <td>{metric.caveat ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
