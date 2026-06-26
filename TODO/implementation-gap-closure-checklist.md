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

- [x] Persist scanner runs separate from raw market data pulls.
- [x] Filter active markets by order-book depth, spread, liquidity, resolution window, category, and minimum volume.
- [x] Add configurable thresholds for minimum depth, minimum liquidity, max spread, minimum hours to resolution, and maximum hours to resolution.
- [x] Calculate market midpoint, bid depth, ask depth, spread, and hours to resolution for each candidate.
- [x] Attach target wallet overlap when target wallets hold or recently traded the market.
- [x] Persist rejected scanner candidates with refusal reason.
- [x] Surface scanner candidates and rejections in a paginated, sortable, filterable table.

Stocks:

- [x] Persist stock scanner runs separate from raw Alpaca pulls.
- [x] Define initial stock scanner strategies: momentum, mean reversion, gap, liquidity, volatility, and unusual volume.
- [x] Add configurable thresholds per stock scanner strategy.
- [x] Run scanner over the configured symbol universe, including S&P 500, Nasdaq 100, custom presets, and individual symbols.
- [x] Persist accepted and rejected stock candidates with refusal reason.
- [x] Surface stock scanner output in the same dynamic table pattern.

## Phase 3: Reasoning / Brain

Phase 3 complete means accepted scanner candidates are scored, persisted, normalized, and visible per run. Checks that need data not attached yet, such as recent news, sector enrichment, and live target-wallet holdings, are recorded as `needs_provider_data` in the prompt/check payload.

Polymarket:

- [x] Wire scanner survivors into LLM scoring in each manual and scheduled run.
- [x] Build the four `pmbot.md` checks: base rate, news, whale check, and disposition.
- [x] Persist the prompt payload, model provider, response, probability estimate, confidence, thesis, and token usage.
- [x] Convert LLM output into normalized directional signals.
- [x] Add budget and rate-limit gates before each scoring request.
- [x] Show reasoning status and scored candidates per pipeline run.

Stocks:

- [x] Define stock-specific reasoning inputs: price action, historical bars, volume, sector, index membership, event/news context, risk, and liquidity.
- [x] Add stock LLM prompt templates separate from Polymarket prompts.
- [x] Persist stock scoring output with the same normalized signal shape.
- [x] Show stock reasoning output per pipeline run.

## Phase 4: Strategy Consensus

Polymarket:

- [x] Implement arbitrage strategy signals.
- [x] Implement convergence strategy signals.
- [x] Implement whale-copy strategy signals using target wallet history.
- [x] Persist per-strategy votes.
- [x] Implement consensus rules: two or more aligned votes for full position, one aligned vote for half position, disagreement means no trade.
- [x] Add tests for conflicting, single-vote, and multi-vote outcomes.

Stocks:

- [x] Implement stock momentum strategy votes.
- [x] Implement stock mean-reversion strategy votes.
- [x] Implement stock event or unusual-volume strategy votes.
- [x] Persist per-strategy stock votes.
- [x] Apply a stock-specific consensus rule before risk sizing.

Implementation note: Phase 4 now persists `shared.strategy_consensus_runs`,
`shared.strategy_votes`, and `shared.strategy_consensus_outputs`. Execution step 4
shows strategy consensus records before risk sizing and order intents.

## Phase 5: Risk and Execution

- [x] Persist order intents before any venue submission.
- [x] Add idempotency keys for all live order intents.
- [x] Run market-data freshness, slippage, max position, max daily loss, max open positions, and kill-switch gates before order submission.
- [x] Support dry-run order recording for Polymarket and Alpaca.
- [x] Wire approved Polymarket intents into the Polymarket execution adapter.
- [x] Wire approved Alpaca intents into the Alpaca execution adapter.
- [x] Reconcile unknown or partially filled order states before retrying.
- [x] Show order intents, submitted orders, refusals, and reconciliation status in the dashboard.

Implementation note: Phase 5 now persists `shared.execution_runs` and
`shared.order_intents` from manual and scheduled runs. Dry-run records simulated
orders. Live runs still require configured venue submitters and credentials; without
them, the lifecycle records a refusal before venue submission.

## Phase 6: Exit

Polymarket:

- [x] Sync open Polymarket positions for target venues.
- [x] Apply profit-target exit logic.
- [x] Apply volume-spike exit logic.
- [x] Apply stale-thesis exit logic.
- [x] Persist exit intents and exit orders.
- [x] Compare exit behavior against target wallet exit patterns where history is available.

Stocks:

- [x] Sync open Alpaca positions.
- [x] Apply stock profit-target, stop-loss, trailing-stop, stale-position, and market-hours exit logic.
- [x] Persist stock exit intents and exit orders.
- [x] Show exit status per open position in the dashboard.

Implementation note: Phase 6 now persists `shared.exit_runs` and
`shared.exit_intents` from manual and scheduled runs. The monitor reads the existing
shared Polymarket wallet positions and Alpaca historical positions as the open-position
source, then records simulated or refused exits with the configured trigger details.

## Phase 7: Stock Universe Refresh

- [x] Replace static S&P 500 and Nasdaq 100 constituent lists with a refreshable source.
- [x] Store preset membership snapshots with effective dates.
- [x] Add a scheduled refresh job.
- [x] Keep user custom symbols additive to presets.
- [x] Show preset age and symbol count in the config UI.
- [x] Add tests that a new custom IPO symbol can be added without replacing preset membership.

Implementation note: Phase 7 now persists `shared.alpaca_symbol_preset_snapshots`.
Scheduled runs refresh active presets from configurable constituent-table URLs before
Alpaca pulls. The static S&P 500 and Nasdaq 100 lists remain as seed fallback data,
not the primary runtime source after successful refresh. Config still keeps custom
presets and individual symbols additive to the refreshed preset members.

## Phase 8: AI and Infrastructure Cost Backfill

- [x] Keep recording provider token usage from live scoring responses.
- [x] Add a provider-side usage import or backfill job where the provider exposes enough API data.
- [x] Store token usage by provider, model, run, step, and candidate.
- [x] Chart token spend and AI cost over time using economics snapshots.
- [x] Keep AWS Cost Explorer as the primary AWS cost source when available.
- [x] Fall back to saved monthly AWS cost preference only when Cost Explorer is unavailable.
- [x] Show cost source, freshness, and error state in the dashboard.

Implementation note: Phase 8 now persists `shared.ai_usage_import_runs` and extends
`shared.ai_usage_events` with provider, model, run, step, candidate, source, and
raw provider payload attribution. Runtime imports use provider admin/reporting APIs
when `OPENAI_ADMIN_API_KEY` or `ANTHROPIC_ADMIN_API_KEY` is configured; otherwise
the dashboard records an explicit unsupported import run instead of showing a
successful pull. Economics summary now includes recent cost snapshots for token,
AI cost, AWS cost, trading P&L, and net profitability history.

## Phase 9: Dashboard and Operations

- [x] Add a pipeline detail view for each run.
- [x] Link each pipeline step to its underlying records.
- [x] Add full tables for data imports, scanner output, reasoning output, strategy votes, order intents, executions, exits, and economics history.
- [x] Add manual controls for data import, scanner-only run, full dry-run, and full live-gated run.
- [x] Show rate limits, provider errors, stale data, and partial fetches separately from successful pulls.
- [x] Add operator documentation in `docs/operations-runbook.md`.

Implementation note: Phase 9 now has explicit manual modes: `data_import`,
`scanner_only`, `full_dry_run`, and `full_live_gated`. Downstream stages skipped
by a requested mode are persisted as skipped pipeline records, not hidden UI state.
Pipeline details expose the shared-table records behind each step, and economics
uses the shared data grid for provider usage imports and cost history.

## Phase 10: Release Gates

- [x] Backend tests cover each new repository table and service boundary.
- [x] Frontend checks cover each new dashboard table and control.
- [x] Migration safety passes with no destructive changes.
- [x] A local dry-run records all five pipeline steps with real records behind each step.
- [ ] Development deployment passes health checks.
- [ ] Production deployment passes health checks.
- [ ] Live trading remains gated until `docs/live-trading-checklist.md` is complete.

Live-trading enablement note: AWS production currently has `LIVE_ENABLED=true`,
`TRADING_ACCOUNT_MODE=live`, `POLYMARKET_US_ENABLED=true`, `ALPACA_ENABLED=true`,
and `ALPACA_ACCOUNT_STATUS=active`, but actual autonomous live order submission is
still not complete until concrete venue submitters are attached in the runtime
service and every live-trading checklist item has release evidence. The current
default lifecycle refuses live submissions with `LIVE_SUBMITTER_NOT_CONFIGURED`
when a venue submitter is absent.

## Current Next Slice

Start with Phase 1 Polymarket data foundation:

- [x] Add schema for Gamma market metadata, raw chain fill events, processed trades, wallet stats, target wallet snapshots, and importer checkpoints.
- [x] Add a clean-room historical importer service interface with fixture-based tests.
- [x] Implement Gamma market metadata backfill first.
- [x] Implement Polygon `OrderFilled` backfill second.
- [x] Implement wallet ranking third.
- [x] Add a dashboard import status card after the backend records exist.
