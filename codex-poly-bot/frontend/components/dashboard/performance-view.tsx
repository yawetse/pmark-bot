"use client";

import Link from "next/link";
import { ArrowRight, BarChart3, Bot, BriefcaseBusiness, CalendarClock, CircleAlert, ExternalLink, Landmark } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Disclosure } from "@/components/dashboard/dashboard-primitives";
import type { VenuePortfolioView } from "@/components/dashboard/venue-portfolio-panel";
import {
  buildPerformanceAccountBalances,
  buildPerformanceHeadline,
  buildPerformanceVenueRows,
} from "@/lib/dashboard-performance-view-model";
import { useDashboardRealtime, type DashboardRealtimeSnapshot } from "@/lib/use-dashboard-realtime";

// REQ: REQ-UI-013, REQ-UI-016, REQ-UI-021, REQ-UI-025, REQ-CMP-004, REQ-CMP-005

export type FundingHistoryView = {
  environment: string;
  interval: { startAt: string; endAt: string };
  cashFlows: Array<{
    id: string;
    venue: string;
    providers: string[];
    accountLabel: string;
    direction: "deposit" | "withdrawal";
    amountUsd: string;
    status: string;
    activityType: string;
    effectiveAt: string;
  }>;
  occurrences: Array<{
    id: string;
    scheduleId: string;
    venue: string;
    provider: string;
    accountLabel: string;
    cadence: string;
    executionMode: string;
    direction: string;
    expectedAmountUsd: string;
    submittedAmountUsd: string | null;
    status: string;
    dueAt: string;
    matchDeadlineAt: string;
    alertState: string;
  }>;
  performance: {
    beginningValueUsd: string;
    endingValueUsd: string;
    completedDepositsUsd: string;
    completedWithdrawalsUsd: string;
    tradingPnlExcludingCashFlowsUsd: string | null;
    modifiedDietzReturn: string | null;
    unavailableReason: string | null;
  };
  dataStatus: { status: "ready" | "degraded" | "unavailable"; accountCount: number; errors: string[] };
  directTransferReadiness: {
    enabled: boolean;
    ready: boolean;
    message: string;
    bankSetupMessage?: string;
  };
};

export function PerformanceView({
  funding,
  fundingError,
  portfolio,
  loadError,
}: {
  funding?: FundingHistoryView;
  fundingError?: string;
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
  const accountBalances = useMemo(() => buildPerformanceAccountBalances(currentPortfolio), [currentPortfolio]);
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

      {fundingError ? <p className="ia-degraded-message" role="status"><CircleAlert aria-hidden="true" size={16} /> Funding data is unavailable. {fundingError}</p> : null}

      <section className="funding-performance-band" aria-labelledby="cash-adjusted-title">
        <div className="funding-performance-heading">
          <div>
            <p className="section-label">Cash-adjusted return</p>
            <h2 id="cash-adjusted-title">{"Trading P&L excluding deposits"}</h2>
          </div>
          <span className={`status ${funding?.performance.unavailableReason ? "idle" : "ok"}`}>
            {funding?.performance.unavailableReason ? "boundary data needed" : "cash adjusted"}
          </span>
        </div>
        <div className="funding-performance-values">
          <PerformanceMetric label="Trading P&L" value={formatUsd(funding?.performance.tradingPnlExcludingCashFlowsUsd)} detail="External deposits and withdrawals removed" tone={pnlTone(funding?.performance.tradingPnlExcludingCashFlowsUsd)} />
          <PerformanceMetric label="Deposits" value={formatUsd(funding?.performance.completedDepositsUsd)} detail="Completed venue cash inflow" />
          <PerformanceMetric label="Withdrawals" value={formatUsd(funding?.performance.completedWithdrawalsUsd)} detail="Completed venue cash outflow" />
          <PerformanceMetric label="Modified Dietz" value={formatDecimalRate(funding?.performance.modifiedDietzReturn)} detail="Cash-flow-weighted return" tone={pnlTone(funding?.performance.modifiedDietzReturn)} />
        </div>
        {funding?.performance.unavailableReason ? <p className="funding-boundary-message">Cash-adjusted return is unavailable until confirmed account values exist at both interval boundaries. Cash activity remains visible below.</p> : null}
      </section>

      <div className="funding-ledger-grid">
        <section className="ia-panel funding-ledger-panel" aria-labelledby="funding-history-title">
          <div className="ia-section-heading">
            <div><p className="section-label">Venue activity</p><h2 id="funding-history-title">Funding history</h2></div>
            <Landmark aria-hidden="true" size={20} />
          </div>
          <div className="performance-table-wrap">
            <table className="performance-table funding-history-table">
              <thead><tr><th>Account</th><th>Flow</th><th>Amount</th><th>Status</th><th>Effective</th></tr></thead>
              <tbody>
                {funding?.cashFlows.length ? funding.cashFlows.map((flow) => (
                  <tr key={flow.id}>
                    <th scope="row"><strong>{flow.accountLabel}</strong><span>{providerLabel(flow.providers)}</span></th>
                    <td className={`funding-direction ${flow.direction}`}>{flow.direction === "deposit" ? "Deposit" : "Withdrawal"}</td>
                    <td>{formatUsd(flow.amountUsd)}</td>
                    <td><span className={`status ${fundingStatusTone(flow.status)}`}>{flow.status}</span></td>
                    <td>{formatDate(flow.effectiveAt)}</td>
                  </tr>
                )) : <tr><td className="performance-empty-cell" colSpan={5}>No venue-confirmed deposits or withdrawals in this interval.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        <section className="ia-panel funding-ledger-panel" aria-labelledby="expected-deposits-title">
          <div className="ia-section-heading">
            <div><p className="section-label">Schedule ledger</p><h2 id="expected-deposits-title">Expected deposits</h2></div>
            <CalendarClock aria-hidden="true" size={20} />
          </div>
          <div className="funding-occurrence-list">
            {funding?.occurrences.length ? funding.occurrences.map((occurrence) => (
              <article className={`funding-occurrence ${occurrence.status}`} key={occurrence.id}>
                <span className="funding-occurrence-node" aria-hidden="true" />
                <div>
                  <strong>{occurrence.scheduleId}</strong>
                  <p>{occurrence.accountLabel} · {cadenceLabel(occurrence.cadence)}</p>
                  <small>Due {formatDate(occurrence.dueAt)} · {occurrence.executionMode === "direct" ? "Direct ACH" : "Observe and alert"}</small>
                </div>
                <div className="funding-occurrence-value">
                  <strong>{formatUsd(occurrence.submittedAmountUsd ?? occurrence.expectedAmountUsd)}</strong>
                  <span className={`status ${fundingStatusTone(occurrence.status)}`}>{occurrence.status}</span>
                </div>
              </article>
            )) : <div className="funding-empty-ledger"><strong>No expected deposits</strong><p>Add a funding schedule in Settings to start reconciliation.</p></div>}
          </div>
        </section>
      </div>

      {funding ? (
        <section className={`funding-readiness-note ${funding.directTransferReadiness.ready ? "ready" : "disabled"}`} aria-label="Direct funding readiness">
          <strong>{funding.directTransferReadiness.enabled ? "Direct Alpaca ACH" : "Direct transfers off"}</strong>
          <p>{funding.directTransferReadiness.message} {funding.directTransferReadiness.bankSetupMessage}</p>
        </section>
      ) : null}

      <section className="ia-panel performance-account-balances" aria-labelledby="account-balances-title">
        <div className="ia-section-heading">
          <div>
            <p className="section-label">Trading capacity</p>
            <h2 id="account-balances-title">Available to trade</h2>
          </div>
          <span>{accountBalances.length} confirmed account{accountBalances.length === 1 ? "" : "s"}</span>
        </div>
        <p className="performance-account-note">
          Equity includes cash and open positions. Available to trade uses current buying power when the venue provides it, or cash otherwise.
        </p>
        <div className="performance-table-wrap">
          <table className="performance-table performance-account-table">
            <thead>
              <tr><th>Account</th><th>Venue</th><th>Equity</th><th>Cash</th><th>Available to trade</th><th>Status</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {accountBalances.length ? accountBalances.map((account) => (
                <tr key={account.key}>
                  <th scope="row">
                    <strong>{providerLabel(account.providers)}</strong>
                    <span>{account.accountMode} account</span>
                  </th>
                  <td>{venueLabel(account.venue)}</td>
                  <td>{formatUsd(account.equityUsd)}</td>
                  <td>{formatUsd(account.cashUsd)}</td>
                  <td className="performance-available-balance">
                    <strong>{formatUsd(account.availableToTradeUsd)}</strong>
                    <span>{account.availableToTradeSource ?? "No venue balance"}</span>
                  </td>
                  <td><span className={`status ${statusTone(account.status)}`}>{account.status}</span></td>
                  <td>{formatDate(account.lastUpdatedAt)}</td>
                </tr>
              )) : (
                <tr><td className="performance-empty-cell" colSpan={7}>No venue-confirmed account balances are available.</td></tr>
              )}
            </tbody>
          </table>
        </div>
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
function formatDecimalRate(value: string | null | undefined): string { if (value === null || value === undefined || value === "") return "Unavailable"; const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 2 }).format(number) : "Unavailable"; }
function formatUsd(value: string | null | undefined): string { if (value === null || value === undefined || value === "") return "Unavailable"; const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(number) : "Unavailable"; }
function formatCount(value: number | null | undefined): string { return value === null || value === undefined ? "Unavailable" : value.toLocaleString(); }
function pnlTone(value: string | null | undefined): string { const number = Number(value); return !Number.isFinite(number) || number === 0 ? "" : number > 0 ? "positive" : "negative"; }
function venueLabel(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function providerLabel(providers: string[]): string { return providers.map((provider) => provider === "openai" ? "OpenAI" : provider === "claude" ? "Claude" : provider).join(" + "); }
function statusTone(status: "ready" | "stale" | "unavailable"): string { return status === "ready" ? "ok" : status === "stale" ? "waiting" : "blocked"; }
function fundingStatusTone(status: string): string { return ["completed", "matched", "submitted"].includes(status) ? "ok" : ["pending", "expected", "reserved", "unknown"].includes(status) ? "waiting" : ["missing", "failed", "rejected", "returned"].includes(status) ? "blocked" : "idle"; }
function cadenceLabel(value: string): string { return value === "low_balance" ? "Low balance" : value.charAt(0).toUpperCase() + value.slice(1); }
function formatDate(value: string | null | undefined): string { if (!value) return "Unavailable"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "Unavailable" : new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(date); }
