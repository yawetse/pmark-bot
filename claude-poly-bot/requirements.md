# claude-poly-bot — Requirements Specification

**Project:** Multi-venue trading bot with dual-LLM (Claude + OpenAI) head-to-head competition.
**Venues:** Polymarket (prediction markets) + Alpaca (US equities).
**Parent context:** Companion to `codex-poly-bot/`. Goal is statistically meaningful comparison of Claude vs OpenAI across both venue types — producing 4 independent P&L streams (claude-polymarket, claude-alpaca, openai-polymarket, openai-alpaca).
**Methodology:** EARS (Easy Approach to Requirements Syntax).
**Priority levels:** P0 = must ship v1. P1 = should ship v1. P2 = v2 / backlog.

## Product Intent Summary

A single-operator, production-grade autonomous trading bot that runs two independent LLM-driven trading strategies side-by-side — one using Anthropic's Claude API, the other using OpenAI's GPT-5 family — each trading on **two venues**: Polymarket (on-chain prediction markets) and Alpaca (US equities via brokerage API). Shared scanning and execution scaffolding means the LLM is the only experimental variable. Each (bot × venue) pair has an independent wallet/account, bankroll, risk halt scope, and P&L attribution, producing 4 comparable streams. Deployed on AWS (ECS Fargate, RDS Postgres, S3, Secrets Manager) via CloudFormation, with dev + prod environments driven by GitHub Actions CI/CD. A Next.js + FastAPI dashboard (GitHub OAuth-gated to the operator only) surfaces side-by-side performance across all 4 streams, decision logs, and runtime config editing including per-venue DRY/LIVE toggles.

## Design Inspiration (Sources)

The architecture concepts in this spec are inspired by:
- **pmbot.md** — 4-agent bot design (scanner, brain, executor, exit), consensus logic, Kelly sizing, volume-exit trigger. See `../pmbot.md`.
- **`warproxxx/poly_data`** — historical-trade-ranked wallet strategy for Polymarket. Concept adopted; code re-implemented.
- **`Polymarket/py-clob-client`** — official Polymarket CLOB SDK. Used as a pip dependency (load-bearing infrastructure, not inspiration code).
- **`Polymarket/agents`** — agent framework patterns. Concepts adopted; code re-implemented.
- **`alpacahq/alpaca-py`** — official Alpaca Python SDK. Used as a pip dependency.

We do NOT depend on `Polymarket-Trading-Bot` or `polymarket-cli`. All strategy code is re-implemented.

## Component Map

| Code | Component | Responsibility |
|------|-----------|----------------|
| DATA | Data Pipeline | Daily Polymarket trade-dataset refresh to S3, target-wallet ranking |
| SCAN | Market Scanner | Venue-aware market filtering and shared candidate queue publishing |
| BRN  | Brain (LLM Strategist) | 4 checks × 3 sub-agents, venue-adapted check logic, thesis generation |
| EXE  | Executor | Kelly sizing, consensus logic, venue-aware order placement |
| EXIT | Exit Engine | 4 exit triggers (target, volume, stale, stop-loss), venue-aware monitoring |
| RISK | Risk Manager | Per-(bot × venue) position limits, daily-loss halts, LLM spend cap |
| WAL  | Wallet (EVM) | Polygon/EVM key gen, signing, balance tracking for Polymarket |
| CFG  | Config Service | Tiered, venue-aware runtime config, audit logging |
| POLY | Polymarket Venue | Polymarket CLOB client (REST + WS), `Venue` impl for prediction markets |
| ALPC | Alpaca Venue | Alpaca client (REST + streaming), `Venue` impl for equities |
| VEN  | Venue Abstraction | `Venue` Protocol, market-hours gating, venue registry |
| LLM  | LLM Abstraction | `Strategist` protocol, Anthropic + OpenAI impls |
| DASH | Dashboard API | FastAPI backend, venue-aware endpoints |
| UI   | Dashboard UI | Next.js + React frontend, 4 P&L streams |
| AUTH | Authentication | GitHub OAuth + allowlist |
| OBS  | Observability | Structured logs, SES alerts |
| INF  | Infrastructure | CloudFormation, ECS, RDS, S3, Secrets |
| CICD | CI/CD | GitHub Actions, OIDC, dev + prod pipelines |

**Notation:** `(bot, venue)` pairs — e.g., `(claude, polymarket)`, `(claude, alpaca)`, `(openai, polymarket)`, `(openai, alpaca)` — are the 4 independent trading scopes. Each has its own bankroll, LIVE_ENABLED flag, open positions, and daily P&L halt scope.

---

## DATA — Data Pipeline

Polymarket-specific trade dataset used only by the whale check on Polymarket venue.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-DATA-001 | P0 | The system shall fetch historical Polymarket trades by paging through the official trades API and accumulating results in partitioned Parquet files on S3. |
| REQ-DATA-002 | P0 | When the daily data-refresh job is triggered at 06:00 UTC, the system shall execute a full refresh of the Polymarket trade dataset. |
| REQ-DATA-003 | P0 | When a trade dataset refresh completes successfully, the system shall recompute the target-wallet list using the configured thresholds. |
| REQ-DATA-004 | P0 | The system shall expose configurable target-wallet thresholds: min trades (default 100), min win rate (default 0.70), top-N cap (default 50). |
| REQ-DATA-005 | P0 | If the data-refresh job fails, then the system shall retain the previous target-wallet list and emit an SES alert. |
| REQ-DATA-006 | P0 | The system shall retain the last 30 days of daily Parquet snapshots in S3 and delete older snapshots via S3 lifecycle rules. |
| REQ-DATA-007 | P0 | The system shall persist the current target-wallet list in Postgres in a `target_wallets` table accessible to the Polymarket-venue whale check. |
| REQ-DATA-008 | P0 | While a data-refresh job is running, the system shall not modify the active target-wallet list until the refresh completes successfully. |
| REQ-DATA-009 | P1 | The system shall provide a manual CLI command `refresh-data` to trigger an ad-hoc refresh outside the scheduled time. |

---

## SCAN — Market Scanner

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-SCAN-001 | P0 | When the scanner timer fires for a given venue (default every 300 seconds), the system shall fetch all active markets/instruments from that venue. |
| REQ-SCAN-002 | P0 | For each Polymarket market, the system shall score on: gap (\|estimate − midpoint\|), book depth (min of bid-side and ask-side depth in USDC), and hours to resolution. |
| REQ-SCAN-003 | P0 | For each Polymarket market, the system shall reject markets failing any configured filter: min gap (default 0.07), min depth (default $500 USDC), min hours to resolution (default 4), max hours to resolution (default 168). |
| REQ-SCAN-004 | P0 | When a market/instrument is rejected, the system shall log the specific rejection reason and persist it to the `market_scans` table (scoped by venue) for dashboard display. |
| REQ-SCAN-005 | P0 | The system shall publish accepted candidates to a venue-scoped candidate queue (Postgres `candidate_queue` table with `venue` column) accessible to both bots. |
| REQ-SCAN-006 | P0 | The Polymarket scanner shall respect geo-restrictions per-bot: each bot's Polymarket scanner input shall be filtered to its configured geo (US or International). |
| REQ-SCAN-007 | P0 | If the venue API returns an error during a scan, then the system shall retry up to 3 times with exponential backoff before skipping the scan and emitting an alert. |
| REQ-SCAN-008 | P0 | The system shall persist each scan run's metadata (venue, start time, end time, instruments fetched, accepted, rejected) for dashboard health display. |
| REQ-SCAN-009 | P1 | The system shall expose an API endpoint to trigger an immediate scan run for a specified venue outside the timer cadence. |
| REQ-SCAN-010 | P0 | For each Alpaca equity instrument, the system shall score on: unusual volume (today's volume / 20-day average), price momentum (5-day change), and LLM-estimated edge (from a lightweight base-rate pre-filter). |
| REQ-SCAN-011 | P0 | For each Alpaca equity instrument, the system shall reject instruments failing any configured filter: min relative volume (default 1.5), min dollar volume (default $10M/day), price within configurable bounds (default $5–$2000). |
| REQ-SCAN-012 | P0 | The Alpaca scanner shall limit its universe to the configured equity universe (default S&P 500 ∪ Nasdaq 100 ∪ top-liquid-ETF whitelist), overridable via a custom ticker whitelist per bot. |
| REQ-SCAN-013 | P0 | The Alpaca scanner shall suspend during market-closed periods (outside 09:30–16:00 ET on US equity trading days) as determined by the Alpaca calendar endpoint. |

---

## BRN — Brain (LLM Strategist)

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-BRN-001 | P0 | When a candidate is received for evaluation, the system shall run 4 checks in parallel; the check set adapts by venue. |
| REQ-BRN-002 | P0 | The system shall run 3 independent LLM calls per bot per candidate evaluation, one per strategy sub-agent: arbitrage, convergence, whale_copy (Polymarket) / flow_copy (Alpaca). |
| REQ-BRN-003 | P0 | On the Polymarket venue, the whale check shall query Polymarket's positions endpoint for each wallet in the current target list and return the count of target wallets holding a matching position. |
| REQ-BRN-004 | P0 | On the Alpaca venue, the whale check shall be replaced by an unusual-volume check that computes relative-volume (today / 20-day-avg) and price-action z-score over the trailing 20 days; no third-party data feed in v1. |
| REQ-BRN-005 | P0 | On both venues, the base_rate and news checks shall have web-search tool use enabled; the whale/unusual-volume and disposition checks shall not. |
| REQ-BRN-006 | P0 | Every LLM call shall request a structured JSON response matching the CheckResult schema: `{verdict: BUY|SELL|SKIP, confidence: 0..1, rationale: str, p_win: 0..1}`. |
| REQ-BRN-007 | P0 | For Alpaca trades, the thesis output shall additionally include `{target_price: float, stop_price: float, horizon_hours: int}` produced by the LLM to drive Kelly sizing and exit bounds. |
| REQ-BRN-008 | P0 | If the LLM returns malformed JSON, then the system shall retry up to 2 times, then emit a SKIP result with the error logged. |
| REQ-BRN-009 | P0 | The system shall persist every LLM call's prompt, response, model ID, venue, latency, input tokens, output tokens, and estimated cost to the bot-scoped `decisions` table in Postgres. |
| REQ-BRN-010 | P0 | The Claude implementation shall enable Anthropic prompt caching on the static system-prompt portion of every call. |
| REQ-BRN-011 | P0 | When all 4 checks complete for a candidate, the system shall generate a thesis: if 3-or-more checks agree on verdict, produce a thesis with `confidence = mean(agreeing confidences)`; otherwise produce SKIP. |
| REQ-BRN-012 | P0 | If thesis confidence is below the configurable threshold (default 0.75), then the system shall skip the trade. |
| REQ-BRN-013 | P0 | The system shall support per-check, per-venue model configuration: each of the 4 checks (× 2 venues) and each of the 3 sub-agents can use a different model ID. |
| REQ-BRN-014 | P0 | The LLM client shall retry on 429 rate-limit errors with exponential backoff up to 3 times. |
| REQ-BRN-015 | P0 | If the LLM provider returns 5 or more consecutive failures, then the system shall halt that bot's decisioning across all venues and emit an SES alert. |
| REQ-BRN-016 | P0 | The system shall track daily LLM spend per bot (sum across venues and checks) and halt decisioning when the cap is reached (delegated to RISK). |
| REQ-BRN-017 | P0 | The system shall track per-bot-per-venue LLM spend breakdown for dashboard attribution (not used for halting). |
| REQ-BRN-018 | P1 | The system shall cache recent whale-check results for 5 minutes (Polymarket) and unusual-volume check results for 5 minutes (Alpaca) to avoid redundant queries. |

---

## EXE — Executor

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-EXE-001 | P0 | When a thesis is approved, the system shall compute position size using the Kelly criterion: `f* = (p·b − q) / b`, with `b` and `q` derived from venue-specific payoff structure. |
| REQ-EXE-002 | P0 | The system shall cap Kelly fraction at a configurable quarter-Kelly maximum (default 0.25), configurable per venue. |
| REQ-EXE-003 | P0 | If Kelly `f*` is ≤ 0, then the system shall skip the trade. |
| REQ-EXE-004 | P0 | The system shall apply consensus logic from the 3 sub-agents: 2-or-more agree on verdict → full sized position; 1 agrees → half-sized position; 0 agree → skip. |
| REQ-EXE-005 | P0 | On the Polymarket venue, the system shall submit a limit order at the bot's estimated fair price bounded by current midpoint ± configurable slippage tolerance (default 0.02). |
| REQ-EXE-006 | P0 | On the Alpaca venue, the system shall submit a limit order at mid-price ± configurable slippage tolerance (default 0.001 = 0.1%) and, if unfilled after a configurable TTL (default 300 seconds), cancel and submit a market order as fallback. |
| REQ-EXE-007 | P0 | While DRY_RUN mode is active for a (bot, venue) pair, the system shall log the intended order to the `orders` table with `status = 'SIMULATED'` but not submit it to the venue. |
| REQ-EXE-008 | P0 | While LIVE_ENABLED is false for a (bot, venue) pair, the system shall behave as if DRY_RUN is active for that pair. |
| REQ-EXE-009 | P0 | Polymarket orders shall be signed with the bot's configured EVM private key via py-clob-client; Alpaca orders shall be authenticated with the bot's Alpaca API keys. |
| REQ-EXE-010 | P0 | When an order is submitted, the system shall record the order ID, venue, side, size, price, timestamp, and linked thesis ID in Postgres. |
| REQ-EXE-011 | P0 | If a Polymarket order does not fill within a configurable TTL (default 300 seconds), then the system shall cancel the order and log the outcome. |
| REQ-EXE-012 | P0 | If the (bot, venue) pair already has max open positions (default 5 per venue, configurable), then the system shall reject the new trade and log the reason. |
| REQ-EXE-013 | P0 | If the proposed position size exceeds the max-position percentage of the (bot, venue) pair's bankroll (default 25%), then the system shall cap the size at the limit. |
| REQ-EXE-014 | P0 | When an order fills, the system shall record the fill price, fill time, and update the linked position row. |
| REQ-EXE-015 | P0 | When an Alpaca entry order fills, the system shall submit a bracket stop-loss order server-side via Alpaca's OCO/bracket order API using the LLM-provided `stop_price`. |

---

## EXIT — Exit Engine

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-EXIT-001 | P0 | When the exit timer fires (default every 60 seconds), the system shall evaluate every open position across all venues for applicable exit triggers. |
| REQ-EXIT-002 | P0 | If the current price ≥ entry + (target − entry) × 0.85 (configurable target-hit multiplier), then the system shall submit a close order with reason TARGET_HIT. |
| REQ-EXIT-003 | P0 | If the volume in the trailing 10 minutes ≥ 3× (configurable multiplier) the rolling average volume, then the system shall submit a close order with reason VOLUME_EXIT. |
| REQ-EXIT-004 | P0 | If a position is older than 24 hours (configurable) and the absolute price change since entry is < 2% (configurable), then the system shall submit a close order with reason STALE_THESIS. |
| REQ-EXIT-005 | P0 | On Alpaca positions, if the current price ≤ the LLM-set stop_price (or Alpaca server-side bracket stop fires), then the system shall record a close with reason STOP_LOSS. |
| REQ-EXIT-006 | P0 | On Alpaca positions, when the configured trade horizon (default 72 hours, configurable per trade or per bot) elapses, the system shall submit a market close order with reason HORIZON_EXIT. |
| REQ-EXIT-007 | P0 | All exit-trigger thresholds (target-hit multiplier, volume multiplier, stale age window, stale price-change threshold, horizon hours) shall be configurable via CFG and overridable per venue. |
| REQ-EXIT-008 | P0 | Exit logic shall run even when LIVE_ENABLED is false, for DRY_RUN accounting accuracy and simulated P&L. |
| REQ-EXIT-009 | P0 | For Polymarket positions, the system shall subscribe via WebSocket to Polymarket's order-book feed for each market with an open position to track live volume. |
| REQ-EXIT-010 | P0 | For Alpaca positions, the system shall subscribe via Alpaca's streaming trade/quote feed to each symbol with an open position to track live volume. |
| REQ-EXIT-011 | P0 | If a streaming connection drops (either venue), then the system shall fall back to REST polling and attempt reconnection with exponential backoff. |
| REQ-EXIT-012 | P0 | When an exit order fills, the system shall mark the position as closed, compute realized P&L, and update the (bot, venue) pair's bankroll. |
| REQ-EXIT-013 | P0 | When a Polymarket market resolves while a position is still open, the system shall record the resolution outcome and settle the position. |
| REQ-EXIT-014 | P0 | When the Alpaca market closes (16:00 ET) while a position is open and the bot's configuration specifies no overnight holds (configurable per bot, default true for v1), then the system shall submit a market close order before 15:55 ET. |

---

## RISK — Risk Manager

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-RISK-001 | P0 | The system shall track daily P&L (realized + unrealized) per (bot, venue) pair, with reset at 00:00 UTC. |
| REQ-RISK-002 | P0 | If daily drawdown reaches 50% of the (bot, venue) pair's start-of-day bankroll (configurable), then the system shall halt that pair until 00:00 UTC. |
| REQ-RISK-003 | P0 | While a (bot, venue) risk halt is active, the system shall stop opening new positions in that pair but allow exit logic to continue running on existing open positions in that pair. |
| REQ-RISK-004 | P0 | A halt on one (bot, venue) pair shall not halt other pairs; the 4 pairs are independent halt scopes. |
| REQ-RISK-005 | P0 | The system shall enforce a max-concurrent-open-positions limit per (bot, venue) pair (default 5 per pair, configurable). |
| REQ-RISK-006 | P0 | The system shall enforce a max-position-size limit per trade per (bot, venue) pair (default 25% of pair's bankroll, configurable). |
| REQ-RISK-007 | P0 | The system shall track daily LLM spend per bot (summed across venues), accumulating estimated USD cost from every LLM API call. |
| REQ-RISK-008 | P0 | If daily LLM spend reaches the configurable per-bot cap (default $20/bot/day), then the system shall halt that bot's decisioning across all venues until 00:00 UTC. |
| REQ-RISK-009 | P0 | When LIVE_ENABLED is toggled off for a (bot, venue) pair mid-session, the system shall continue running exit logic on existing positions in that pair but reject all new trades for that pair. |
| REQ-RISK-010 | P0 | Every risk-halt event shall emit an SES alert with the reason, bot name, venue, and current metrics. |
| REQ-RISK-011 | P0 | The system shall expose the current risk-halt status and metrics per (bot, venue) pair via the dashboard `/api/health` endpoint. |

---

## WAL — Wallet (EVM)

Polymarket-specific. Alpaca account/key management is covered by ALPC.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-WAL-001 | P0 | The system shall provide a CLI command `setup-wallets` that generates a fresh EVM wallet for each bot for Polymarket use. |
| REQ-WAL-002 | P0 | When `setup-wallets` runs, the system shall print the public addresses to stdout and write the private keys to AWS Secrets Manager (prod) or `.env` (local). |
| REQ-WAL-003 | P0 | The system shall load the EVM private key at startup from the configured secret path when the Polymarket venue is enabled. |
| REQ-WAL-004 | P0 | The system shall expose each bot's EVM wallet USDC and MATIC balances via the dashboard `/api/health` endpoint. |
| REQ-WAL-005 | P0 | If USDC balance is below a configurable threshold (default $10), then the system shall emit a low-balance SES alert. |
| REQ-WAL-006 | P0 | If MATIC balance is below a configurable gas threshold (default 0.5 MATIC), then the system shall emit a low-gas SES alert. |
| REQ-WAL-007 | P0 | All EVM signing operations shall use `eth-account` with the loaded private key. |
| REQ-WAL-008 | P0 | EVM private keys shall never be written to logs, dashboard API responses, or audit records. |
| REQ-WAL-009 | P0 | The `setup-wallets` command shall run a pre-flight checklist: verify network connectivity to Polygon, verify Secrets Manager write permissions, print public addresses for funding. |

---

## CFG — Config Service

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-CFG-001 | P0 | The system shall store runtime-editable configuration in a Postgres `config` table with composite key `(bot, venue)` where `venue` may be `'*'` for bot-level values. |
| REQ-CFG-002 | P0 | Configuration fields shall be tiered as Tier 1 (dashboard-editable), Tier 2 (env-var, restart required), Tier 3 (code-only). |
| REQ-CFG-003 | P0 | Bot-level Tier 1 fields (venue = `'*'`) shall include: llm_daily_spend_cap, model-per-check-per-venue, auth_allowlist. |
| REQ-CFG-004 | P0 | Per-(bot, venue) Tier 1 fields shall include: LIVE_ENABLED, starting_bankroll, max_position_pct, max_daily_loss_pct, max_open_positions, kelly_max_fraction, thesis_confidence_threshold, scanner_cadence_sec, exit_cadence_sec, target_hit_multiplier, volume_exit_multiplier, stale_window_hours, stale_price_change_pct, order_ttl_sec, slippage_tolerance. |
| REQ-CFG-005 | P0 | Polymarket-specific Tier 1 fields shall include: geo, min_gap, min_depth, min_hours_to_resolution, max_hours_to_resolution, target_wallet_min_trades, target_wallet_min_win_rate, target_wallet_top_n, whale_check_cache_sec, usdc_low_balance_threshold, matic_low_balance_threshold. |
| REQ-CFG-006 | P0 | Alpaca-specific Tier 1 fields shall include: equity_universe (preset name or custom ticker list), min_relative_volume, min_dollar_volume, price_range_low, price_range_high, trade_horizon_hours, allow_overnight_holds, unusual_volume_cache_sec. |
| REQ-CFG-007 | P0 | Tier 2 fields (env-var, restart required) shall include: database URL, LLM API keys, wallet private-key path, Alpaca API keys (paper and live), AWS region. |
| REQ-CFG-008 | P0 | Tier 3 (code-only) shall include: the 4-check logic, 3-sub-agent logic, scoring formula math, Kelly formula math, consensus logic. |
| REQ-CFG-009 | P0 | When a Tier 1 config value is changed via the dashboard API, the system shall persist the change immediately and apply it on the next relevant event loop. |
| REQ-CFG-010 | P0 | Every config change shall be logged to a `config_audit` table with timestamp, actor email, bot, venue, field, old value, new value. |
| REQ-CFG-011 | P0 | All Tier 1 fields shall have server-side validation rules (type, min, max, enum where applicable). |
| REQ-CFG-012 | P0 | When LIVE_ENABLED is toggled for any (bot, venue) pair via the dashboard, the system shall emit an SES audit alert. |
| REQ-CFG-013 | P0 | The config service shall expose a read endpoint that returns the effective config for any (bot, venue) pair, merging bot-level and pair-level values. |

---

## POLY — Polymarket Venue

`POLY` is the `Venue` protocol implementation for Polymarket.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-POLY-001 | P0 | The system shall use the official `py-clob-client` SDK as the Polymarket integration layer. |
| REQ-POLY-002 | P0 | The system shall support both US and International Polymarket endpoints, configurable per bot. |
| REQ-POLY-003 | P0 | The system shall use REST polling for market and book data requested by the scanner. |
| REQ-POLY-004 | P0 | The system shall use WebSocket subscriptions for live order-book updates on markets with open positions. |
| REQ-POLY-005 | P0 | The system shall implement exponential backoff retry (max 3 attempts) on all Polymarket API calls. |
| REQ-POLY-006 | P0 | The system shall respect Polymarket rate limits and log every API call with endpoint, latency, status. |
| REQ-POLY-007 | P0 | If the Polymarket API is entirely unreachable for 2 consecutive minutes, then the system shall emit an SES alert. |
| REQ-POLY-008 | P0 | The Polymarket venue shall implement the `Venue` Protocol defined in VEN. |

---

## ALPC — Alpaca Venue

`ALPC` is the `Venue` protocol implementation for Alpaca equities.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-ALPC-001 | P0 | The system shall use the official `alpaca-py` SDK as the Alpaca integration layer. |
| REQ-ALPC-002 | P0 | The system shall support both Alpaca paper (`paper-api.alpaca.markets`) and live (`api.alpaca.markets`) endpoints with separate API key pairs per environment. |
| REQ-ALPC-003 | P0 | Each bot shall have its own Alpaca account (one paper account + one live account per bot) with independent key pairs. |
| REQ-ALPC-004 | P0 | The system shall provide a CLI command `setup-alpaca` that walks the operator through Alpaca account creation (manual on alpaca.markets), prompts for key paste-in, validates the keys by calling `GET /v2/account`, and writes them to AWS Secrets Manager (prod) or `.env` (local). |
| REQ-ALPC-005 | P0 | The Alpaca venue shall operate on live endpoints only when LIVE_ENABLED is true for the (bot, alpaca) pair; otherwise it shall use the paper endpoint. |
| REQ-ALPC-006 | P0 | The system shall query the Alpaca market calendar endpoint daily to build a cache of trading days and market-hour boundaries (09:30–16:00 ET). |
| REQ-ALPC-007 | P0 | The system shall use Alpaca's real-time data streaming (SIP feed or IEX feed per subscription tier, configurable) for live trade/quote subscriptions on open positions. |
| REQ-ALPC-008 | P0 | The Alpaca venue shall implement the `Venue` Protocol defined in VEN. |
| REQ-ALPC-009 | P0 | The system shall expose each bot's Alpaca account equity, buying power, and day trade count via the dashboard `/api/health` endpoint. |
| REQ-ALPC-010 | P0 | If the Alpaca account buying power falls below the (bot, alpaca) pair's configured bankroll, then the system shall emit an SES alert. |
| REQ-ALPC-011 | P0 | If the Alpaca API is entirely unreachable for 2 consecutive minutes during market hours, then the system shall emit an SES alert. |
| REQ-ALPC-012 | P0 | The Alpaca venue shall respect Alpaca's pattern day trader rules: if a (bot, alpaca) pair's account equity < $25,000, the bot shall limit day trades to < 4 in any rolling 5-business-day window. |
| REQ-ALPC-013 | P0 | All Alpaca API keys shall never be written to logs, dashboard API responses, or audit records. |

---

## VEN — Venue Abstraction

`VEN` defines the `Venue` Protocol and shared venue-lifecycle logic.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-VEN-001 | P0 | The system shall define a `Venue` Protocol exposing at minimum: `list_active_markets()`, `get_market_data(id)`, `get_book(id)`, `place_order(spec)`, `cancel_order(id)`, `get_positions(bot)`, `get_account_balance(bot)`, `subscribe_to_updates(ids)`, `is_market_open()`. |
| REQ-VEN-002 | P0 | The system shall provide two `Venue` implementations: `PolymarketVenue` (in POLY) and `AlpacaVenue` (in ALPC). |
| REQ-VEN-003 | P0 | The system shall maintain a venue registry keyed by venue name, providing lookup and iteration for scanner/executor/exit loops. |
| REQ-VEN-004 | P0 | Each `Venue` implementation shall expose its market-hours predicate `is_market_open()`; Polymarket returns `true` always; Alpaca returns `true` only during configured trading hours on configured trading days. |
| REQ-VEN-005 | P0 | Scanner, executor, and exit loops shall be venue-agnostic and iterate over registered venues, calling the `Venue` interface. |
| REQ-VEN-006 | P0 | The system shall support enabling/disabling a venue per bot via config; a disabled venue is skipped entirely for that bot. |
| REQ-VEN-007 | P0 | Each `Venue` implementation shall expose a `health_check()` coroutine returning status and latency used by the `/api/health` endpoint. |
| REQ-VEN-008 | P0 | The system shall support injecting a mocked `Venue` implementation for tests and local dev without real API calls. |

---

## LLM — LLM Abstraction

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-LLM-001 | P0 | The system shall define a `Strategist` Protocol exposing `async evaluate(check_type, venue, market, context) -> CheckResult`. |
| REQ-LLM-002 | P0 | The system shall provide two Strategist implementations: `AnthropicStrategist` (Claude) and `OpenAIStrategist` (GPT-5 family). |
| REQ-LLM-003 | P0 | Default models shall be `claude-opus-4-7` for the Claude bot and `gpt-5` for the OpenAI bot, both configurable per check per venue via Tier 1 config. |
| REQ-LLM-004 | P0 | Both Strategist implementations shall return JSON-formatted output matching the CheckResult schema (with venue-specific extensions — e.g., Alpaca check results include target_price, stop_price, horizon_hours). |
| REQ-LLM-005 | P0 | The `AnthropicStrategist` shall enable Anthropic prompt caching on static system prompts. |
| REQ-LLM-006 | P0 | Both Strategist implementations shall support web-search tool use, enabled per-check via Tier 1 config (default: news and base_rate only). |
| REQ-LLM-007 | P0 | Both Strategist implementations shall track and return per-call token usage (input, output, cached) and estimated USD cost. |
| REQ-LLM-008 | P0 | If an LLM call fails after all retries, then the Strategist shall return a CheckResult with `verdict=SKIP` and the error logged. |
| REQ-LLM-009 | P0 | The system shall support injecting a mocked Strategist for tests and local dev without real API calls. |
| REQ-LLM-010 | P0 | Prompts shall be templated per venue: Polymarket prompts include market question and resolution rules; Alpaca prompts include ticker, sector, last earnings date, and recent news. |

---

## DASH — Dashboard API (FastAPI)

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-DASH-001 | P0 | The system shall expose a FastAPI service at `/api/*` serving the dashboard backend. |
| REQ-DASH-002 | P0 | All `/api/*` endpoints except `/api/auth/*` and `/api/health/ping` shall require a valid authenticated session. |
| REQ-DASH-003 | P0 | The API shall expose read endpoints: GET `/api/bots`, GET `/api/bots/{name}`, GET `/api/bots/{name}/venues/{venue}/positions`, GET `/api/bots/{name}/venues/{venue}/trades`, GET `/api/bots/{name}/decisions` (with `venue` query param), GET `/api/markets/queue?venue=`, GET `/api/markets/scans?venue=`, GET `/api/config?bot=&venue=`, GET `/api/config/audit`, GET `/api/health`. |
| REQ-DASH-004 | P0 | The API shall expose mutation endpoint PATCH `/api/config` (accepting bot, venue, field, value) that requires a confirmation field in the body and logs every change to audit. |
| REQ-DASH-005 | P0 | The API shall expose a WebSocket endpoint `/api/live` for real-time P&L and decision stream updates across all (bot, venue) pairs. |
| REQ-DASH-006 | P0 | The API shall validate every request and return RFC 7807 Problem Details JSON on error. |
| REQ-DASH-007 | P0 | All endpoints shall be covered by an OpenAPI 3.1 schema auto-generated from FastAPI. |

---

## UI — Dashboard UI (Next.js)

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-UI-001 | P0 | The system shall provide a Next.js app with App Router, server-side rendering, and TailwindCSS for styling. |
| REQ-UI-002 | P0 | The UI shall expose pages at: `/` (overview), `/bots/{name}` (per-bot with venue tabs), `/decisions`, `/markets`, `/config`, `/health`. |
| REQ-UI-003 | P0 | The `/` overview page shall display 4 P&L streams (claude-polymarket, claude-alpaca, openai-polymarket, openai-alpaca) in both a combined chart and a faceted 2×2 grid with cumulative and daily P&L. |
| REQ-UI-004 | P0 | The `/` overview page shall display a summary table with win rate, trade count, Sharpe, and current bankroll per (bot, venue) pair. |
| REQ-UI-005 | P0 | The `/bots/{name}` page shall provide tabs per venue; each tab shows that pair's open positions, trade history (paginated), recent decisions with full LLM prompt/response, and current per-pair config. |
| REQ-UI-006 | P0 | The `/decisions` page shall list every LLM call with filters by bot, venue, date range, check type, sub-agent, and verdict. |
| REQ-UI-007 | P0 | The `/markets` page shall display the current candidate queue grouped by venue with per-market scores and a list of recently rejected markets with rejection reasons. |
| REQ-UI-008 | P0 | The `/config` page shall provide a form editor for Tier 1 fields grouped by (bot, venue), with type-appropriate inputs, validation, confirmation modal on save, and an audit-log panel. |
| REQ-UI-009 | P0 | The `/health` page shall display: last scanner-run timestamp per venue, last data-refresh timestamp, LLM API status per bot, Polymarket wallet USDC + MATIC balances per bot, Alpaca account equity + buying power per bot, daily LLM-spend counter per bot, risk-halt status per (bot, venue) pair, LIVE_ENABLED status per (bot, venue) pair. |
| REQ-UI-010 | P0 | All pages shall display a visually prominent banner indicating each (bot, venue) pair's DRY / LIVE mode. |
| REQ-UI-011 | P0 | The UI shall subscribe to the `/api/live` WebSocket for real-time P&L and decision updates on the overview and bot-detail pages. |
| REQ-UI-012 | P0 | The UI shall redirect unauthenticated users to the GitHub OAuth flow. |

---

## AUTH — Authentication

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-AUTH-001 | P0 | The system shall use GitHub OAuth for dashboard authentication. |
| REQ-AUTH-002 | P0 | The system shall maintain an allowlist of permitted GitHub-registered emails (configurable via the `auth_allowlist` config field, default `['yaw.etse@gmail.com']`). |
| REQ-AUTH-003 | P0 | If an authenticated user's primary GitHub email is not on the allowlist, then the system shall deny access and return HTTP 403. |
| REQ-AUTH-004 | P0 | The system shall set session cookies with attributes HttpOnly, Secure, SameSite=Lax, and configurable max-age (default 12 hours). |
| REQ-AUTH-005 | P0 | The system shall provide a CLI command `setup-oauth` that walks the operator through GitHub OAuth app creation and writes the client ID and client secret to Secrets Manager (prod) or `.env` (local). |
| REQ-AUTH-006 | P0 | The system shall include callback URLs for dev and prod environments; the `setup-oauth` command shall print both for the operator to register in GitHub. |
| REQ-AUTH-007 | P0 | The system shall log every authentication event (success, denial, logout) to the `auth_events` table. |

---

## OBS — Observability

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-OBS-001 | P0 | All application logs shall be structured JSON and emitted to CloudWatch via stdout. |
| REQ-OBS-002 | P0 | Every log record shall include: timestamp, level, service, bot, venue (where applicable), correlation_id, message, context. |
| REQ-OBS-003 | P0 | Sensitive fields (EVM private keys, Alpaca API keys, LLM API keys, session cookies, wallet seed phrases) shall be redacted from all logs. |
| REQ-OBS-004 | P0 | The system shall emit an SES email alert when any of the following occurs: bot crash (unhandled exception), risk halt triggered, LIVE_ENABLED toggled, USDC balance below threshold, MATIC balance below threshold, Alpaca buying-power anomaly, LLM sustained errors (≥ 5 consecutive failures), failed scanner run, failed daily data-refresh run, Polymarket API unreachable ≥ 2 min, Alpaca API unreachable ≥ 2 min during market hours. |
| REQ-OBS-005 | P0 | When the daily-summary timer fires at 08:00 UTC, the system shall email yesterday's P&L, trade count, win rate, and Sharpe ratio for all 4 (bot, venue) pairs. |
| REQ-OBS-006 | P0 | CloudWatch log retention shall be 30 days; LLM prompt/response logs shall be retained 90 days in Postgres, then archived to S3 (gzipped JSONL) and deleted from Postgres. |
| REQ-OBS-007 | P0 | The system shall emit CloudWatch metrics for: scanner runs (per venue), thesis generations (per bot per venue), trades executed (per bot per venue), risk halts (per pair), LLM calls, LLM costs. |

---

## INF — Infrastructure

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-INF-001 | P0 | All AWS infrastructure shall be defined in CloudFormation templates; manual console changes shall not be part of steady-state operation. |
| REQ-INF-002 | P0 | The system shall deploy to a single AWS account with resources prefixed by environment: `claude-poly-bot-dev-*`, `claude-poly-bot-prod-*`. |
| REQ-INF-003 | P0 | The system shall provision per environment: VPC with public and private subnets, ECS Fargate cluster, RDS Postgres (db.t4g.micro), S3 bucket for trade data, ECR repository, Secrets Manager secrets (LLM API keys, EVM private keys, Alpaca API key pairs per bot per environment tier, OAuth client secret, session secret), IAM roles, CloudWatch log groups, SES configuration, Application Load Balancer, Route 53 records, ACM TLS certificate. |
| REQ-INF-004 | P0 | Dev and prod environments shall be identical in topology; only instance sizing, retention policies, backup frequency, and Alpaca endpoint (paper-only in dev, paper+live in prod) may differ. |
| REQ-INF-005 | P0 | The system shall run 5 always-on ECS Fargate services per environment: `scanner`, `claude-bot`, `openai-bot`, `dashboard-api`, `dashboard-ui`. Each bot service handles both venues in-process. |
| REQ-INF-006 | P0 | The system shall run 1 scheduled ECS task per environment: `data-refresh`, triggered daily at 06:00 UTC via EventBridge. |
| REQ-INF-007 | P0 | All secrets shall be stored in AWS Secrets Manager; services shall consume secrets via IAM-authorized retrieval at startup. |
| REQ-INF-008 | P0 | All resources shall be provisioned in AWS region `us-east-1`. |
| REQ-INF-009 | P0 | The RDS instance shall have automated daily backups with 7-day retention in prod and 1-day retention in dev. |
| REQ-INF-010 | P0 | The Application Load Balancer shall terminate TLS and route `/api/*` to `dashboard-api` and all other paths to `dashboard-ui`. |
| REQ-INF-011 | P0 | The system shall provision separate Secrets Manager entries per (bot × environment × alpaca-mode) for Alpaca API keys: e.g., `claude-poly-bot-prod-alpaca-claude-paper`, `claude-poly-bot-prod-alpaca-claude-live`, and matching openai entries. |

---

## CICD — CI/CD

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-CICD-001 | P0 | When a pull request is opened or updated against any branch, the system shall run linting, type-checking, unit tests, integration tests (with mocked Polymarket + Alpaca + LLM clients), and a Docker build (without push). |
| REQ-CICD-002 | P0 | When code is merged to `develop`, the system shall push the Docker image to ECR, deploy to the dev environment via CloudFormation, and run smoke tests against dev. |
| REQ-CICD-003 | P0 | When code is merged to `main`, the system shall push the Docker image to ECR, deploy to the prod environment via CloudFormation, and run smoke tests against prod. |
| REQ-CICD-004 | P0 | GitHub Actions shall authenticate to AWS via OIDC federation; no long-lived AWS access keys shall be stored in GitHub secrets. |
| REQ-CICD-005 | P0 | The system shall provide a manually triggered GitHub Actions workflow for emergency rollback that redeploys the previous ECR image tag to the specified environment. |
| REQ-CICD-006 | P0 | If post-deploy smoke tests fail, then the system shall automatically roll back to the previous image tag and emit an SES alert. |
| REQ-CICD-007 | P0 | Local development shall be possible via `docker compose up` reading from `.env` with DRY_RUN=true as the default for both venues. |
| REQ-CICD-008 | P0 | The repository shall include a `.devcontainer/devcontainer.json` to support GitHub Codespaces and Claude Code Web. |
| REQ-CICD-009 | P0 | All integration tests shall be runnable fully offline with mocked external dependencies (Polymarket, Alpaca, LLM APIs, AWS services via moto or equivalent). |

---

## Summary

| Component | P0 | P1 | P2 | Total |
|-----------|-----|-----|-----|-------|
| DATA | 8 | 1 | 0 | 9 |
| SCAN | 12 | 1 | 0 | 13 |
| BRN  | 17 | 1 | 0 | 18 |
| EXE  | 15 | 0 | 0 | 15 |
| EXIT | 14 | 0 | 0 | 14 |
| RISK | 11 | 0 | 0 | 11 |
| WAL  | 9 | 0 | 0 | 9 |
| CFG  | 13 | 0 | 0 | 13 |
| POLY | 8 | 0 | 0 | 8 |
| ALPC | 13 | 0 | 0 | 13 |
| VEN  | 8 | 0 | 0 | 8 |
| LLM  | 10 | 0 | 0 | 10 |
| DASH | 7 | 0 | 0 | 7 |
| UI   | 12 | 0 | 0 | 12 |
| AUTH | 7 | 0 | 0 | 7 |
| OBS  | 7 | 0 | 0 | 7 |
| INF  | 11 | 0 | 0 | 11 |
| CICD | 9 | 0 | 0 | 9 |
| **Total** | **191** | **3** | **0** | **194** |
