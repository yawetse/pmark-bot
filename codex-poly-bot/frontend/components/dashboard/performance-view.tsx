"use client";

import Link from "next/link";
import { ArrowRight, BarChart3, Bot, BriefcaseBusiness, CircleAlert, ExternalLink } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Disclosure } from "@/components/dashboard/dashboard-primitives";
import type { VenuePortfolioView } from "@/components/dashboard/venue-portfolio-panel";
import {
  buildPerformanceHeadline,
  buildPerformanceVenueRows,
} from "@/lib/dashboard-performance-view-model";
import { useDashboardRealtime, type DashboardRealtimeSnapshot } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-013, REQ-UI-016, REQ-UI-021, REQ-UI-025, REQ-CMP-004, REQ-CMP-005

export function PerformanceView({
  portfolio,
  loadError,
}: {
  portfolio?: VenuePortfolioView;
  loadError?: string;
}) {
  const [currentPortfolio, setCurrentPortfolio] = useState(portfolio);
  const [portfolioError, setPortfolioError] = useState(loadError);
  const onSnapshot = useCallback((snapshot: DashboardRealtimeSnapshot) => {
    if (snapshot.portfolio) {
      setCurrentPortfolio(snapshot.portfolio);
      setPortfolioError(undefined);
    }
  }, []);
  useDashboardRealtime({ onSnapshot });
  const headline = useMemo(() => buildPerformanceHeadline(currentPortfolio), [currentPortfolio]);
  const marketRows = useMemo(() => buildPerformanceVenueRows(currentPortfolio), [currentPortfolio]);

  return (
    <div className="ia-page performance-page" aria-labelledby="performance-title">
      <header className="ia-page-heading">
        <div>
          <p className="section-label">Performance</p>
          <h1 id="performance-title">Confirmed trading results</h1>
          <p>Venue-confirmed balances, positions, and fills. Practice and unfilled orders are excluded.</p>
        </div>
        <span className={`ia-update-chip ${currentPortfolio?.freshness.status ?? "idle"}`}>
          <span aria-hidden="true" /> {currentPortfolio?.freshness.message ?? "Waiting for confirmed data"}
        </span>
      </header>

      {portfolioError ? <p className="ia-degraded-message" role="status"><CircleAlert aria-hidden="true" size={16} /> Performance data is unavailable. {portfolioError}</p> : null}

      <section className="performance-metrics" aria-label="Confirmed performance metrics">
        <PerformanceMetric label="Equity" value={formatUsd(currentPortfolio?.overall.accountValueUsd)} detail="Confirmed account value" />
        <PerformanceMetric label="Realized P&L" value={formatUsd(currentPortfolio?.overall.realizedPnlUsd)} detail="Closed confirmed outcomes" tone={pnlTone(currentPortfolio?.overall.realizedPnlUsd)} />
        <PerformanceMetric label="Unrealized P&L" value={formatUsd(currentPortfolio?.overall.unrealizedPnlUsd)} detail="Open confirmed positions" tone={pnlTone(currentPortfolio?.overall.unrealizedPnlUsd)} />
        <PerformanceMetric label="Open positions" value={formatCount(currentPortfolio?.overall.openPositions)} detail="Venue-confirmed holdings" />
        <PerformanceMetric label="Win rate" value={formatRate(headline.winRate)} detail={headline.winRateDetail} />
        <PerformanceMetric label="Trades" value={formatCount(headline.tradeCount)} detail="Venue-confirmed fills" />
      </section>

      <section className="ia-panel" aria-labelledby="by-market-title">
        <div className="ia-section-heading">
          <div><p className="section-label">Breakdown</p><h2 id="by-market-title">By market</h2></div>
          <span className={`status ${currentPortfolio?.overall.status === "ready" ? "ok" : currentPortfolio?.overall.status === "stale" ? "waiting" : "blocked"}`}>{currentPortfolio?.overall.status ?? "unavailable"}</span>
        </div>
        <div className="performance-table-wrap">
          <table className="performance-table">
            <thead><tr><th>Market</th><th>Trades</th><th>Win rate</th><th>P&L</th></tr></thead>
            <tbody>
              {marketRows.length ? marketRows.map((row) => (
                <tr key={row.market}><th scope="row"><strong>{row.market}</strong><span>{row.detail}</span></th><td>{formatCount(row.trades)}</td><td>{formatRate(row.winRate)}</td><td className={pnlTone(row.pnlUsd)}>{formatUsd(row.pnlUsd)}</td></tr>
              )) : <tr><td className="performance-empty-cell" colSpan={4}>No venue-confirmed market results are available.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ia-panel performance-records" aria-labelledby="confirmed-records-title">
        <div className="ia-section-heading"><div><p className="section-label">Evidence</p><h2 id="confirmed-records-title">Confirmed records</h2></div><BriefcaseBusiness aria-hidden="true" size={20} /></div>
        <Disclosure title={`Open holdings (${currentPortfolio?.positions.length ?? 0})`}>
          <div className="performance-table-wrap"><table className="performance-table compact"><thead><tr><th>Market</th><th>Venue</th><th>Value</th><th>P&L</th></tr></thead><tbody>
            {currentPortfolio?.positions.length ? currentPortfolio.positions.map((position) => <tr key={position.id}><th scope="row"><strong>{position.title}</strong><span>{position.outcome ?? position.instrumentId}</span></th><td>{venueLabel(position.venue)}</td><td>{formatUsd(position.marketValueUsd)}</td><td className={pnlTone(position.totalPnlUsd)}>{formatUsd(position.totalPnlUsd)}</td></tr>) : <tr><td className="performance-empty-cell" colSpan={4}>No confirmed open holdings.</td></tr>}
          </tbody></table></div>
        </Disclosure>
        <Disclosure title={`Confirmed fills (${currentPortfolio?.fills.length ?? 0})`}>
          <div className="performance-table-wrap"><table className="performance-table compact"><thead><tr><th>Market</th><th>Side</th><th>Notional</th><th>Executed</th></tr></thead><tbody>
            {currentPortfolio?.fills.length ? currentPortfolio.fills.map((fill) => <tr key={fill.id}><th scope="row"><strong>{fill.title}</strong><span>{venueLabel(fill.venue)}</span></th><td>{fill.side}</td><td>{formatUsd(fill.notionalUsd)}</td><td>{formatDate(fill.executedAt)}</td></tr>) : <tr><td className="performance-empty-cell" colSpan={4}>No confirmed fills.</td></tr>}
          </tbody></table></div>
        </Disclosure>
      </section>

      <div className="ia-context-links">
        <Link href="/dashboard/comparison"><BarChart3 aria-hidden="true" size={17} /><span><strong>Compare AI models</strong><small>Review provider and venue metrics with caveats.</small></span><ArrowRight aria-hidden="true" size={15} /></Link>
        <Link href="/dashboard/models"><Bot aria-hidden="true" size={17} /><span><strong>AI model detail</strong><small>Open Claude and OpenAI records separately.</small></span><ExternalLink aria-hidden="true" size={15} /></Link>
      </div>
    </div>
  );
}

function PerformanceMetric({ label, value, detail, tone = "" }: { label: string; value: string; detail: string; tone?: string }) {
  return <article className="performance-metric"><span>{label}</span><strong className={tone}>{value}</strong><small>{detail}</small></article>;
}

function formatRate(value: number | null): string { return value === null ? "Unavailable" : new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 }).format(value); }
function formatUsd(value: string | null | undefined): string { if (value === null || value === undefined || value === "") return "Unavailable"; const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(number) : "Unavailable"; }
function formatCount(value: number | null | undefined): string { return value === null || value === undefined ? "Unavailable" : value.toLocaleString(); }
function pnlTone(value: string | null | undefined): string { const number = Number(value); return !Number.isFinite(number) || number === 0 ? "" : number > 0 ? "positive" : "negative"; }
function venueLabel(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatDate(value: string | null | undefined): string { if (!value) return "Unavailable"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "Unavailable" : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(date); }
