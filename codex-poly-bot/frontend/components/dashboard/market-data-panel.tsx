// REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005

export type MarketDataCandidateView = {
  id: string;
  venue: string;
  symbol?: string | null;
  market?: string | null;
  price?: string | null;
  liquidity?: string | null;
  spread?: string | null;
  state: string;
  pulledAt?: string | null;
};

export type MarketDataPullView = {
  id?: string | null;
  environment: string;
  venue: string;
  status: string;
  trigger: string;
  source: string;
  lastPulledAt?: string | null;
  candidateCount: number;
  candidates: MarketDataCandidateView[];
  message: string;
};

export function MarketDataPanel({
  marketData,
  timeZone,
}: {
  marketData: MarketDataPullView;
  timeZone: string;
}) {
  return (
    <section className="operator-panel span-2" aria-labelledby="market-data-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Market data</p>
          <h2 id="market-data-title">Latest pull</h2>
        </div>
        <span className={`status ${marketData.candidateCount > 0 ? "ok" : "idle"}`}>
          {marketData.status}
        </span>
      </div>
      <div className="metric-grid compact">
        <Metric label="Venue" value={marketData.venue} />
        <Metric label="Candidates" value={String(marketData.candidateCount)} />
        <Metric label="Trigger" value={marketData.trigger} />
        <Metric label="Pulled" value={formatDateTime(marketData.lastPulledAt, timeZone)} />
      </div>
      <p className="panel-note">{marketData.message}</p>
      {marketData.candidates.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Venue</th>
                <th>Price</th>
                <th>Liquidity</th>
                <th>Spread</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {marketData.candidates.map((candidate) => (
                <tr key={candidate.id}>
                  <td>{candidate.market ?? candidate.symbol ?? candidate.id}</td>
                  <td>{candidate.venue}</td>
                  <td>{candidate.price ?? ""}</td>
                  <td>{candidate.liquidity ?? ""}</td>
                  <td>{candidate.spread ?? ""}</td>
                  <td>{candidate.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state">
          <strong>No candidates recorded</strong>
          <p>The dashboard has not received a candidate snapshot for the selected environment.</p>
        </div>
      )}
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

function formatDateTime(value: string | null | undefined, timeZone: string): string {
  if (!value) {
    return "not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "not recorded";
  }
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone,
  }).format(date);
}
