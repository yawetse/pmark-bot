# codex-poly-bot Requirements

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.0  
**Date:** 2026-04-24  
**Status:** DRAFT  

## Product Intent

`codex-poly-bot` is a standalone live-capable trading bot with a Python/FastAPI backend and a Next.js React dashboard. The bot supports Polymarket US, Polymarket International, and traditional stock-market trading through Alpaca for stocks and ETFs. The bot defaults to Polymarket US, disables every venue unless explicitly enabled by configuration, and runs OpenAI and Claude evaluators at the same time with separate budgets, Alpaca accounts, wallets, and Postgres schemas.

The first version includes market scanning, daily full and incremental S3 data downloads, wallet target analysis, LLM thesis scoring, arbitrage, convergence, whale-copy strategies, Alpaca stock/ETF signal evaluation, Kelly sizing, configurable risk controls, limit and market order execution, exit monitoring, dashboard configuration, GitHub OAuth login, SES email notifications, model and venue comparison analytics, and AWS deployment. Dry-run mode exists from day one, live trading defaults to off, and configuration changes made in the dashboard apply on the next trading loop. The system runs locally with gitignored `.env` files and deploys through GitHub Actions to AWS `us-east-1` development and production environments.

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
| REQ-ALP-002 | P0 | The system shall exclude Alpaca options, crypto, short selling, and margin trading from v1. |
| REQ-ALP-003 | P0 | When the system uses Alpaca, the system shall use Alpaca's official Python SDK or documented HTTP APIs for account, market data, position, and order operations. |
| REQ-ALP-004 | P0 | The system shall require separate Alpaca account identifiers per environment and model provider. |
| REQ-ALP-005 | P0 | While global dry-run mode is enabled, the system shall record simulated Alpaca stock and ETF orders without submitting orders to Alpaca paper or live endpoints. |
| REQ-ALP-006 | P0 | While global dry-run mode is disabled and Alpaca is enabled, the system shall submit approved Alpaca orders to the configured Alpaca account mode subject to risk checks. |
| REQ-ALP-007 | P0 | The system shall support Alpaca paper and live account modes as environment and dashboard configuration values. |
| REQ-ALP-008 | P0 | If an Alpaca order would create a short position or require margin, then the system shall refuse the order. |
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
| REQ-STR-001 | P0 | The system shall run the trading loop every 60 seconds by default. |
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
| REQ-EXE-013 | P0 | If `LIVE_ENABLED=false`, venue disabled, wallet secret missing, API credentials missing, max daily loss reached, max open positions reached, max position exceeded, unsupported jurisdiction or venue config detected, stale market data detected, or LLM scoring failed, then the system shall refuse live order placement. |
| REQ-EXE-014 | P0 | When the kill switch is activated, the system shall disable live trading for all models and venues. |
| REQ-EXE-015 | P0 | When the kill switch is activated, the system shall attempt to cancel open orders for all enabled live venues. |
| REQ-EXE-016 | P0 | When the system refuses, submits, fills, cancels, or fails an order, the system shall persist the event and expose it in dashboard status. |
| REQ-EXE-017 | P0 | When global dry-run mode is disabled, the system shall permit live orders only for explicitly enabled venues and account modes that pass all venue-specific and shared risk checks. |

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
| REQ-UI-004 | P0 | The dashboard shall allow authorized users to view venue, model, wallet, ingestion, trading loop, position, order, and notification status, and shall load each user's display preferences from the database by authenticated username and environment. |
| REQ-UI-005 | P0 | The dashboard shall allow authorized users to change venue flags, dry-run/live mode, loop interval, strategy settings, model budgets, risk limits, slippage threshold, and notification settings. |
| REQ-UI-006 | P0 | When an authorized user changes configuration in the dashboard, the system shall audit the user, old value, new value, timestamp, environment, and IP address. |
| REQ-UI-007 | P0 | When dashboard configuration is saved, the system shall apply the database-backed owner-specific change on the next trading loop without restart. |
| REQ-UI-008 | P0 | The dashboard shall expose a manual kill switch for all models and venues. |
| REQ-UI-009 | P1 | The dashboard shall show wallet public identifiers and health status without showing private keys. |
| REQ-UI-010 | P1 | The dashboard shall present separate views for Claude and OpenAI positions, decisions, budgets, and P&L. |
| REQ-UI-011 | P0 | The dashboard shall compare Claude and OpenAI performance across Polymarket and Alpaca using P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics. |

### Cross-Market Comparison Analytics

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-CMP-001 | P0 | The system shall calculate performance metrics by model provider, venue, environment, and instrument type. |
| REQ-CMP-002 | P0 | The system shall compare Claude and OpenAI performance across Polymarket bets and Alpaca stocks or ETFs. |
| REQ-CMP-003 | P0 | The system shall include realized P&L, unrealized P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics in comparison views using documented formulas. |
| REQ-CMP-004 | P1 | If a metric cannot be calculated because data is missing or insufficient, then the system shall show the metric as unavailable rather than zero. |

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

### Observability and Audit Logging

| ID | Priority | EARS Requirement |
|----|----------|------------------|
| REQ-OBS-001 | P0 | The system shall emit structured logs for ingestion, scoring, strategy decisions, risk checks, orders, exits, notifications, configuration changes, and deployment health. |
| REQ-OBS-002 | P0 | In AWS environments, the system shall send application logs to CloudWatch. |
| REQ-OBS-003 | P0 | When a live order is refused, submitted, filled, canceled, or failed, the system shall produce an audit event. |
| REQ-OBS-004 | P0 | When a dashboard user changes configuration, toggles live mode, or activates the kill switch, the system shall produce an audit event. |
| REQ-OBS-005 | P1 | The dashboard shall expose recent audit events and system health indicators. |
| REQ-OBS-006 | P1 | If a background worker fails, then the system shall record the failure and surface degraded status in the dashboard. |
