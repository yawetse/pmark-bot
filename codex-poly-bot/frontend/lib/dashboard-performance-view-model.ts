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
