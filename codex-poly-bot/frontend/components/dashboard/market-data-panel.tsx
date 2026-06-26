"use client";

// REQ: REQ-DAT-001, REQ-DAT-008, REQ-OBS-005

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { Disclosure } from "@/components/dashboard/dashboard-primitives";

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
  dataSource?: string | null;
  historyBarCount?: number | null;
  previousClose?: string | null;
  historyStart?: string | null;
  historyEnd?: string | null;
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
  const columns: DashboardGridColumn<MarketDataCandidateView>[] = [
    {
      field: "market",
      headerName: "Candidate",
      minWidth: 220,
      valueGetter: (params) => params.data?.market ?? params.data?.symbol ?? params.data?.id ?? "",
    },
    { field: "venue", headerName: "Venue", minWidth: 150 },
    { field: "price", headerName: "Price", minWidth: 120 },
    { field: "liquidity", headerName: "Liquidity", minWidth: 130 },
    { field: "spread", headerName: "Spread", minWidth: 120 },
    { field: "previousClose", headerName: "Prev Close", minWidth: 130 },
    { field: "historyBarCount", headerName: "Bars", minWidth: 100 },
    { field: "dataSource", headerName: "Source", minWidth: 170 },
    { field: "state", headerName: "State", minWidth: 140 },
    {
      field: "pulledAt",
      headerName: "Pulled",
      minWidth: 190,
      valueFormatter: (params) => formatDateTime(params.value, timeZone),
    },
  ];
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
      <Disclosure
        title={
          candidates.length === 1
            ? "View 1 candidate record"
            : `View ${candidates.length} candidate records`
        }
      >
        <DashboardDataGrid
          rows={candidates}
          columns={columns}
          emptyTitle="No candidates recorded"
          emptyBody="The dashboard has not received priced candidate rows for the selected environment."
          getRowId={(candidate) => candidate.id}
          title="Candidate records"
          description="Use the grid for exact pricing, liquidity, spread, history, source, and pull time."
          searchPlaceholder="Filter candidates"
        />
      </Disclosure>
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
