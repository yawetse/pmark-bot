"use client";

import Link from "next/link";
import { BriefcaseBusiness, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// REQ: REQ-UI-013, REQ-CMP-005

type PortfolioTotals = {
  status: "ready" | "stale" | "unavailable";
  accountValueUsd: string | null;
  realizedPnlUsd: string | null;
  unrealizedPnlUsd: string | null;
  totalPnlUsd: string | null;
  openPositions: number | null;
  filledTrades: number | null;
};

type PortfolioAccountView = PortfolioTotals & {
  venue: string;
  accountRef: string;
  accountMode: string;
  providers: string[];
  cashUsd: string | null;
  buyingPowerUsd: string | null;
  lastUpdatedAt: string | null;
  message: string;
};

type PortfolioVenueView = PortfolioTotals & {
  venue: string;
  label: string;
  accounts: PortfolioAccountView[];
};

type PortfolioPositionView = {
  id: string;
  venue: string;
  providers: string[];
  accountRef: string;
  instrumentId: string;
  title: string;
  outcome: string | null;
  quantity: string;
  positionSide: "long" | "short";
  averageEntryPrice: string | null;
  currentPrice: string | null;
  costBasisUsd: string | null;
  marketValueUsd: string | null;
  realizedPnlUsd: string | null;
  unrealizedPnlUsd: string | null;
  totalPnlUsd: string | null;
  state: string;
  updatedAt: string | null;
};

type PortfolioFillView = {
  id: string;
  venue: string;
  providers: string[];
  accountRef: string;
  sourceTradeId: string;
  venueOrderId: string | null;
  instrumentId: string;
  title: string;
  side: string;
  quantity: string;
  price: string;
  notionalUsd: string;
  realizedPnlUsd: string | null;
  feeUsd: string | null;
  state: "filled";
  executedAt: string | null;
};

type PortfolioHistoryView = {
  asOf: string;
  accountValueUsd: string | null;
  totalPnlUsd: string | null;
  polymarketUsPnlUsd: string | null;
  alpacaPnlUsd: string | null;
};

export type VenuePortfolioView = {
  environment: string;
  generatedAt: string;
  overall: PortfolioTotals;
  venues: PortfolioVenueView[];
  accounts: PortfolioAccountView[];
  positions: PortfolioPositionView[];
  fills: PortfolioFillView[];
  history: PortfolioHistoryView[];
  freshness: {
    status: "ready" | "stale" | "unavailable";
    refreshedAt: string | null;
    ageSeconds: number | null;
    message: string;
  };
  source: string;
};

export function VenuePortfolioPanel({ portfolio }: { portfolio: VenuePortfolioView }) {
  const chartData = portfolio.history.map((row) => ({
    label: formatChartTime(row.asOf),
    total: numberOrNull(row.totalPnlUsd),
    polymarket: numberOrNull(row.polymarketUsPnlUsd),
    alpaca: numberOrNull(row.alpacaPnlUsd),
  }));
  const statusTone = portfolio.overall.status === "ready"
    ? "ok"
    : portfolio.overall.status === "stale"
      ? "waiting"
      : "blocked";

  return (
    <section className="consumer-panel span-3 venue-portfolio-panel" aria-labelledby="venue-portfolio-title">
      <div className="consumer-panel-heading">
        <div>
          <p className="section-label">Actual portfolio</p>
          <h2 id="venue-portfolio-title">Are my trades making money?</h2>
        </div>
        <div className="portfolio-heading-status">
          <BriefcaseBusiness aria-hidden="true" size={20} />
          <span className={`status ${statusTone}`}>{portfolio.overall.status}</span>
        </div>
      </div>

      <p className="panel-note">
        Venue-confirmed balances, positions, and fills only. Submitted and simulated orders are excluded.
      </p>

      <div className="portfolio-summary-grid">
        <PortfolioMetric label="Account value" value={formatOptionalUsd(portfolio.overall.accountValueUsd)} />
        <PortfolioMetric label="Total P&L" value={formatOptionalUsd(portfolio.overall.totalPnlUsd)} tone={pnlTone(portfolio.overall.totalPnlUsd)} />
        <PortfolioMetric label="Realized" value={formatOptionalUsd(portfolio.overall.realizedPnlUsd)} tone={pnlTone(portfolio.overall.realizedPnlUsd)} />
        <PortfolioMetric label="Unrealized" value={formatOptionalUsd(portfolio.overall.unrealizedPnlUsd)} tone={pnlTone(portfolio.overall.unrealizedPnlUsd)} />
        <PortfolioMetric label="Open positions" value={formatOptionalCount(portfolio.overall.openPositions)} />
        <PortfolioMetric label="Confirmed fills" value={formatOptionalCount(portfolio.overall.filledTrades)} />
      </div>

      <div className="portfolio-performance-layout">
        <div className="portfolio-chart-block">
          <div className="portfolio-subheading">
            <h3>Confirmed P&L over time</h3>
            <span>{portfolio.freshness.message}</span>
          </div>
          <div className="consumer-chart" aria-label="Confirmed portfolio profit and loss over time">
            {chartData.length > 1 ? (
              <ResponsiveContainer height="100%" width="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} />
                  <YAxis tickFormatter={(value) => `$${value}`} tickLine={false} width={64} />
                  <Tooltip formatter={(value) => formatOptionalUsd(String(value))} />
                  <Line dataKey="total" dot={false} name="Total P&L" stroke="var(--foreground)" strokeWidth={2.5} />
                  <Line dataKey="polymarket" dot={false} name="Polymarket US" stroke="var(--accent)" strokeWidth={2} />
                  <Line dataKey="alpaca" dot={false} name="Alpaca" stroke="var(--focus)" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="consumer-empty-chart">
                <strong>{formatOptionalUsd(portfolio.overall.totalPnlUsd)}</strong>
                <span>Waiting for another confirmed portfolio snapshot.</span>
              </div>
            )}
          </div>
        </div>

        <div className="portfolio-venue-breakdown" aria-label="Venue performance">
          <div className="portfolio-subheading">
            <h3>Performance by venue</h3>
            <span>Shared accounts are counted once.</span>
          </div>
          {portfolio.venues.map((venue) => (
            <div className="portfolio-venue-group" key={venue.venue}>
              <div className="portfolio-venue-row">
                <div>
                  <strong>{venue.label}</strong>
                  <span>{accountLabels(venue.accounts)}</span>
                </div>
                <PortfolioDatum label="Account value" value={formatOptionalUsd(venue.accountValueUsd)} />
                <PortfolioDatum label="Total P&L" value={formatOptionalUsd(venue.totalPnlUsd)} tone={pnlTone(venue.totalPnlUsd)} />
                <PortfolioDatum label="Open" value={formatOptionalCount(venue.openPositions)} />
                <span className={`status ${venue.status === "ready" ? "ok" : venue.status === "stale" ? "waiting" : "blocked"}`}>
                  {venue.status}
                </span>
              </div>
              <div className="portfolio-account-rows">
                {venue.accounts.length ? venue.accounts.map((account) => (
                  <div className="portfolio-account-row" key={`${account.venue}-${account.accountRef}`}>
                    <div>
                      <strong>{providerLabel(account.providers)}</strong>
                      <span>{account.accountMode} account</span>
                    </div>
                    <PortfolioDatum label="Value" value={formatOptionalUsd(account.accountValueUsd)} />
                    <PortfolioDatum label="Cash" value={formatOptionalUsd(account.cashUsd)} />
                    <PortfolioDatum label="Available" value={formatOptionalUsd(availableToTradeUsd(account))} />
                    <PortfolioDatum label="P&L" value={formatOptionalUsd(account.totalPnlUsd)} tone={pnlTone(account.totalPnlUsd)} />
                    <span className={`status ${account.status === "ready" ? "ok" : account.status === "stale" ? "waiting" : "blocked"}`}>
                      {account.status}
                    </span>
                  </div>
                )) : (
                  <p className="portfolio-account-empty">No configured account was confirmed.</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <PortfolioTable
        emptyMessage="No venue-confirmed open positions are available."
        title="Open holdings"
        headers={["Venue", "Model account", "Instrument", "Quantity", "Cost basis", "Market value", "Unrealized P&L", "Updated"]}
      >
        {portfolio.positions.slice(0, 12).map((position) => (
          <tr key={position.id}>
            <td>{venueLabel(position.venue)}</td>
            <td>{providerLabel(position.providers)}</td>
            <td><strong>{position.title}</strong>{position.outcome ? <span>{position.outcome}</span> : null}</td>
            <td>{position.quantity} <span className="status neutral">{position.positionSide}</span></td>
            <td>{formatOptionalUsd(position.costBasisUsd)}</td>
            <td>{formatOptionalUsd(position.marketValueUsd)}</td>
            <td className={pnlTone(position.unrealizedPnlUsd)}>{formatOptionalUsd(position.unrealizedPnlUsd)}</td>
            <td>{formatDateTime(position.updatedAt)}</td>
          </tr>
        ))}
      </PortfolioTable>

      <PortfolioTable
        emptyMessage="No venue-confirmed fills are available. Submitted and simulated orders do not appear here."
        title="Recent confirmed fills"
        headers={["Venue", "Model account", "Instrument", "Side", "Quantity", "Price", "Notional", "Realized P&L", "Executed"]}
      >
        {portfolio.fills.slice(0, 10).map((fill) => (
          <tr key={fill.id}>
            <td>{venueLabel(fill.venue)}</td>
            <td>{providerLabel(fill.providers)}</td>
            <td><strong>{fill.title}</strong></td>
            <td>{fill.side}</td>
            <td>{fill.quantity}</td>
            <td>{formatOptionalUsd(fill.price)}</td>
            <td>{formatOptionalUsd(fill.notionalUsd)}</td>
            <td className={pnlTone(fill.realizedPnlUsd)}>{formatOptionalUsd(fill.realizedPnlUsd)}</td>
            <td>{formatDateTime(fill.executedAt)}</td>
          </tr>
        ))}
      </PortfolioTable>

      <div className="portfolio-footer">
        <span>Last venue-confirmed refresh: {formatDateTime(portfolio.freshness.refreshedAt)}</span>
        <Link className="inline-link" href="/dashboard/operations">
          View full order history
          <ExternalLink aria-hidden="true" size={15} />
        </Link>
      </div>
    </section>
  );
}

function PortfolioMetric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="portfolio-metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function PortfolioDatum({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="portfolio-datum">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

function PortfolioTable({
  children,
  emptyMessage,
  headers,
  title,
}: {
  children: ReactNode;
  emptyMessage: string;
  headers: string[];
  title: string;
}) {
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
  const headingId = `portfolio-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <div className="portfolio-table-section">
      <h3 id={headingId}>{title}</h3>
      {hasRows ? (
        <div className="portfolio-table-wrap" role="region" aria-labelledby={headingId} tabIndex={0}>
          <table aria-labelledby={headingId} className="portfolio-table">
            <thead>
              <tr>{headers.map((header) => <th key={header} scope="col">{header}</th>)}</tr>
            </thead>
            <tbody>{children}</tbody>
          </table>
        </div>
      ) : (
        <p className="portfolio-empty">{emptyMessage}</p>
      )}
    </div>
  );
}

function accountLabels(accounts: PortfolioAccountView[]): string {
  if (!accounts.length) {
    return "No confirmed account";
  }
  return accounts.map((account) => `${providerLabel(account.providers)} ${account.accountMode}`).join(", ");
}

function providerLabel(providers: string[]): string {
  return providers.map((provider) => provider === "openai" ? "OpenAI" : provider === "claude" ? "Claude" : provider).join(" + ");
}

function venueLabel(venue: string): string {
  return venue === "polymarket_us" ? "Polymarket US" : venue === "alpaca" ? "Alpaca" : venue;
}

function pnlTone(value: string | null): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) {
    return "";
  }
  return parsed > 0 ? "portfolio-positive" : "portfolio-negative";
}

function numberOrNull(value: string | null): number | null {
  const parsed = Number(value);
  return value !== null && Number.isFinite(parsed) ? parsed : null;
}

function formatOptionalUsd(value: string | null): string {
  if (value === null) {
    return "Unavailable";
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", { currency: "USD", style: "currency" }).format(parsed);
}

function formatOptionalCount(value: number | null): string {
  return value === null ? "Unavailable" : String(value);
}

function availableToTradeUsd(account: PortfolioAccountView): string | null {
  return account.buyingPowerUsd ?? account.cashUsd;
}

function formatChartTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(parsed);
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "not available";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "not available";
  }
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}
