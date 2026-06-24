// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

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
      {summary.metrics.length === 0 ? (
        <div className="empty-state">
          <strong>No comparison metrics yet</strong>
          <p>
            The app needs recorded decisions, orders, position changes, and model
            costs before it can calculate P&L, win rate, drawdown, or return to risk.
          </p>
        </div>
      ) : (
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
              {summary.metrics.map((metric) => (
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
      )}
    </section>
  );
}
