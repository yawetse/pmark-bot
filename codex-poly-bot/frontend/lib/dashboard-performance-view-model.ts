import type { VenuePortfolioView } from "@/components/dashboard/venue-portfolio-panel";

// REQ: REQ-UI-013, REQ-UI-021, REQ-UI-025

export type PerformanceHeadlineView = {
  tradeCount: number | null;
  winRate: number | null;
  winRateDetail: string;
};

export type PerformanceVenueRow = {
  market: string;
  detail: string;
  trades: number | null;
  winRate: number | null;
  pnlUsd: string | null;
};

export type PerformanceAccountBalanceRow = {
  key: string;
  venue: string;
  providers: string[];
  accountMode: string;
  equityUsd: string | null;
  cashUsd: string | null;
  availableToTradeUsd: string | null;
  availableToTradeSource: "Buying power" | "Cash balance" | null;
  status: "ready" | "stale" | "unavailable";
  lastUpdatedAt: string | null;
};

export function buildPerformanceHeadline(
  portfolio?: VenuePortfolioView,
): PerformanceHeadlineView {
  return {
    tradeCount: portfolio?.overall.filledTrades ?? null,
    winRate: null,
    winRateDetail: "Needs confirmed closed outcomes",
  };
}

export function buildPerformanceVenueRows(
  portfolio?: VenuePortfolioView,
): PerformanceVenueRow[] {
  return (portfolio?.venues ?? []).map((venue) => ({
    market: venue.label,
    detail: venue.accounts.length
      ? `${venue.accounts.length} confirmed account${venue.accounts.length === 1 ? "" : "s"}`
      : "No confirmed account",
    trades: venue.filledTrades,
    winRate: null,
    pnlUsd: venue.totalPnlUsd,
  }));
}

// REQ: REQ-UI-013
export function buildPerformanceAccountBalances(
  portfolio?: Pick<VenuePortfolioView, "accounts">,
): PerformanceAccountBalanceRow[] {
  return (portfolio?.accounts ?? []).map((account) => {
    const buyingPowerUsd = validMoney(account.buyingPowerUsd);
    const cashUsd = validMoney(account.cashUsd);
    return {
      key: `${account.venue}:${account.accountRef}`,
      venue: account.venue,
      providers: account.providers,
      accountMode: account.accountMode,
      equityUsd: validMoney(account.accountValueUsd),
      cashUsd,
      availableToTradeUsd: buyingPowerUsd ?? cashUsd,
      availableToTradeSource: buyingPowerUsd !== null
        ? "Buying power"
        : cashUsd !== null
          ? "Cash balance"
          : null,
      status: account.status,
      lastUpdatedAt: account.lastUpdatedAt,
    };
  });
}

function validMoney(value: string | null): string | null {
  if (value === null || value.trim() === "") {
    return null;
  }
  return Number.isFinite(Number(value)) ? value : null;
}
