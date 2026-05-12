// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

const ORDER_STATES = ["refused", "submitted", "filled", "canceled", "failed", "unknown"] as const;

type OrderState = (typeof ORDER_STATES)[number];

type OrderEventView = {
  id: string;
  state: OrderState;
  venue: string;
  provider: string;
};

const ORDER_EVENTS: OrderEventView[] = ORDER_STATES.map((state) => ({
  id: `order-${state}`,
  provider: state === "submitted" || state === "filled" ? "openai" : "claude",
  state,
  venue: state === "unknown" ? "alpaca" : "polymarket_us",
}));

export function OperationsView() {
  return (
    <section className="panel">
      <h1>Operations</h1>
      <div className="metric-grid">
        <Metric label="Kill switch" value="inactive" />
        <Metric label="Open orders" value="0" />
        <Metric label="Cancel progress" value="0 / 0" />
        <Metric label="Manual review" value="none" />
      </div>
      <ul className="status-list">
        <li>
          <span>Degraded venue status</span>
          <span className="status ok">none</span>
        </li>
        <li>
          <span>Manual-review state</span>
          <span className="status ok">clear</span>
        </li>
      </ul>
      <h2>Order Events</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Order</th>
              <th>State</th>
              <th>Venue</th>
              <th>Provider</th>
            </tr>
          </thead>
          <tbody>
            {ORDER_EVENTS.map((event) => (
              <tr key={event.id}>
                <td>{event.id}</td>
                <td>{event.state}</td>
                <td>{event.venue}</td>
                <td>{event.provider}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
