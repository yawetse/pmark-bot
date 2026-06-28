// REQ: REQ-UI-004, REQ-UI-008, REQ-OBS-005

type DashboardLoadingPanelsProps = {
  title?: string;
  panelCount?: number;
};

export function DashboardLoadingPanels({
  title = "Loading dashboard",
  panelCount = 4,
}: DashboardLoadingPanelsProps) {
  return (
    <div className="page-stack" aria-busy="true" aria-live="polite">
      <DashboardPanelLoading
        eyebrow="Dashboard"
        title={title}
        metricCount={4}
        rowCount={2}
        wide
      />
      <div className="operator-grid">
        {Array.from({ length: panelCount }).map((_, index) => (
          <DashboardPanelLoading
            eyebrow={index === 0 ? "Current state" : "Panel"}
            key={index}
            title={index === 0 ? "Loading controls" : "Loading data"}
            metricCount={index === 0 ? 3 : 2}
            rowCount={index === 0 ? 3 : 2}
            wide={index === 0}
          />
        ))}
      </div>
    </div>
  );
}

export function DashboardPanelLoading({
  eyebrow,
  title,
  metricCount = 3,
  rowCount = 3,
  wide = false,
}: {
  eyebrow: string;
  title: string;
  metricCount?: number;
  rowCount?: number;
  wide?: boolean;
}) {
  return (
    <section
      className={`operator-panel loading-panel ${wide ? "span-2 wide-panel" : ""}`.trim()}
      aria-label={title}
    >
      <div className="panel-heading">
        <div>
          <p className="section-label">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        <span className="status waiting">loading</span>
      </div>
      <div className="metric-grid compact">
        {Array.from({ length: metricCount }).map((_, index) => (
          <div className="metric loading-metric" key={index}>
            <span className="loading-line short" />
            <strong className="loading-line" />
          </div>
        ))}
      </div>
      <div className="loading-line" />
      <div className="loading-line medium" />
      <div className="loading-row-list">
        {Array.from({ length: rowCount }).map((_, index) => (
          <div className="loading-row" key={index}>
            <span className="loading-dot" />
            <span className="loading-line" />
          </div>
        ))}
      </div>
    </section>
  );
}
