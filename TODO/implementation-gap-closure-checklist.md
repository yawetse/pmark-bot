# Implementation Gap Closure Checklist

Last updated: 2026-06-25

Purpose: track the remaining work needed to turn the current dashboard-visible loop into the full trading methodology described in `pmbot.md`, with equivalent support for Polymarket and stock trades.

This checklist is the working source of truth for closing the gaps. Check off an item only after the implementation, tests, and dashboard evidence exist in the repo or release record.

## Historical Polymarket Trades Plan

Yes, we can use the same method described in `pmbot.md`.

The original method starts from the `warproxxx/poly_data` repo, which now reads Polymarket CTF Exchange V2 `OrderFilled` events directly from Polygon JSON-RPC, joins them to Gamma market metadata, and outputs structured trades. That is the right shape for this service because the current authenticated CLOB `/data/trades` endpoint is for the authenticated user's trades, while the bot needs broad historical wallet behavior across many traders.

Implementation approach:

1. Use `poly_data` as a reference for the public data flow, not as copied application code unless a GPL-3.0 license decision is explicitly approved.
2. Build a clean-room importer inside this repo, or run `poly_data` as a separate external import job and ingest its CSV outputs. The clean-room path is preferred for long-term maintainability.
3. Pull market metadata from Gamma, including closed and active markets, token IDs, outcomes, end dates, volume, liquidity, tags, and categories.
4. Backfill Polygon `OrderFilled` events from the Polymarket CTF Exchange V2 contract in block windows, with a checkpoint cursor per environment.
5. Decode each fill into normalized trade rows with wallet, market, token, side, price, size, timestamp, transaction hash, and maker/taker role.
6. Join fills to market metadata and outcome metadata.
7. Reconstruct wallet-level positions, exits, realized P&L, win rate, hold time, average entry, average exit, and settlement behavior.
8. Rank wallets using the `pmbot.md` style filter: at least 100 trades, win rate above 70%, sorted by total realized P&L.
9. Persist the target wallet set so the scanner and brain can use it for whale-copy and whale-confirmation checks.
10. Run incremental updates by resuming from the last scanned block and only reprocessing changed markets or new fills.

Reference sources:

- Local intent: `pmbot.md`
- Historical repo reference: https://github.com/warproxxx/poly_data
- Polymarket API overview: https://docs.polymarket.com/api-reference/introduction
- Polymarket CLOB authenticated user trades endpoint: https://docs.polymarket.com/api-reference/trade/get-trades
- Polymarket CLOB price history endpoint: https://docs.polymarket.com/api-reference/markets/get-prices-history

## Phase 0: Design Decisions

- [ ] Decide whether to implement a clean-room historical importer or run `poly_data` as an external import job.
- [ ] Record the license decision for GPL-3.0 code in `docs/source-references.md` before using any source code from `poly_data`.
- [ ] Decide the Polygon RPC provider for development and production.
- [ ] Add non-secret runtime config for `POLYGON_RPC_URL`, max block range, retry policy, and importer cadence.
- [ ] Define retention policy for raw chain events, processed trades, wallet stats, and scanner outputs.
- [ ] Add operator-facing dashboard language that distinguishes imported history, provider market data, scanner results, LLM reasoning, execution, and exit monitoring.

## Phase 1: Step 0 Data Foundation

Polymarket:

- [x] Add schema for raw Gamma market metadata.
- [x] Add schema for raw Polygon `OrderFilled` events.
- [x] Add schema for normalized Polymarket trades.
- [x] Add schema for reconstructed wallet positions and exits.
- [x] Add schema for wallet performance stats.
- [x] Add schema for target wallet lists and ranking snapshots.
- [x] Add checkpoint state for historical backfill and incremental sync.
- [x] Implement Gamma market metadata backfill with resumable pagination.
- [x] Implement Polygon event backfill with block-window retries and cursor persistence.
- [x] Implement event decoding tests using fixture logs.
- [x] Implement market metadata join tests using fixture markets.
- [x] Implement wallet performance ranking tests, including the 100-trade and 70% win-rate thresholds.
- [x] Show historical import status in the dashboard.

Stocks:

- [x] Add schema for Alpaca historical fills, orders, positions, and account snapshots.
- [x] Add schema for daily and intraday stock bars used for scanner backtests.
- [x] Implement Alpaca historical order and fill import for paper and live accounts.
- [x] Implement realized and unrealized stock P&L reconstruction.
- [x] Show broker history import status in the dashboard.

## Phase 2: Scanner

Polymarket:

- [ ] Persist scanner runs separate from raw market data pulls.
- [ ] Filter active markets by order-book depth, spread, liquidity, resolution window, category, and minimum volume.
- [ ] Add configurable thresholds for minimum depth, minimum liquidity, max spread, minimum hours to resolution, and maximum hours to resolution.
- [ ] Calculate market midpoint, bid depth, ask depth, spread, and hours to resolution for each candidate.
- [ ] Attach target wallet overlap when target wallets hold or recently traded the market.
- [ ] Persist rejected scanner candidates with refusal reason.
- [ ] Surface scanner candidates and rejections in a paginated, sortable, filterable table.

Stocks:

- [ ] Persist stock scanner runs separate from raw Alpaca pulls.
- [ ] Define initial stock scanner strategies: momentum, mean reversion, gap, liquidity, volatility, and unusual volume.
- [ ] Add configurable thresholds per stock scanner strategy.
- [ ] Run scanner over the configured symbol universe, including S&P 500, Nasdaq 100, custom presets, and individual symbols.
- [ ] Persist accepted and rejected stock candidates with refusal reason.
- [ ] Surface stock scanner output in the same dynamic table pattern.

## Phase 3: Reasoning / Brain

Polymarket:

- [ ] Wire scanner survivors into LLM scoring in each manual and scheduled run.
- [ ] Build the four `pmbot.md` checks: base rate, news, whale check, and disposition.
- [ ] Persist the prompt payload, model provider, response, probability estimate, confidence, thesis, and token usage.
- [ ] Convert LLM output into normalized directional signals.
- [ ] Add budget and rate-limit gates before each scoring request.
- [ ] Show reasoning status and scored candidates per pipeline run.

Stocks:

- [ ] Define stock-specific reasoning inputs: price action, historical bars, volume, sector, index membership, event/news context, risk, and liquidity.
- [ ] Add stock LLM prompt templates separate from Polymarket prompts.
- [ ] Persist stock scoring output with the same normalized signal shape.
- [ ] Show stock reasoning output per pipeline run.

## Phase 4: Strategy Consensus

Polymarket:

- [ ] Implement arbitrage strategy signals.
- [ ] Implement convergence strategy signals.
- [ ] Implement whale-copy strategy signals using target wallet history.
- [ ] Persist per-strategy votes.
- [ ] Implement consensus rules: two or more aligned votes for full position, one aligned vote for half position, disagreement means no trade.
- [ ] Add tests for conflicting, single-vote, and multi-vote outcomes.

Stocks:

- [ ] Implement stock momentum strategy votes.
- [ ] Implement stock mean-reversion strategy votes.
- [ ] Implement stock event or unusual-volume strategy votes.
- [ ] Persist per-strategy stock votes.
- [ ] Apply a stock-specific consensus rule before risk sizing.

## Phase 5: Risk and Execution

- [ ] Persist order intents before any venue submission.
- [ ] Add idempotency keys for all live order intents.
- [ ] Run market-data freshness, slippage, max position, max daily loss, max open positions, and kill-switch gates before order submission.
- [ ] Support dry-run order recording for Polymarket and Alpaca.
- [ ] Wire approved Polymarket intents into the Polymarket execution adapter.
- [ ] Wire approved Alpaca intents into the Alpaca execution adapter.
- [ ] Reconcile unknown or partially filled order states before retrying.
- [ ] Show order intents, submitted orders, refusals, and reconciliation status in the dashboard.

## Phase 6: Exit

Polymarket:

- [ ] Sync open Polymarket positions for target venues.
- [ ] Apply profit-target exit logic.
- [ ] Apply volume-spike exit logic.
- [ ] Apply stale-thesis exit logic.
- [ ] Persist exit intents and exit orders.
- [ ] Compare exit behavior against target wallet exit patterns where history is available.

Stocks:

- [ ] Sync open Alpaca positions.
- [ ] Apply stock profit-target, stop-loss, trailing-stop, stale-position, and market-hours exit logic.
- [ ] Persist stock exit intents and exit orders.
- [ ] Show exit status per open position in the dashboard.

## Phase 7: Stock Universe Refresh

- [ ] Replace static S&P 500 and Nasdaq 100 constituent lists with a refreshable source.
- [ ] Store preset membership snapshots with effective dates.
- [ ] Add a scheduled refresh job.
- [ ] Keep user custom symbols additive to presets.
- [ ] Show preset age and symbol count in the config UI.
- [ ] Add tests that a new custom IPO symbol can be added without replacing preset membership.

## Phase 8: AI and Infrastructure Cost Backfill

- [ ] Keep recording provider token usage from live scoring responses.
- [ ] Add a provider-side usage import or backfill job where the provider exposes enough API data.
- [ ] Store token usage by provider, model, run, step, and candidate.
- [ ] Chart token spend and AI cost over time using economics snapshots.
- [ ] Keep AWS Cost Explorer as the primary AWS cost source when available.
- [ ] Fall back to saved monthly AWS cost preference only when Cost Explorer is unavailable.
- [ ] Show cost source, freshness, and error state in the dashboard.

## Phase 9: Dashboard and Operations

- [ ] Add a pipeline detail view for each run.
- [ ] Link each pipeline step to its underlying records.
- [ ] Add full tables for data imports, scanner output, reasoning output, strategy votes, order intents, executions, exits, and economics history.
- [ ] Add manual controls for data import, scanner-only run, full dry-run, and full live-gated run.
- [ ] Show rate limits, provider errors, stale data, and partial fetches separately from successful pulls.
- [ ] Add operator documentation in `docs/operations-runbook.md`.

## Phase 10: Release Gates

- [ ] Backend tests cover each new repository table and service boundary.
- [ ] Frontend checks cover each new dashboard table and control.
- [ ] Migration safety passes with no destructive changes.
- [ ] A local dry-run records all five pipeline steps with real records behind each step.
- [ ] Development deployment passes health checks.
- [ ] Production deployment passes health checks.
- [ ] Live trading remains gated until `docs/live-trading-checklist.md` is complete.

## Current Next Slice

Start with Phase 1 Polymarket data foundation:

- [x] Add schema for Gamma market metadata, raw chain fill events, processed trades, wallet stats, target wallet snapshots, and importer checkpoints.
- [x] Add a clean-room historical importer service interface with fixture-based tests.
- [x] Implement Gamma market metadata backfill first.
- [x] Implement Polygon `OrderFilled` backfill second.
- [x] Implement wallet ranking third.
- [x] Add a dashboard import status card after the backend records exist.
