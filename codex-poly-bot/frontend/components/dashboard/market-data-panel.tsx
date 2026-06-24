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
  errorCode?: string | null;
  venues?: MarketDataPullView[];
};

export function MarketDataPanel({
  marketData,
  timeZone,
}: {
  marketData: MarketDataPullView;
  timeZone: string;
}) {
  const venuePulls = marketData.venues?.length ? marketData.venues : [marketData];
  const candidates = venuePulls.flatMap((venue) => venue.candidates);
  const latestPulledAt = latestTimestamp(venuePulls);
  return (
    <section className="operator-panel span-2" aria-labelledby="market-data-title">
      <div className="panel-heading">
        <div>
          <p className="section-label">Market data</p>
          <h2 id="market-data-title">Latest pull</h2>
        </div>
        <span className={`status ${statusClass(marketData)}`}>
          {marketData.status}
        </span>
      </div>
      <div className="metric-grid compact">
        <Metric label="Venues" value={venuePulls.map((venue) => venue.venue).join(", ")} />
        <Metric label="Candidates" value={String(candidates.length)} />
        <Metric label="Trigger" value={marketData.trigger} />
        <Metric label="Pulled" value={formatDateTime(latestPulledAt, timeZone)} />
      </div>
      <p className="panel-note">{marketData.message}</p>
      <div className="market-venue-grid">
        {venuePulls.map((venuePull) => (
          <article className="market-venue-card" key={venuePull.venue}>
            <div className="market-venue-heading">
              <strong>{venuePull.venue}</strong>
              <span className={`status ${statusClass(venuePull)}`}>{venuePull.status}</span>
            </div>
            <dl>
              <div>
                <dt>Candidates</dt>
                <dd>{venuePull.candidateCount}</dd>
              </div>
              <div>
                <dt>Trigger</dt>
                <dd>{venuePull.trigger}</dd>
              </div>
              <div>
                <dt>Pulled</dt>
                <dd>{formatDateTime(venuePull.lastPulledAt, timeZone)}</dd>
              </div>
            </dl>
            <p>{venuePull.message}</p>
          </article>
        ))}
      </div>
      {candidates.length > 0 ? (
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
              {candidates.map((candidate) => (
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
          <p>The dashboard has not received priced candidate rows for the selected environment.</p>
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

function latestTimestamp(venuePulls: MarketDataPullView[]): string | null {
  const timestamps = venuePulls
    .map((venuePull) => venuePull.lastPulledAt)
    .filter((value): value is string => Boolean(value));
  if (timestamps.length === 0) {
    return null;
  }
  return timestamps.sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0];
}

function statusClass(marketData: MarketDataPullView): "ok" | "idle" | "blocked" {
  if (
    marketData.status === "failed" ||
    marketData.status === "blocked" ||
    marketData.status === "rate_limited"
  ) {
    return "blocked";
  }
  if (marketData.status === "idle" || marketData.status === "empty") {
    return "idle";
  }
  return marketData.id || marketData.candidateCount > 0 ? "ok" : "idle";
}
