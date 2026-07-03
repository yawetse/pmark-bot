// REQ: REQ-UI-004, REQ-OBS-005

export type StatusItem = {
  label: string;
  value: string;
  state: "ok" | "blocked";
};

export const DEFAULT_STATUS_ITEMS: StatusItem[] = [
  { label: "Venue", value: "Polymarket US disabled", state: "ok" },
  { label: "Wallet", value: "Public identifiers only", state: "ok" },
  { label: "Ingestion", value: "Awaiting worker heartbeat", state: "blocked" },
  { label: "Trading loop", value: "Simulation", state: "ok" },
  { label: "Notification", value: "Not configured", state: "blocked" },
  { label: "Audit", value: "Ready", state: "ok" },
  { label: "Health", value: "API reachable", state: "ok" },
];

export function StatusOverview({ items = DEFAULT_STATUS_ITEMS }: { items?: StatusItem[] }) {
  return (
    <section className="panel">
      <h2>Status</h2>
      <ul className="status-list">
        {items.map((item) => (
          <li key={item.label}>
            <span>{item.label}</span>
            <span>
              {item.value} <span className={`status ${item.state}`}>{item.state}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
