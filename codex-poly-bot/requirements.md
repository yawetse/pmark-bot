# codex-poly-bot Requirements

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.4
**Date:** 2026-08-02
**Status:** APPROVED

## Product Intent

`codex-poly-bot` is a standalone live-capable trading bot with a Python/FastAPI backend and a Next.js React dashboard. The bot supports Polymarket US, Polymarket International, Kalshi event markets, and traditional stock-market trading through Alpaca for stocks and ETFs. The bot defaults to Polymarket US, disables every venue unless explicitly enabled by configuration, and runs OpenAI and Claude evaluators at the same time with separate budgets, venue accounts or wallets, and Postgres schemas.

The first version includes market scanning, daily full and incremental S3 data downloads, wallet target analysis, LLM thesis scoring, arbitrage, convergence, whale-copy strategies, Alpaca stock/ETF signal evaluation, Kelly sizing, configurable risk controls, limit and market order execution, exit monitoring, dashboard configuration, GitHub OAuth login, SES email notifications, model and venue comparison analytics, and AWS deployment. Dry-run mode exists from day one, live trading defaults to off, and configuration changes made in the dashboard apply on the next trading loop. The system runs locally with gitignored `.env` files and deploys through GitHub Actions to AWS `us-east-1` development and production environments.

Recurring funding support observes venue-managed deposits for each model-provider account, reconciles deposit and withdrawal activity, reports funding history and missed occurrences, and removes external cash flows from trading-return calculations. Alpaca direct incoming ACH transfers are supported only through separately entitled Broker API credentials and an approved venue-managed ACH relationship. Plaid bank onboarding, raw bank-account storage, and direct Polymarket funding are outside this release. Direct transfers remain disabled with zero limits until an authorized operator configures nonzero safety caps.

## Source References

The implementation shall not depend on the referenced repos at runtime unless later requirements explicitly add that dependency. The repos and docs below inform the design:

- `pmbot.md`
- `https://docs.polymarket.com/quickstart`
- `https://docs.polymarket.com/api-reference/authentication`
- `https://docs.polymarket.us/getting-started/welcome`
- `https://github.com/warproxxx/poly_data`
- `https://github.com/Polymarket/polymarket-cli`
- `https://github.com/Polymarket/agents`
- `https://github.com/dylanpersonguy/Polymarket-Trading-Bot`
- `https://docs.alpaca.markets/`
- `https://docs.alpaca.markets/docs/trading/paper-trading/`
- `https://docs.alpaca.markets/docs/trading/orders/`
- `https://docs.alpaca.markets/docs/about-market-data-api`
- `https://docs.alpaca.markets/us/docs/account-activities`
- `https://docs.alpaca.markets/us/reference/createtransferforaccount`
- `https://docs.alpaca.markets/reference/createachrelationshipforaccount`
- `https://docs.polymarket.us/api-reference/portfolio/get-activities`
- `https://docs.kalshi.com/getting_started/api_environments`
- `https://docs.kalshi.com/getting_started/quick_start_authenticated_requests`
- `https://docs.kalshi.com/getting_started/fixed_point_migration`
- `https://docs.kalshi.com/getting_started/rate_limits`
- `https://docs.kalshi.com/getting_started/historical_data`
- `https://docs.kalshi.com/api-reference/market/get-markets`
- `https://docs.kalshi.com/api-reference/market/get-multiple-market-orderbooks`
- `https://docs.kalshi.com/api-reference/orders/create-order-v2`
- `https://docs.kalshi.com/api-reference/orders/cancel-order-v2`
- `https://docs.kalshi.com/api-reference/portfolio/get-balance`

## Requirements

### Venue Integration

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-VEN-001 | P0 | The system shall support Polymarket US and Polymarket International as configurable trading venues. |
| REQ-VEN-002 | P0 | When the system starts without an explicit venue setting, the system shall select Polymarket US as the default venue. |
| REQ-VEN-003 | P0 | If a venue is not explicitly enabled by configuration, then the system shall refuse to scan, score, or trade on that venue. |
| REQ-VEN-004 | P0 | When the system places live orders, the system shall use official Polymarket SDK or documented API clients for that venue. |
| REQ-VEN-005 | P0 | If a venue configuration is unsupported for the current environment, then the system shall block live orders and record the refusal reason. |
| REQ-VEN-006 | P1 | When the dashboard updates venue configuration, the system shall apply the change on the next trading loop without a process restart. |

### Alpaca Stock and ETF Integration

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-ALP-001 | P0 | The system shall support Alpaca as a configurable brokerage venue for stocks and ETFs. |
| REQ-ALP-002 | P0 | The system shall exclude Alpaca options, crypto, hard-to-borrow locates, and margin-funded long purchases from this release. |
| REQ-ALP-003 | P0 | When the system uses Alpaca, the system shall use Alpaca's official Python SDK or documented HTTP APIs for account, market data, position, and order operations. |
| REQ-ALP-004 | P0 | The system shall require separate Alpaca account identifiers per environment and model provider. |
| REQ-ALP-005 | P0 | While global dry-run mode is enabled, the system shall record simulated Alpaca stock and ETF orders without submitting orders to Alpaca paper or live endpoints. |
| REQ-ALP-006 | P0 | While global dry-run mode is disabled and Alpaca is enabled, the system shall submit approved Alpaca orders to the configured Alpaca account mode subject to risk checks. |
| REQ-ALP-007 | P0 | The system shall support Alpaca paper and live account modes as environment and dashboard configuration values. |
| REQ-ALP-008 | P0 | If an Alpaca order would require margin for a long purchase or create a short position while shorting is disabled, then the system shall refuse the order. |
| REQ-ALP-009 | P0 | The system shall enforce a default Alpaca max stock or ETF position size of 100 USD per symbol and model provider. |
| REQ-ALP-010 | P0 | The system shall enforce a default Alpaca max daily loss of 100 USD per model provider. |
| REQ-ALP-011 | P0 | The system shall enforce a default Alpaca max open stock or ETF position count of 5 per model provider. |
| REQ-ALP-012 | P0 | The system shall enforce a default Alpaca max portfolio allocation of 10 percent per symbol and model provider. |
| REQ-ALP-013 | P0 | The system shall enforce a default Alpaca market order slippage threshold of 0.5 percent. |
| REQ-ALP-014 | P0 | The dashboard shall allow authorized users to change Alpaca account mode, enabled flag, stock risk limits, symbol universe, and slippage threshold. |
| REQ-ALP-015 | P1 | If Alpaca market data is unavailable, rate-limited, stale, or outside configured trading hours, then the system shall block Alpaca live orders and record the refusal reason. |
| REQ-ALP-016 | P0 | If an Alpaca credential resolves to the same account identifier as another model provider in the same environment and account mode, then the system shall block Alpaca live trading for the duplicated account and record the refusal reason. |
| REQ-ALP-017 | P0 | The system shall reconcile Alpaca account positions, open orders, and buying power with Postgres before permitting Alpaca live orders. |
| REQ-ALP-018 | P0 | If Alpaca reconciliation detects an unresolved mismatch between broker state and Postgres state, then the system shall block Alpaca live orders for the affected model provider and record the mismatch. |
| REQ-ALP-019 | P0 | The system shall default Alpaca short selling to disabled and shall permit only an authorized user to change the audited shorting configuration. |
| REQ-ALP-020 | P0 | Immediately before submitting a sell-to-open order, the system shall read current account state and require an active Alpaca account with shorting enabled, at least 2,000 USD equity, sufficient buying power for Alpaca's short-sale buying-power calculation, and no account-blocked, trading-blocked, or user-suspended trading flag. |
| REQ-ALP-021 | P0 | Immediately before submitting a sell-to-open order, the system shall read current asset state and require an active, tradable, shortable U.S. equity whose Alpaca `borrow_status` is `easy_to_borrow`; missing, unknown, stale, or hard-to-borrow status shall be refused. |
| REQ-ALP-022 | P0 | When submitting an Alpaca short entry, the system shall use a positive whole-share quantity and explicit `sell_to_open` position intent; notional, fractional, zero, or negative short-entry quantities shall be refused. |
| REQ-ALP-023 | P0 | When Alpaca reports a short position, the system shall preserve its signed direction through reconciliation, risk, P&L, age, exit triggers, audit records, and dashboard output, and shall close it with buy-to-close only. |
| REQ-ALP-024 | P0 | If a new Alpaca entry would add to, reduce, or cross an existing position in the same symbol, or if an unresolved order exists for the symbol, then the system shall refuse the entry and require reconciliation or the explicit exit path. |
| REQ-ALP-025 | P0 | When a reconciled Alpaca short position exists, the system shall allow a risk-reducing buy-to-close for its exact absolute quantity even if new shorting is disabled, account or borrow entry eligibility later fails, or a corporate action produced a fractional quantity; if an exact supported close cannot be submitted, the system shall block automation and surface an operator action instead of rounding down. |
| REQ-ALP-026 | P0 | When the system exits an Alpaca position, the system shall preserve the originating environment, model provider, account mode, and sanitized account reference so that the close is routed to the same configured account and its audit and notification records retain the correct provider. |

### Data Ingestion and S3 Storage

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-DAT-001 | P0 | When the daily full-ingestion schedule reaches 06:00 UTC, the system shall download a full market and trade data snapshot for enabled venues. |
| REQ-DAT-002 | P0 | When the incremental-ingestion interval elapses, the system shall download only new or changed market and trade data since the prior checkpoint. |
| REQ-DAT-003 | P0 | The system shall store full raw snapshots, incremental raw snapshots, and normalized outputs in S3. |
| REQ-DAT-004 | P0 | When the system stores a snapshot in S3, the system shall partition the object path by environment, venue, snapshot type, and UTC date. |
| REQ-DAT-005 | P0 | If market data is stale beyond a configurable threshold, then the system shall block live orders that depend on that data. |
| REQ-DAT-006 | P1 | The system shall retain raw S3 snapshots for 365 days. |
| REQ-DAT-007 | P1 | The system shall retain normalized S3 snapshots for 730 days. |
| REQ-DAT-008 | P1 | If an ingestion job fails, then the system shall record the error, preserve the last successful checkpoint, and retry according to configured retry policy. |

### Postgres Persistence

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-DB-001 | P0 | The system shall store live and dry-run positions in RDS Postgres. |
| REQ-DB-002 | P0 | The system shall use separate schemas in the same RDS database for Claude and OpenAI model data. |
| REQ-DB-003 | P0 | The system shall store shared system records in a shared schema. |
| REQ-DB-004 | P0 | When the system records a trade decision, the system shall persist the model provider, venue, environment, instrument identifier, instrument type, signal inputs, decision, order type, size, and timestamp. |
| REQ-DB-005 | P0 | When a position changes state, the system shall persist the prior state, new state, realized P&L, unrealized P&L, and reason for change. |
| REQ-DB-006 | P1 | The system shall retain Postgres audit, trade, and position history indefinitely unless a later archive policy is configured. |
| REQ-DB-007 | P0 | If Postgres is configured, then the system shall initialize SQLAlchemy with the packaged Postgres driver; if Postgres is unavailable, then the system shall block live order placement and surface the persistence failure in logs and dashboard status. |
| REQ-DB-008 | P0 | When an enabled venue account is reconciled, the system shall persist sanitized account, position, and confirmed-fill snapshots by environment, venue, model provider, and account reference without storing credential material. |
| REQ-DB-009 | P0 | When a scanner run persists a candidate batch, the system shall commit the run and its candidates in one database transaction rather than committing each candidate separately. |
| REQ-DB-010 | P0 | When a dashboard-relevant Postgres transaction commits, the database shall publish one coalescible invalidation event scoped to its environment and, for user-owned configuration or preferences, its authenticated username. |

### Wallet and Secrets Management

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-WAL-001 | P0 | The system shall support separate wallets or brokerage credentials per environment, venue, and model provider. |
| REQ-WAL-002 | P0 | When a user runs the wallet-generation CLI, the system shall generate wallet material for the requested environment, venue, and model provider. |
| REQ-WAL-003 | P0 | In deployed environments, the system shall store private keys and API credentials only in AWS Secrets Manager. |
| REQ-WAL-004 | P0 | In local development, the system shall read private keys and API credentials from gitignored `.env` files. |
| REQ-WAL-005 | P0 | The dashboard shall show wallet, account, and credential status with public identifiers without displaying private keys or API secrets. |
| REQ-WAL-006 | P0 | If a wallet secret, brokerage credential, or API credential is missing for a live order, then the system shall refuse to place the order and record the refusal reason. |
| REQ-WAL-007 | P1 | When credentials are rotated, the system shall use the updated secret on the next credential refresh without requiring a redeploy. |

### Recurring Funding and Direct Transfers

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-FND-001 | P0 | When an authenticated Polymarket US or Alpaca account is reconciled, the system shall retrieve deposit and withdrawal activity from the venue's documented account-activity API in addition to balances, positions, and fills. |
| REQ-FND-002 | P0 | When venue funding activity is normalized, the system shall retain the environment, venue, model providers, sanitized account reference, venue transaction identifier, direction, USD amount, venue status, occurrence time, and last update time without retaining credential or bank-account material. |
| REQ-FND-003 | P0 | When the same venue funding transaction is observed more than once or through model credentials that resolve to one account, the system shall upsert one cash-flow record and merge provider attribution without duplicating its amount. |
| REQ-FND-004 | P1 | The system shall retain normalized funding activity and expected funding occurrences indefinitely unless a later archive policy is configured. |
| REQ-FND-005 | P0 | [ASSUMED] When an authorized operator configures an observed recurring deposit, the system shall support weekly and monthly schedules per environment, venue, and model provider at 09:00 America/New_York, moving weekend or United States federal-holiday occurrences to the next business day. |
| REQ-FND-006 | P0 | [ASSUMED] When an authorized operator configures a direct low-balance refill, the system shall evaluate it after each confirmed portfolio refresh and calculate the requested amount as the configured target balance minus confirmed available-to-trade balance, capped by the schedule amount and transfer safety limits. |
| REQ-FND-007 | P0 | When a recurring funding occurrence becomes due, the system shall persist exactly one deterministic occurrence with its expected account, amount, due time, execution mode, status, and idempotency key before any external transfer call. |
| REQ-FND-008 | P0 | [ASSUMED] If no completed venue cash flow matches an observed recurring occurrence by account, direction, amount within 0.01 USD, and occurrence window within four business days after its due time, then the system shall mark the occurrence missing. |
| REQ-FND-009 | P0 | When a funding occurrence first becomes missing, rejected, returned, or failed, the system shall send one SES alert and persist the alert result; if a missing occurrence is later reconciled, then the system shall send one recovery notification. |
| REQ-FND-010 | P0 | When Performance is opened, the dashboard shall show funding history, expected occurrences, venue status, matched or missing state, direction, amount, account attribution, and timestamps without exposing account identifiers, relationship identifiers, or credentials. |
| REQ-FND-011 | P0 | When portfolio performance is calculated across a period, the system shall calculate cash-flow-adjusted trading P&L as ending account value minus starting account value minus deposits plus withdrawals, and shall not classify deposits or withdrawals as trading profit or loss. |
| REQ-FND-012 | P0 | [ASSUMED] When a percentage return is calculated across external cash flows, the system shall use the Modified Dietz method with cash flows weighted by their time within the selected period, and shall mark the return unavailable when its weighted capital denominator is zero or negative. |
| REQ-FND-013 | P0 | The system shall support direct incoming Alpaca ACH transfers only through the documented Alpaca Broker API using separately configured Broker API credentials, the target account identifier, and a previously approved ACH relationship identifier; the system shall not require or integrate Plaid. |
| REQ-FND-014 | P0 | While direct transfers are disabled, the per-transfer limit is zero, the monthly limit is zero, Broker API credentials are missing, the ACH relationship reference is missing, or persistence is unavailable, the system shall refuse a direct transfer before calling Alpaca and record the refusal reason. |
| REQ-FND-015 | P0 | Before submitting a direct transfer, the system shall enforce a positive amount, the configured per-transfer limit, the configured calendar-month account limit including pending and completed transfers, and at most one pending direct transfer per venue account. |
| REQ-FND-016 | P0 | When a direct transfer is retried with the same funding-occurrence idempotency key, the system shall return the persisted attempt or reconcile its venue state without submitting a second transfer request. |
| REQ-FND-017 | P0 | If Alpaca rejects, returns, or fails a direct transfer, then the system shall persist the terminal status, alert the operator, and require a new authorized occurrence rather than retrying automatically. |
| REQ-FND-018 | P0 | When the global kill switch or funding emergency stop is active, the system shall block new direct-transfer submissions while continuing read-only venue funding reconciliation and alert recovery. |
| REQ-FND-019 | P0 | When an authorized operator creates, changes, enables, disables, or deletes a funding schedule or direct-transfer setting, the system shall validate the complete schedule, persist a versioned owner-specific configuration change, and audit the username, old value, new value, environment, timestamp, and IP address. |
| REQ-FND-020 | P0 | While no documented and entitled Polymarket US funding-write API is configured, the system shall keep Polymarket US funding in observe-and-reconcile mode and shall not attempt direct deposit initiation. |

### LLM Scoring

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-LLM-001 | P0 | The system shall evaluate eligible Polymarket markets and Alpaca stock or ETF candidates with both Claude and OpenAI model providers. |
| REQ-LLM-002 | P0 | The system shall maintain separate configured budgets for Claude and OpenAI. |
| REQ-LLM-003 | P0 | When a model evaluates a market, the system shall record the model provider, prompt version, input summary, output thesis, confidence, estimated probability, and cost estimate. |
| REQ-LLM-004 | P0 | If a model budget is exhausted, then the system shall stop sending new scoring requests to that model and continue other eligible models. |
| REQ-LLM-005 | P0 | If LLM scoring fails for a market, then the system shall block live orders for that model and market in the current loop. |
| REQ-LLM-006 | P1 | The system shall allow dashboard users to change model budgets and scoring settings. |
| REQ-LLM-007 | P1 | When a scoring configuration changes, the system shall apply the change on the next trading loop. |

### Strategy and Signal Engine

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-STR-001 | P0 | The system shall run the trading loop every 15 minutes by default. |
| REQ-STR-002 | P0 | The system shall allow the trading loop interval to be changed through dashboard configuration. |
| REQ-STR-003 | P0 | When the trading loop runs, the system shall scan enabled venues for markets that pass deterministic filters before requesting LLM scoring. |
| REQ-STR-004 | P0 | The system shall implement an arbitrage strategy for related-market price dislocations. |
| REQ-STR-005 | P0 | The system shall implement a convergence strategy for markets where price movement is expected to converge toward the model estimate. |
| REQ-STR-006 | P0 | The system shall implement a whale-copy strategy using configured target wallets and delay settings. |
| REQ-STR-007 | P0 | When strategies produce signals for the same market and model, the system shall record each strategy signal before creating an execution decision. |
| REQ-STR-008 | P0 | If strategy signals disagree for the same model and market, then the system shall apply the configured consensus rule before any order is created. |
| REQ-STR-009 | P1 | The dashboard shall allow authorized users to enable, disable, and configure each strategy. |

### Risk and Execution Engine

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-EXE-001 | P0 | The system shall start with `LIVE_ENABLED=false` in all environments unless explicitly configured otherwise. |
| REQ-EXE-002 | P0 | While dry-run mode is enabled, the system shall record simulated orders without submitting orders to a venue. |
| REQ-EXE-003 | P0 | When an authorized dashboard user toggles dry-run to live mode, the system shall apply the change on the next trading loop. |
| REQ-EXE-004 | P0 | The system shall enforce a default max position size of 25 USD per position. |
| REQ-EXE-005 | P0 | The system shall enforce a default max daily loss of 50 USD per model provider. |
| REQ-EXE-006 | P0 | The system shall enforce a default max open position count of 5 per model provider. |
| REQ-EXE-007 | P0 | The system shall allow max position size, max daily loss, and max open positions to be changed through dashboard configuration. |
| REQ-EXE-008 | P0 | When sizing an order, the system shall calculate a Kelly-based size and cap it by the configured risk limits. |
| REQ-EXE-009 | P0 | If the Kelly calculation produces a non-positive size, then the system shall refuse the trade. |
| REQ-EXE-010 | P0 | The system shall support limit orders and market orders. |
| REQ-EXE-011 | P0 | When creating a market order, the system shall block the order if estimated slippage exceeds the configured threshold. |
| REQ-EXE-012 | P0 | The default estimated slippage threshold for market orders shall be 2 percent. |
| REQ-EXE-013 | P0 | If `LIVE_ENABLED=false`, venue disabled, wallet secret missing, API credentials missing, max daily loss reached, max open positions reached, max position exceeded, unsupported jurisdiction or venue config detected, stale market data detected, or LLM scoring failed, then the system shall refuse new or exposure-increasing live order placement; exact reconciled risk-reducing exits remain subject to credential, persistence, account-routing, market-hours, and venue availability checks but shall not be blocked by entry size, allocation, position-count, or daily-loss limits. |
| REQ-EXE-014 | P0 | When the kill switch is activated, the system shall disable live trading for all models and venues. |
| REQ-EXE-015 | P0 | When the kill switch is activated, the system shall attempt to cancel open orders for all enabled live venues. |
| REQ-EXE-016 | P0 | When the system refuses, submits, fills, cancels, or fails an order, the system shall persist the event and expose it in dashboard status. |
| REQ-EXE-017 | P0 | When global dry-run mode is disabled, the system shall permit live orders only for explicitly enabled venues, model-provider accounts, and account modes that pass all venue-specific and shared risk checks. |

### Exit Monitoring

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-EXT-001 | P0 | The system shall monitor open positions for configured exit triggers. |
| REQ-EXT-002 | P0 | When a position reaches the configured profit target, the system shall create an exit decision. |
| REQ-EXT-003 | P0 | When a configured volume spike threshold is reached, the system shall create an exit decision. |
| REQ-EXT-004 | P0 | When a thesis becomes stale according to configured age and price movement thresholds, the system shall create an exit decision. |
| REQ-EXT-005 | P0 | While dry-run mode is enabled, the exit monitor shall record simulated exits without submitting orders. |
| REQ-EXT-006 | P0 | While live mode is enabled, the exit monitor shall route approved exits through the risk and execution engine. |

### Dashboard and GitHub OAuth

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-UI-001 | P0 | The system shall provide a custom Next.js React dashboard backed by FastAPI services. |
| REQ-UI-002 | P0 | The dashboard shall require GitHub OAuth login. |
| REQ-UI-003 | P0 | If the authenticated GitHub username is not on the allowlist, then the dashboard shall deny access. |
| REQ-UI-004 | P0 | The dashboard shall allow authorized users to view venue, model, wallet, ingestion, trading loop, position, order, and notification status, shall report persisted pipeline aggregate counts when detail rows are deferred, and shall load each user's display preferences from the database by authenticated username and environment. |
| REQ-UI-005 | P0 | The dashboard shall allow authorized users to change venue flags, dry-run/live mode, loop interval, strategy settings, model budgets, risk limits, slippage threshold, and notification settings. |
| REQ-UI-006 | P0 | When an authorized user changes configuration in the dashboard, the system shall audit the user, old value, new value, timestamp, environment, and IP address. |
| REQ-UI-007 | P0 | When dashboard configuration is saved, the system shall apply the database-backed owner-specific change on the next trading loop without restart. |
| REQ-UI-008 | P0 | The dashboard shall expose a manual kill switch for all models and venues. |
| REQ-UI-009 | P1 | The dashboard shall show wallet public identifiers and health status without showing private keys. |
| REQ-UI-010 | P1 | The dashboard shall present separate views for Claude and OpenAI positions, decisions, budgets, and P&L. |
| REQ-UI-011 | P0 | The dashboard shall compare Claude and OpenAI performance across Polymarket and Alpaca using P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics. |
| REQ-UI-012 | P0 | When recent scanner output identifies a settings-based blocker, the dashboard shall show an actionable config recommendation that preserves the setting's required value type, saves user-owned database settings through the audited config endpoint, shows venue-specific input counts when a total spans venues, and explains that model, credential, market-hours, and risk gates still apply. |
| REQ-UI-013 | P0 | When an authorized user opens Performance, the system shall show venue-confirmed account value, cash, available-to-trade balance, realized P&L, unrealized P&L, open positions, and confirmed fills for Polymarket US and Alpaca, separated by model-provider account and marked unavailable when venue data is missing or stale; available-to-trade balance shall use venue-confirmed buying power when present and cash otherwise; Overview shall show only a compact current-status result with a link to Performance. |
| REQ-UI-014 | P0 | If the realtime dashboard connection is unavailable, then polling shall keep at most one snapshot request in flight, retry with bounded backoff, and read only the latest persisted dashboard rows required for the response. |
| REQ-UI-015 | P0 | While an authorized dashboard WebSocket is connected, the system shall send one complete user-scoped snapshot on connection, send lightweight heartbeats while state is unchanged, and send updated operations, market, schedule, and portfolio data only after a relevant committed database change; if the event stream fails, the browser shall reconnect with bounded backoff while retaining polling as a recovery path. |
| REQ-UI-016 | P0 | The authenticated dashboard shall provide five always-visible primary destinations named Overview, Activity, Performance, Settings, and Help, shall remove the More menu, and shall preserve legacy operational routes through contextual links and direct URLs, including `/dashboard/operations` as the detailed operations and emergency-stop route linked from Activity and Settings. |
| REQ-UI-017 | P0 | When dashboard data loads, Overview shall derive exactly one current state from persisted or realtime data, using live-trade state when the latest tick placed a non-simulated order, attention state when a pipeline stage is blocked or required setup is incomplete, and all-clear state otherwise; no prototype or manual state selector shall be rendered. |
| REQ-UI-018 | P0 | When Overview is in attention state, the system shall show a short prioritized list of actionable blockers and no more than three relevant setting recommendations; when Overview is live-trade or all-clear, it shall not show blocker recommendations. |
| REQ-UI-019 | P0 | Overview shall show only current mode, active markets, last check, next check, the most recent result, and contextual links below its primary state, and shall not duplicate detailed operation records, performance tables, configuration forms, or help content. |
| REQ-UI-020 | P0 | When an authorized user opens Activity, the system shall show the latest scan funnel and a recent check log from persisted or realtime operations data, shall identify when the data was updated, and shall render an unavailable or degraded state rather than inventing counts. |
| REQ-UI-021 | P0 | When an authorized user opens Performance, the system shall show venue-confirmed Equity, Realized P&L, Unrealized P&L, Open positions, Win rate, and Trades metrics plus a by-market table with Market, Trades, Win rate, and P&L columns, shall exclude simulated and unfilled orders, and shall render missing or stale money values as unavailable rather than zero. |
| REQ-UI-022 | P0 | Settings shall present common confidence, spread, real-money, notification, recipient, and market controls in plain language, shall preserve validated audited persistence for all existing advanced settings, shall link to the existing emergency-stop control, and shall keep destructive or live-money controls visually distinct. |
| REQ-UI-023 | P1 | Help shall explain the trading process as Collect prices, Find candidates, Score, Simulate or submit, and Monitor exits in that order, answer common operating questions, and link back to Overview without depending on backend availability. |
| REQ-UI-024 | P0 | The five dashboard destinations shall remain usable without horizontal page overflow at 390 CSS pixels and at desktop widths, shall support keyboard navigation and visible focus, shall not communicate status by color alone, and shall respect reduced-motion preferences. |
| REQ-UI-025 | P0 | If one or more upstream dashboard sections fail while a last known snapshot exists, then each redesigned page shall keep valid data visible, identify stale or unavailable sections once, and avoid repeating the same failure message in multiple cards. |
| REQ-UI-026 | P0 | Before an Overview recommendation changes a setting, the dashboard shall show the exact current and proposed values and require confirmation; after a successful change, it shall provide an undo action through the same validated audited configuration endpoint until the next config mutation, navigation, or page reload, and shall reject stale undo attempts on version conflict. |

### Cross-Market Comparison Analytics

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-CMP-001 | P0 | The system shall calculate performance metrics by model provider, venue, environment, and instrument type. |
| REQ-CMP-002 | P0 | The system shall compare Claude and OpenAI performance across Polymarket bets and Alpaca stocks or ETFs. |
| REQ-CMP-003 | P0 | The system shall include realized P&L, unrealized P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics in comparison views using documented formulas. |
| REQ-CMP-004 | P1 | If a metric cannot be calculated because data is missing or insufficient, then the system shall show the metric as unavailable rather than zero. |
| REQ-CMP-005 | P0 | When portfolio performance is aggregated, the system shall exclude simulated and unfilled orders, deduplicate shared venue accounts, and calculate totals only from venue-confirmed positions and fills. |

### Notifications

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-NOT-001 | P0 | The system shall send a daily digest email through Amazon SES to users in the GitHub OAuth allowlist. |
| REQ-NOT-002 | P0 | The daily digest shall include P&L summary, open positions, new trades, exits, refused orders, model budget usage, ingestion status, and risk-limit status. |
| REQ-NOT-003 | P0 | When a position P&L changes by at least 25 USD or 10 percent by default, the system shall send a large-movement alert through SES. |
| REQ-NOT-004 | P0 | When daily realized or unrealized P&L crosses a configured movement or drawdown threshold, the system shall send an alert through SES. |
| REQ-NOT-005 | P0 | The system shall enforce a default 30-minute alert cooldown per market and model provider. |
| REQ-NOT-006 | P1 | The dashboard shall allow authorized users to change notification recipients, thresholds, schedules, and cooldowns. |
| REQ-NOT-007 | P1 | If SES delivery fails, then the system shall record the failure and retry according to configured retry policy. |

### Deployment, CI/CD, and Codex Web Setup

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-DEP-001 | P0 | The system shall run locally with Docker and gitignored `.env` files. |
| REQ-DEP-002 | P0 | The system shall deploy to AWS `us-east-1` using ECS Fargate, RDS Postgres, S3, Secrets Manager, CloudWatch, and SES. |
| REQ-DEP-003 | P0 | When code is merged to `develop`, GitHub Actions shall deploy the application to the development environment. |
| REQ-DEP-004 | P0 | When code is merged to `main`, GitHub Actions shall deploy the application to the production environment automatically. |
| REQ-DEP-005 | P0 | The CI pipeline shall run tests before building or deploying containers. |
| REQ-DEP-006 | P0 | The deployment pipeline shall build container images and publish them to Amazon ECR before ECS deployment. |
| REQ-DEP-007 | P0 | The repository shall include `.env.example` files that document required local configuration without containing secrets. |
| REQ-DEP-008 | P0 | The repository shall include Codex web setup guidance through `AGENTS.md`, setup scripts, and safe default dry-run configuration. |
| REQ-DEP-009 | P0 | Codex web environments shall not require production trading secrets to install dependencies, run tests, or inspect the codebase. |
| REQ-DEP-010 | P1 | The deployment shall maintain separate development and production resources, secrets, wallets, and configuration. |
| REQ-DEP-011 | P0 | The deployment shall provision RDS Postgres with gp3 storage so application availability does not depend on gp2 burst-credit balance. |

### Observability and Audit Logging

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-OBS-001 | P0 | The system shall emit structured logs for ingestion, scoring, strategy decisions, risk checks, orders, exits, notifications, configuration changes, and deployment health. |
| REQ-OBS-002 | P0 | In AWS environments, the system shall send application logs to CloudWatch. |
| REQ-OBS-003 | P0 | When a live order is refused, submitted, filled, canceled, or failed, the system shall produce an audit event. |
| REQ-OBS-004 | P0 | When a dashboard user changes configuration, toggles live mode, or activates the kill switch, the system shall produce an audit event. |
| REQ-OBS-005 | P1 | The dashboard shall expose recent audit events and system health indicators. |
| REQ-OBS-006 | P1 | If a background worker fails, then the system shall record the failure and surface degraded status in the dashboard. |

### Kalshi Venue Integration

The following requirements use the current REST polling architecture and the user-approved production rollout. Items tagged `[ASSUMED]` record implementation choices that were not separately specified by the user and can be revised in a later release.

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-KAL-001 | P0 | When Kalshi is explicitly enabled, the system shall expose `kalshi` for market data, scoring, simulation, execution, runtime status, portfolio, and performance; when it is disabled, the system shall refuse new scans, scores, and entries while continuing read-only reconciliation, exits, and cancellation of known exposure. |
| REQ-KAL-002 | P0 | When a Kalshi market-data pull runs, the system shall paginate active standard binary markets, send `mve_filter=exclude`, retain each market's `price_ranges`, and use authenticated order-book batches of at most 100 tickers as the authoritative bid, ask, depth, and live-eligibility source for normalized YES and NO decimal candidates; without the dedicated read credential, the system may read public market summaries but shall emit no live-eligible candidate or unsigned order-book request. |
| REQ-KAL-003 | P0 | If required Kalshi market or order-book data is empty, older than the configured 60-second live threshold, rate limited, malformed, or unavailable, then the system shall record an allowlisted error code, make at most three total attempts with configured exponential backoff only for GET, and refuse dependent exposure-increasing orders; valid empty account collections shall remain successful reads. |
| REQ-KAL-004 | P0 | [ASSUMED] While running locally or in development, the system shall use only the recommended Kalshi demo host and demo credentials; while running in production, it shall use only the recommended production host and production credentials; credentials shall be isolated by environment and model provider and shall never be returned, logged, persisted outside the approved secret store, or committed. Signed requests shall use RSA-PSS SHA-256 over `<millisecond timestamp><UPPERCASE METHOD><full path without query>` and shall fail closed when clock skew causes authentication rejection. |
| REQ-KAL-005 | P0 | When an approved live Kalshi entry or exit is submitted, the system shall use the V2 event-order API, map normalized outcome and direction through the defined YES-book truth table, emulate a market order with a slippage-bounded IOC limit or use GTC for an explicit limit, round to a side-safe valid `price_ranges` step, resolve current event overrides and series fee type and multiplier, reserve worst-case principal plus fee-model and rounding costs inside approved risk, and send a stable client order ID, 0.01-granular count, supported self-trade prevention, pause cancellation, `reduce_only` for exits, and primary subaccount 0. |
| REQ-KAL-006 | P0 | Before dispatching a Kalshi mutation, the system shall persist `SUBMITTING`; if the post-dispatch result is ambiguous, it shall persist `UNKNOWN_SUBMIT`, preserve the client order ID, block replacement orders and ID reuse, and reconcile orders, fills, and positions until terminal or operator-reviewed without automatically retrying the POST. |
| REQ-KAL-007 | P0 | Before an exposure-increasing live Kalshi order, the system shall require enabled venue configuration, valid provider RSA credentials, supported binary semantics, an active market, active exchange trading, market data no older than 60 seconds, account and open-order state no older than 60 seconds, no unknown or conflicting order, distinct provider account identity, and shared risk approval; dry-run mode shall persist simulation without signing or venue transport. |
| REQ-KAL-008 | P0 | When Kalshi account reconciliation runs, the system shall read one balance snapshot and cursor-paginate positions, fills, settlements, and orders for each provider's primary account, normalize each field according to the source-unit contract, and retain a failed refresh's prior confirmed snapshot only as degraded state that cannot authorize new exposure. |
| REQ-KAL-009 | P0 | When an authorized dashboard user saves Kalshi configuration, the system shall persist enablement, default venue, scan limits, and risk limits for the next loop and shall show sanitized credential readiness, activity, account, position, fill, net-of-fee P&L, and freshness; an unauthorized user shall be unable to read or mutate protected Kalshi data. |
| REQ-KAL-010 | P0 | [ASSUMED] When the Kalshi release is promoted, development and production infrastructure shall accept environment-specific, provider-specific key IDs and RSA private keys from AWS Secrets Manager and keep live submission unavailable when any required secret is absent. The release shall complete CI, deployment, health, public-read, missing-secret, rollback, and zero-mutation verification without a live-money smoke order; when all six credential secrets are configured, it shall also verify the authenticated batch order book, per-provider balance normalization, and unchanged order and fill counts. |
| REQ-KAL-011 | P0 | When a known Kalshi order must be canceled, including after venue disablement or kill-switch activation, the system shall reconcile the order, submit one V2 DELETE for the known order ID if it remains cancelable, persist the result, and permit a later bounded cancel attempt only after another read confirms that the same order remains open. |
| REQ-KAL-012 | P0 | [ASSUMED] While live Kalshi trading is enabled for both model providers, OpenAI and Claude shall use distinct credentials whose authenticated `/api_keys` membership sets produce distinct sanitized account fingerprints, and each shall have read scope for reconciliation plus write scope before live enablement; a credential or account collision shall block new exposure while allowing reconciliation and risk-reducing actions under an account-level reservation lock. |
| REQ-KAL-013 | P0 | When Kalshi portfolio data is normalized, integer `balance` and `portfolio_value` cents shall be divided by 100 into USD, `*_dollars` prices and costs shall remain dollar Decimal strings, `*_fp` quantities shall remain contract Decimal strings, fees, settlement revenue, and P&L shall retain six-decimal intermediate precision with explicit final currency rounding, per-position unrealized P&L shall remain unavailable until a confirmed venue mark exists, and YES or NO `outcomeSide` shall remain distinct from stock long or short semantics. |
| REQ-KAL-014 | P0 | When reconciliation needs records older than Kalshi's live-data cutoffs, the system shall read `/historical/cutoff`, paginate historical fills and orders, use live positions and settlements for current and settlement evidence, persist checkpoints, deduplicate live and historical records by stable venue identifiers, and stop as degraded without advancing a checkpoint on a repeated cursor or after 100 pages. |
