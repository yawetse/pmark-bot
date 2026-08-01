# codex-poly-bot Test Specification

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.2
**Date:** 2026-07-31
**Status:** DRAFT  

## Test Strategy

- P0 requirements receive happy-path and negative or edge-case coverage.
- P1 requirements receive one focused test each.
- Tests shall be isolated. Shared fixtures and factories are allowed, but each test owns its state.
- Numeric controls shall be tested at the boundary and past the boundary.
- Unit tests shall cover component behavior. Integration tests shall cover trading loop, config changes, execution, and dashboard API flows.
- Performance and timing checks shall cover scheduler cadence, ingestion job behavior, and API response sanity.

## Summary

| Priority | Requirements | Planned Tests |
|----------|--------------|---------------|
| P0 | 143 | 373 |
| P1 | 20 | 34 |
| Total | 163 | 407 |

## Test Cases

### Venue Integration

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-VEN-001-01 | Happy | REQ-VEN-001 | Given supported venue configs for Polymarket US and International, When venue adapters are registered, Then both venues are available as configurable trading venues. |
| TST-REQ-VEN-001-02 | Edge | REQ-VEN-001 | Given an unknown Polymarket venue key, When venue adapters are resolved, Then the system rejects the venue and records a configuration error. |
| TST-REQ-VEN-002-01 | Happy | REQ-VEN-002 | Given no explicit venue setting, When the app loads runtime config, Then `polymarket_us` is selected as the default venue. |
| TST-REQ-VEN-002-02 | Edge | REQ-VEN-002 | Given an explicit supported venue setting, When the app loads runtime config, Then the explicit setting is used instead of the default. |
| TST-REQ-VEN-003-01 | Happy | REQ-VEN-003 | Given a venue with `enabled=false`, When scan, score, or trade is requested, Then the system refuses the operation before external calls. |
| TST-REQ-VEN-003-02 | Edge | REQ-VEN-003 | Given a venue is toggled from enabled to disabled, When the next loop starts, Then no stale enabled state allows scan, score, or trade. |
| TST-REQ-VEN-004-01 | Happy | REQ-VEN-004 | Given live mode and an approved Polymarket order, When execution submits the order, Then the official SDK or documented API client is used. |
| TST-REQ-VEN-004-02 | Edge | REQ-VEN-004 | Given a non-official Polymarket client implementation is configured, When live order submission is attempted, Then the system blocks the submission. |
| TST-REQ-VEN-004-03 | Focus | REQ-VEN-004 | Given dry-run mode is enabled and Polymarket is configured, When market reads execute through the adapter boundary, Then approved read APIs are used and no live order submit is attempted. |
| TST-REQ-VEN-005-01 | Happy | REQ-VEN-005 | Given an unsupported venue configuration for the environment, When live order checks run, Then live orders are blocked and the refusal reason is persisted. |
| TST-REQ-VEN-005-02 | Edge | REQ-VEN-005 | Given multiple unsupported venue fields, When validation runs, Then the refusal event includes each relevant unsupported setting. |
| TST-REQ-VEN-005-03 | Focus | REQ-VEN-005 | Given unsupported Polymarket venue configuration for the current environment, When live eligibility checks run, Then live orders are blocked and the refusal reason is persisted. |
| TST-REQ-VEN-006-01 | Focus | REQ-VEN-006 | Given an authorized dashboard update to venue config, When the next trading loop starts, Then the updated venue config is applied without restart. |

### Alpaca Stock and ETF Integration

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-ALP-001-01 | Happy | REQ-ALP-001 | Given Alpaca is configured and enabled, When venue adapters are registered, Then Alpaca is available for stocks and ETFs. |
| TST-REQ-ALP-001-02 | Edge | REQ-ALP-001 | Given Alpaca is not enabled, When the trading loop evaluates stock or ETF candidates, Then Alpaca scan and execution are skipped. |
| TST-REQ-ALP-002-01 | Happy | REQ-ALP-002 | Given stock and ETF candidates, When Alpaca filtering runs, Then only stocks and ETFs remain eligible. |
| TST-REQ-ALP-002-02 | Edge | REQ-ALP-002 | Given options, crypto, hard-to-borrow locate, or margin-funded long candidates, When Alpaca filtering runs, Then each unsupported product is rejected with a reason. |
| TST-REQ-ALP-003-01 | Happy | REQ-ALP-003 | Given Alpaca account, market data, position, and order operations, When adapters execute them, Then the official SDK or documented HTTP APIs are used. |
| TST-REQ-ALP-003-02 | Edge | REQ-ALP-003 | Given an adapter without an approved Alpaca client binding, When live operations are requested, Then the operation is blocked. |
| TST-REQ-ALP-003-03 | Focus | REQ-ALP-003 | Given dry-run mode is enabled and Alpaca is configured, When account and market data reads execute through the adapter boundary, Then approved read APIs are used without submitting to Alpaca paper or live order endpoints. |
| TST-REQ-ALP-004-01 | Happy | REQ-ALP-004 | Given dev and prod settings for Claude and OpenAI, When Alpaca credentials are loaded, Then each environment and model has a distinct account identifier. |
| TST-REQ-ALP-004-02 | Edge | REQ-ALP-004 | Given a missing Alpaca account identifier for one model provider, When live checks run, Then Alpaca live trading is blocked for that provider. |
| TST-REQ-ALP-005-01 | Happy | REQ-ALP-005 | Given global dry-run mode is enabled, When an Alpaca stock or ETF order is approved, Then a simulated order is recorded without broker submission. |
| TST-REQ-ALP-005-02 | Edge | REQ-ALP-005 | Given dry-run mode and a mocked broker client, When execution runs, Then no Alpaca paper or live endpoint is called. |
| TST-REQ-ALP-006-01 | Happy | REQ-ALP-006 | Given dry-run mode is disabled, Alpaca is enabled, and risk checks pass, When an order is approved, Then it is submitted to the configured Alpaca account mode. |
| TST-REQ-ALP-006-02 | Edge | REQ-ALP-006 | Given dry-run mode is disabled but a risk check fails, When Alpaca execution is requested, Then no order is submitted. |
| TST-REQ-ALP-007-01 | Happy | REQ-ALP-007 | Given environment and dashboard config values, When Alpaca account mode is resolved, Then paper and live modes are supported values. |
| TST-REQ-ALP-007-02 | Edge | REQ-ALP-007 | Given an invalid Alpaca account mode, When config validation runs, Then the mode is rejected and live trading is blocked. |
| TST-REQ-ALP-008-01 | Happy | REQ-ALP-008 | Given a buy order that does not require margin, When Alpaca risk checks run, Then the order remains eligible. |
| TST-REQ-ALP-008-02 | Edge | REQ-ALP-008 | Given shorting is disabled or a long purchase requires margin, When Alpaca risk checks run, Then the order is refused. |
| TST-REQ-ALP-009-01 | Happy | REQ-ALP-009 | Given default Alpaca risk config, When a stock or ETF order is sized at 100 USD per symbol and provider, Then the order passes the max-position boundary check. |
| TST-REQ-ALP-009-02 | Edge | REQ-ALP-009 | Given default Alpaca risk config, When a stock or ETF order exceeds 100 USD for a symbol and provider, Then the order is refused. |
| TST-REQ-ALP-010-01 | Happy | REQ-ALP-010 | Given default Alpaca risk config, When daily loss equals 100 USD for a model provider and a new order is evaluated, Then the order is refused because max daily loss is reached. |
| TST-REQ-ALP-010-02 | Edge | REQ-ALP-010 | Given default Alpaca risk config, When daily loss exceeds 100 USD for a model provider, Then additional Alpaca orders are refused. |
| TST-REQ-ALP-011-01 | Happy | REQ-ALP-011 | Given default Alpaca risk config and 4 open stock or ETF positions, When an approved order would create the fifth open position, Then the order passes the max-open boundary check. |
| TST-REQ-ALP-011-02 | Edge | REQ-ALP-011 | Given default Alpaca risk config, When a sixth open stock or ETF position would be created, Then the order is refused. |
| TST-REQ-ALP-012-01 | Happy | REQ-ALP-012 | Given default Alpaca risk config, When symbol allocation would equal 10 percent for a model provider, Then the order passes the allocation boundary check. |
| TST-REQ-ALP-012-02 | Edge | REQ-ALP-012 | Given default Alpaca risk config, When symbol allocation would exceed 10 percent, Then the order is refused. |
| TST-REQ-ALP-013-01 | Happy | REQ-ALP-013 | Given default Alpaca slippage config, When estimated market order slippage is exactly 0.5 percent, Then the market order passes the slippage boundary check. |
| TST-REQ-ALP-013-02 | Edge | REQ-ALP-013 | Given default Alpaca slippage config, When estimated market order slippage exceeds 0.5 percent, Then the market order is blocked. |
| TST-REQ-ALP-014-01 | Happy | REQ-ALP-014 | Given an authorized dashboard user, When Alpaca mode, enabled flag, risk limits, universe, or slippage is saved, Then the config is persisted. |
| TST-REQ-ALP-014-02 | Edge | REQ-ALP-014 | Given an unauthorized user or invalid Alpaca config value, When the update is submitted, Then the dashboard rejects the change. |
| TST-REQ-ALP-015-01 | Focus | REQ-ALP-015 | Given Alpaca market data is unavailable, rate-limited, stale, or outside configured trading hours, When live order checks run, Then the order is blocked and the reason is recorded. |
| TST-REQ-ALP-015-02 | Focus | REQ-ALP-015 | Given Alpaca data is unavailable, stale, rate-limited, or outside trading hours, When live order checks run, Then affected live orders are blocked and the refusal reason is recorded. |
| TST-REQ-ALP-016-01 | Happy | REQ-ALP-016 | Given distinct Alpaca account identifiers for each model in the same environment and mode, When duplicate checks run, Then Alpaca live trading remains eligible. |
| TST-REQ-ALP-016-02 | Edge | REQ-ALP-016 | Given two model providers resolve to the same Alpaca account identifier in the same environment and mode, When checks run, Then live trading is blocked for the duplicate account. |
| TST-REQ-ALP-017-01 | Happy | REQ-ALP-017 | Given Alpaca and Postgres agree on positions, open orders, and buying power, When reconciliation runs, Then Alpaca live orders may proceed to remaining checks. |
| TST-REQ-ALP-017-02 | Edge | REQ-ALP-017 | Given reconciliation has not completed, When Alpaca live execution is requested, Then the order is blocked. |
| TST-REQ-ALP-017-03 | Focus | REQ-ALP-017 | Given Alpaca account mode is configured with account and portfolio state, When live eligibility checks run, Then account ID, status, positions, open orders, and buying power are validated first. |
| TST-REQ-ALP-018-01 | Happy | REQ-ALP-018 | Given reconciliation detects no unresolved mismatch, When Alpaca live checks run, Then the mismatch gate passes. |
| TST-REQ-ALP-018-02 | Edge | REQ-ALP-018 | Given an unresolved broker and Postgres mismatch, When Alpaca live checks run, Then live orders are blocked for the affected provider and mismatch details are recorded. |
| TST-REQ-ALP-019-01 | Happy | REQ-ALP-019 | Given default config, When Alpaca settings load, Then `allow_shorting` is false and the active stock profile does not enable it. |
| TST-REQ-ALP-019-02 | UI | REQ-ALP-019 | Given an authorized user, When the shorting setting is changed, Then the boolean value is validated, persisted, audited, and shown with its risk impact. |
| TST-REQ-ALP-020-01 | Happy | REQ-ALP-020 | Given an active unblocked short-enabled account with at least 2,000 USD equity and sufficient buying power including the 3 percent ask buffer, When sell-to-open is submitted, Then the account gate passes. |
| TST-REQ-ALP-020-02 | Edge | REQ-ALP-020 | Given any account eligibility field is missing, blocked, user-suspended, false, below minimum, or has insufficient buying power, When sell-to-open is requested, Then no order POST occurs and a safe refusal is returned. |
| TST-REQ-ALP-021-01 | Happy | REQ-ALP-021 | Given an active tradable shortable U.S. equity with `borrow_status=easy_to_borrow`, When sell-to-open is submitted, Then the asset gate passes. |
| TST-REQ-ALP-021-02 | Edge | REQ-ALP-021 | Given asset status, class, tradability, shortability, or borrow status is missing or ineligible, When sell-to-open is requested, Then no order POST occurs and a safe refusal is returned. |
| TST-REQ-ALP-022-01 | Happy | REQ-ALP-022 | Given an approved whole-share short entry, When its payload is built, Then it contains positive `qty` and `sell_to_open` position intent without notional. |
| TST-REQ-ALP-022-02 | Edge | REQ-ALP-022 | Given a notional, fractional, zero, or negative short-entry quantity, When payload validation runs, Then the order is refused before submission. |
| TST-REQ-ALP-023-01 | Happy | REQ-ALP-023 | Given Alpaca reports a short position, When snapshots and lifecycle state are normalized, Then quantity is signed negative, side is short, P&L and trailing thresholds are short-aware, and exit uses buy-to-close for absolute quantity. |
| TST-REQ-ALP-023-02 | Edge | REQ-ALP-023 | Given a short position exit attempts sell-to-close, exceeds reconciled absolute quantity, or loses direction metadata, When validation runs, Then the exit is refused. |
| TST-REQ-ALP-024-01 | Happy | REQ-ALP-024 | Given no position and no unresolved order for a symbol, When a new entry is evaluated, Then it may continue through remaining gates. |
| TST-REQ-ALP-024-02 | Edge | REQ-ALP-024 | Given a nonzero position or unresolved order already exists for the symbol, When a new entry is evaluated, Then it is refused without crossing or adding to the position. |
| TST-REQ-ALP-025-01 | Happy | REQ-ALP-025 | Given a reconciled short whose entry eligibility later fails, When an exit triggers, Then the system submits buy-to-close for the exact absolute quantity without applying new-short entry gates. |
| TST-REQ-ALP-025-02 | Edge | REQ-ALP-025 | Given a fractional short from a corporate action and no supported exact close path, When an exit triggers, Then the system does not round or submit and returns an operator-action state. |
| TST-REQ-ALP-025-03 | Edge | REQ-ALP-025 | Given a reconciled short after the daily-loss, allocation, position-size, or open-position entry limit is reached, When an exact cover is evaluated, Then buy-to-close remains eligible through exit safety gates. |
| TST-REQ-ALP-026-01 | Happy | REQ-ALP-026 | Given a short belongs to one environment, provider, mode, and account reference, When it exits, Then submitter routing, audit, order event, and notification preserve that ownership. |
| TST-REQ-ALP-026-02 | Edge | REQ-ALP-026 | Given the configured exit submitter resolves to a different provider or account, When close validation runs, Then no venue call occurs and an account-routing refusal is recorded. |

### Data Ingestion and S3 Storage

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-DAT-001-01 | Happy | REQ-DAT-001 | Given enabled venues and the clock reaches 06:00 UTC, When the daily full-ingestion scheduler fires, Then a full market and trade snapshot is downloaded. |
| TST-REQ-DAT-001-02 | Edge | REQ-DAT-001 | Given no venues are enabled at 06:00 UTC, When full ingestion runs, Then no venue download starts and the skipped state is recorded. |
| TST-REQ-DAT-002-01 | Happy | REQ-DAT-002 | Given an existing checkpoint and elapsed incremental interval, When incremental ingestion runs, Then only new or changed data since that checkpoint is downloaded. |
| TST-REQ-DAT-002-02 | Edge | REQ-DAT-002 | Given the checkpoint is missing or corrupt, When incremental ingestion runs, Then the job fails safely or falls back according to configured policy without advancing the checkpoint. |
| TST-REQ-DAT-003-01 | Happy | REQ-DAT-003 | Given raw full, raw incremental, and normalized outputs, When storage writes complete, Then each output category is stored in S3. |
| TST-REQ-DAT-003-02 | Edge | REQ-DAT-003 | Given an S3 write failure for one output category, When ingestion completes, Then the job records failure and does not mark the snapshot fully stored. |
| TST-REQ-DAT-004-01 | Happy | REQ-DAT-004 | Given environment, venue, snapshot type, and UTC date, When an S3 object key is built, Then the path includes each partition. |
| TST-REQ-DAT-004-02 | Edge | REQ-DAT-004 | Given a missing partition value, When an S3 object key is built, Then the system rejects the write before storing an incorrectly partitioned object. |
| TST-REQ-DAT-005-01 | Happy | REQ-DAT-005 | Given fresh market data within the configured threshold, When live order checks run, Then the freshness gate passes. |
| TST-REQ-DAT-005-02 | Edge | REQ-DAT-005 | Given stale market data beyond the configured threshold, When live order checks run, Then dependent live orders are blocked. |
| TST-REQ-DAT-005-03 | Focus | REQ-DAT-005 | Given Polymarket market data is stale beyond the configured threshold, When live order checks run, Then dependent live orders are blocked and the refusal event is persisted. |
| TST-REQ-DAT-006-01 | Focus | REQ-DAT-006 | Given raw snapshot lifecycle rules are synthesized, When infrastructure configuration is validated, Then raw snapshots have a 365-day retention policy. |
| TST-REQ-DAT-006-02 | Focus | REQ-DAT-006 | Given S3 buckets are created by infrastructure, When lifecycle rules are validated, Then raw snapshots are retained for 365 days. |
| TST-REQ-DAT-007-01 | Focus | REQ-DAT-007 | Given normalized snapshot lifecycle rules are synthesized, When infrastructure configuration is validated, Then normalized snapshots have a 730-day retention policy. |
| TST-REQ-DAT-007-02 | Focus | REQ-DAT-007 | Given S3 buckets are created by infrastructure, When lifecycle rules are validated, Then normalized snapshots are retained for 730 days. |
| TST-REQ-DAT-008-01 | Focus | REQ-DAT-008 | Given an ingestion job fails after a prior checkpoint, When retry policy runs, Then the error is recorded, the checkpoint is preserved, and retry timing follows config. |

### Postgres Persistence

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-DB-001-01 | Happy | REQ-DB-001 | Given live and dry-run position events, When persistence runs, Then both position types are stored in Postgres. |
| TST-REQ-DB-001-02 | Edge | REQ-DB-001 | Given duplicate position events with the same idempotency key, When persistence runs, Then the system avoids duplicate position rows. |
| TST-REQ-DB-002-01 | Happy | REQ-DB-002 | Given Claude and OpenAI records, When migrations and repositories run, Then each model provider uses its separate schema. |
| TST-REQ-DB-002-02 | Edge | REQ-DB-002 | Given a repository attempts to write a model record to the wrong schema, When validation runs, Then the write is rejected. |
| TST-REQ-DB-003-01 | Happy | REQ-DB-003 | Given shared config, audit, and system health records, When persistence runs, Then shared records are stored in the shared schema. |
| TST-REQ-DB-003-02 | Edge | REQ-DB-003 | Given a shared record is routed to a model schema, When repository validation runs, Then the write is rejected. |
| TST-REQ-DB-004-01 | Happy | REQ-DB-004 | Given a trade decision with all required fields, When persistence runs, Then provider, venue, environment, instrument, signal, decision, order type, size, and timestamp are saved. |
| TST-REQ-DB-004-02 | Edge | REQ-DB-004 | Given a trade decision missing a required field, When persistence runs, Then the write fails and the omission is reported. |
| TST-REQ-DB-005-01 | Happy | REQ-DB-005 | Given a position state transition, When persistence runs, Then prior state, new state, realized P&L, unrealized P&L, and reason are stored. |
| TST-REQ-DB-005-02 | Edge | REQ-DB-005 | Given an invalid position state transition, When persistence runs, Then the transition is rejected and prior state remains intact. |
| TST-REQ-DB-006-01 | Focus | REQ-DB-006 | Given no later archive policy is configured, When retention settings are validated, Then audit, trade, and position history have no automatic deletion. |
| TST-REQ-DB-007-01 | Happy | REQ-DB-007 | Given Postgres is available, When live order checks require persistence, Then persistence health passes. |
| TST-REQ-DB-007-02 | Edge | REQ-DB-007 | Given Postgres is unavailable, When live order placement is requested, Then the order is blocked and logs plus dashboard status surface the failure. |
| TST-REQ-DB-009-01 | Regression | REQ-DB-009 | Given a scanner run with many candidates, When persistence succeeds, Then the run and all candidate rows commit through one database transaction. |
| TST-REQ-DB-009-02 | Edge | REQ-DB-009 | Given one scanner candidate write fails, When the batch is persisted, Then the transaction rolls back the scanner run and every candidate row. |
| TST-REQ-DB-010-01 | Regression | REQ-DB-010 | Given dashboard-relevant Postgres tables, When migrations run, Then commit-scoped notification triggers publish coalescible environment and optional username invalidations without attaching high-volume candidate or bar detail tables. |
| TST-REQ-DB-010-02 | Edge | REQ-DB-010 | Given dashboard subscribers for multiple environments and users, When an invalidation is published, Then only matching subscribers receive it and a slow subscriber retains at most one pending refresh. |
| TST-REQ-DB-007-03 | Edge | REQ-DB-007 | Given a deployed bare Postgres DSN, When the SQLAlchemy session factory initializes, Then the installed psycopg driver is selected instead of psycopg2. |
| TST-REQ-DB-008-01 | Happy | REQ-DB-008 | Given confirmed venue account, position, and fill data, When reconciliation persists a snapshot, Then rows retain environment, venue, provider, and account attribution without credential material. |
| TST-REQ-DB-008-02 | Edge | REQ-DB-008 | Given a position or fill write fails during account reconciliation, When the database transaction rolls back, Then no partial account snapshot, position, or fill rows remain. |

### Wallet and Secrets Management

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-WAL-001-01 | Happy | REQ-WAL-001 | Given environment, venue, and model provider combinations, When credential references are resolved, Then each combination can use separate wallet or brokerage credentials. |
| TST-REQ-WAL-001-02 | Edge | REQ-WAL-001 | Given two combinations resolve to the same disallowed credential reference, When live checks run, Then the duplicate is rejected. |
| TST-REQ-WAL-002-01 | Happy | REQ-WAL-002 | Given wallet-generation CLI inputs for environment, venue, and provider, When the command runs, Then wallet material is generated for that target. |
| TST-REQ-WAL-002-02 | Edge | REQ-WAL-002 | Given missing or unsupported CLI inputs, When wallet generation runs, Then no wallet material is produced and validation errors are returned. |
| TST-REQ-WAL-003-01 | Happy | REQ-WAL-003 | Given deployed environment settings, When private keys and API credentials are requested, Then they are read only from AWS Secrets Manager. |
| TST-REQ-WAL-003-02 | Edge | REQ-WAL-003 | Given deployed environment settings and a local secret file path, When credential loading runs, Then local secret loading is rejected. |
| TST-REQ-WAL-003-03 | Focus | REQ-WAL-003 | Given an ECS task attempts to read deployment secrets, When IAM secret scope is validated, Then only the current environment secret prefix is allowed. |
| TST-REQ-WAL-003-04 | Focus | REQ-WAL-003 | Given wallet and deployment docs, When deployed secret handling is reviewed, Then deployed credentials are documented as AWS Secrets Manager values. |
| TST-REQ-WAL-004-01 | Happy | REQ-WAL-004 | Given local development settings and gitignored `.env` values, When credential loading runs, Then private keys and API credentials are read from local environment values. |
| TST-REQ-WAL-004-02 | Edge | REQ-WAL-004 | Given local development settings with missing `.env` values, When live checks run, Then orders requiring those credentials are refused. |
| TST-REQ-WAL-005-01 | Happy | REQ-WAL-005 | Given wallet and credential metadata, When dashboard status is rendered, Then public identifiers and health are shown. |
| TST-REQ-WAL-005-02 | Edge | REQ-WAL-005 | Given private keys or API secrets are present in secret storage, When dashboard status is rendered, Then secret values are never returned. |
| TST-REQ-WAL-006-01 | Happy | REQ-WAL-006 | Given all required wallet, brokerage, and API credentials exist, When live order checks run, Then the credential gate passes. |
| TST-REQ-WAL-006-02 | Edge | REQ-WAL-006 | Given any required secret or credential is missing, When live order checks run, Then the order is refused and the missing credential reason is recorded. |
| TST-REQ-WAL-007-01 | Focus | REQ-WAL-007 | Given credentials are rotated in the configured store, When the next credential refresh runs, Then updated secrets are used without redeploy. |

### LLM Scoring

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-LLM-001-01 | Happy | REQ-LLM-001 | Given eligible Polymarket and Alpaca candidates, When scoring runs, Then both Claude and OpenAI providers evaluate the candidates. |
| TST-REQ-LLM-001-02 | Edge | REQ-LLM-001 | Given one model provider is disabled or out of budget, When scoring runs, Then eligible remaining providers continue independently. |
| TST-REQ-LLM-001-03 | Focus | REQ-LLM-001 | Given configured OpenAI and Claude credentials are present, When eligible scoring requests run through provider adapters, Then both providers receive scoring requests through their external API boundary. |
| TST-REQ-LLM-002-01 | Happy | REQ-LLM-002 | Given Claude and OpenAI budget settings, When scoring costs are recorded, Then each provider budget is tracked separately. |
| TST-REQ-LLM-002-02 | Edge | REQ-LLM-002 | Given a scoring event attempts to consume the wrong provider budget, When budget accounting runs, Then the event is rejected or corrected before persistence. |
| TST-REQ-LLM-002-03 | Focus | REQ-LLM-002 | Given provider cost is returned or estimated, When budget ledger reconciliation runs, Then cost entries are recorded and structured budget status is emitted. |
| TST-REQ-LLM-003-01 | Happy | REQ-LLM-003 | Given a successful model evaluation, When the score is persisted, Then provider, prompt version, input summary, thesis, confidence, probability, and cost estimate are stored. |
| TST-REQ-LLM-003-02 | Edge | REQ-LLM-003 | Given a model response missing required scoring fields, When parsing runs, Then the score is marked failed and no live order can use it. |
| TST-REQ-LLM-004-01 | Happy | REQ-LLM-004 | Given a model budget is exhausted, When scoring queues are built, Then no new requests are sent to that model. |
| TST-REQ-LLM-004-02 | Edge | REQ-LLM-004 | Given Claude is exhausted and OpenAI has budget, When scoring runs, Then OpenAI continues while Claude is skipped. |
| TST-REQ-LLM-004-03 | Focus | REQ-LLM-004 | Given OpenAI is exhausted and Claude has budget, When scoring runs through external provider adapters, Then OpenAI receives no request and Claude continues independently. |
| TST-REQ-LLM-005-01 | Happy | REQ-LLM-005 | Given LLM scoring succeeds for a model and market, When execution eligibility is checked, Then the scoring failure gate passes. |
| TST-REQ-LLM-005-02 | Edge | REQ-LLM-005 | Given LLM scoring fails for a model and market, When execution eligibility is checked in the same loop, Then live orders are blocked for that pair. |
| TST-REQ-LLM-006-01 | Focus | REQ-LLM-006 | Given an authorized dashboard user changes model budgets or scoring settings, When the update is saved, Then the new scoring config is persisted. |
| TST-REQ-LLM-007-01 | Focus | REQ-LLM-007 | Given scoring config changes are saved, When the next trading loop starts, Then the updated settings are used. |

### Strategy and Signal Engine

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-STR-001-01 | Happy | REQ-STR-001 | Given default scheduler config, When the worker starts, Then the trading loop interval is 15 minutes. |
| TST-REQ-STR-001-02 | Edge | REQ-STR-001 | Given scheduler drift or a slow loop body, When the next loop is scheduled, Then the cadence is measured and logged without overlapping unsafe work. |
| TST-REQ-STR-002-01 | Happy | REQ-STR-002 | Given an authorized dashboard update to loop interval, When config is saved, Then the new interval is persisted. |
| TST-REQ-STR-002-02 | Edge | REQ-STR-002 | Given an invalid loop interval, When dashboard config is saved, Then validation rejects the value. |
| TST-REQ-STR-003-01 | Happy | REQ-STR-003 | Given enabled venues and markets that pass deterministic filters, When the trading loop runs, Then filtered markets are sent to LLM scoring. |
| TST-REQ-STR-003-02 | Edge | REQ-STR-003 | Given markets fail deterministic filters, When the trading loop runs, Then no LLM scoring request is created for them. |
| TST-REQ-STR-004-01 | Happy | REQ-STR-004 | Given related-market prices with a configured dislocation, When arbitrage strategy runs, Then an arbitrage signal is produced. |
| TST-REQ-STR-004-02 | Edge | REQ-STR-004 | Given dislocation is below threshold or data is stale, When arbitrage strategy runs, Then no arbitrage signal is produced. |
| TST-REQ-STR-005-01 | Happy | REQ-STR-005 | Given market price differs from model estimate beyond threshold, When convergence strategy runs, Then a convergence signal is produced. |
| TST-REQ-STR-005-02 | Edge | REQ-STR-005 | Given price and model estimate are within threshold, When convergence strategy runs, Then no convergence signal is produced. |
| TST-REQ-STR-006-01 | Happy | REQ-STR-006 | Given target wallet activity and configured delay settings, When whale-copy strategy runs after the delay, Then a whale-copy signal is produced. |
| TST-REQ-STR-006-02 | Edge | REQ-STR-006 | Given target wallet activity occurs within a blocked delay or from an unconfigured wallet, When whale-copy strategy runs, Then no signal is produced. |
| TST-REQ-STR-007-01 | Happy | REQ-STR-007 | Given multiple strategies produce signals for the same market and model, When decision creation starts, Then each strategy signal is recorded first. |
| TST-REQ-STR-007-02 | Edge | REQ-STR-007 | Given signal persistence fails, When decision creation starts, Then execution decision creation is blocked. |
| TST-REQ-STR-008-01 | Happy | REQ-STR-008 | Given strategy signals disagree, When consensus rules run, Then the configured rule determines whether an order decision is created. |
| TST-REQ-STR-008-02 | Edge | REQ-STR-008 | Given an unknown consensus rule, When signals disagree, Then no order is created and config validation reports the issue. |
| TST-REQ-STR-009-01 | Focus | REQ-STR-009 | Given an authorized dashboard user changes strategy enabled flags or settings, When config is saved, Then strategy config is persisted and available to the next loop. |

### Risk and Execution Engine

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-EXE-001-01 | Happy | REQ-EXE-001 | Given no explicit live trading override, When environment config is loaded, Then `LIVE_ENABLED=false` in all environments. |
| TST-REQ-EXE-001-02 | Edge | REQ-EXE-001 | Given an explicit live trading override is absent or invalid, When config validation runs, Then live trading remains disabled. |
| TST-REQ-EXE-002-01 | Happy | REQ-EXE-002 | Given dry-run mode is enabled, When an order is approved, Then a simulated order is recorded. |
| TST-REQ-EXE-002-02 | Edge | REQ-EXE-002 | Given dry-run mode is enabled and a venue client mock is attached, When execution runs, Then no venue submission method is called. |
| TST-REQ-EXE-003-01 | Happy | REQ-EXE-003 | Given an authorized dashboard user toggles dry-run to live, When the next trading loop starts, Then live mode config is applied. |
| TST-REQ-EXE-003-02 | Edge | REQ-EXE-003 | Given an unauthorized user attempts to toggle dry-run to live, When the dashboard request is processed, Then the change is rejected. |
| TST-REQ-EXE-004-01 | Happy | REQ-EXE-004 | Given default Polymarket risk config, When an order size is exactly 25 USD, Then the order passes the max-position boundary check. |
| TST-REQ-EXE-004-02 | Edge | REQ-EXE-004 | Given default Polymarket risk config, When an order size exceeds 25 USD, Then the order is refused. |
| TST-REQ-EXE-005-01 | Happy | REQ-EXE-005 | Given default Polymarket risk config, When daily loss equals 50 USD for a model provider and a new order is evaluated, Then the order is refused because max daily loss is reached. |
| TST-REQ-EXE-005-02 | Edge | REQ-EXE-005 | Given default Polymarket risk config, When daily loss exceeds 50 USD for a model provider, Then additional orders are refused. |
| TST-REQ-EXE-006-01 | Happy | REQ-EXE-006 | Given default Polymarket risk config and 4 open positions, When an approved order would create the fifth open position, Then the order passes the max-open boundary check. |
| TST-REQ-EXE-006-02 | Edge | REQ-EXE-006 | Given default Polymarket risk config, When a sixth open position would be created, Then the order is refused. |
| TST-REQ-EXE-007-01 | Happy | REQ-EXE-007 | Given an authorized dashboard user updates max position, daily loss, or open positions, When config is saved, Then risk limits are persisted. |
| TST-REQ-EXE-007-02 | Edge | REQ-EXE-007 | Given invalid risk limit values, When dashboard config is saved, Then validation rejects the values. |
| TST-REQ-EXE-008-01 | Happy | REQ-EXE-008 | Given a positive Kelly result above a configured risk cap, When sizing runs, Then final size is capped by the risk limit. |
| TST-REQ-EXE-008-02 | Edge | REQ-EXE-008 | Given missing probability, odds, or bankroll inputs, When Kelly sizing runs, Then sizing fails safely and no order is created. |
| TST-REQ-EXE-009-01 | Happy | REQ-EXE-009 | Given Kelly calculation returns a positive size, When execution checks run, Then the non-positive-size refusal gate passes. |
| TST-REQ-EXE-009-02 | Edge | REQ-EXE-009 | Given Kelly calculation returns zero or negative size, When execution checks run, Then the trade is refused. |
| TST-REQ-EXE-010-01 | Happy | REQ-EXE-010 | Given approved limit and market order decisions, When execution routes orders, Then both order types are supported. |
| TST-REQ-EXE-010-02 | Edge | REQ-EXE-010 | Given an unsupported order type, When execution routes the order, Then the order is rejected. |
| TST-REQ-EXE-011-01 | Happy | REQ-EXE-011 | Given a market order with estimated slippage at or below threshold, When execution checks run, Then the slippage gate passes. |
| TST-REQ-EXE-011-02 | Edge | REQ-EXE-011 | Given a market order with estimated slippage above threshold, When execution checks run, Then the market order is blocked. |
| TST-REQ-EXE-012-01 | Happy | REQ-EXE-012 | Given default Polymarket config, When market order slippage threshold is loaded, Then it equals 2 percent. |
| TST-REQ-EXE-012-02 | Edge | REQ-EXE-012 | Given a dashboard override for slippage threshold, When config is loaded, Then the override replaces the 2 percent default only after validation. |
| TST-REQ-EXE-013-01 | Happy | REQ-EXE-013 | Given all live-order gates pass, When live order placement is requested, Then the order may proceed to venue submission. |
| TST-REQ-EXE-013-02 | Edge | REQ-EXE-013 | Given any configured refusal reason is present, When live order placement is requested, Then the order is refused and the reason is persisted. |
| TST-REQ-EXE-014-01 | Happy | REQ-EXE-014 | Given the kill switch is inactive, When live eligibility is checked, Then normal live gates apply. |
| TST-REQ-EXE-014-02 | Edge | REQ-EXE-014 | Given the kill switch is activated, When live eligibility is checked, Then live trading is disabled for all models and venues. |
| TST-REQ-EXE-014-03 | Focus | REQ-EXE-014 | Given the operations dashboard renders, When dashboard operations checks run, Then kill-switch state and degraded venue status are visible. |
| TST-REQ-EXE-015-01 | Happy | REQ-EXE-015 | Given kill switch activation and enabled live venues with open orders, When kill switch handling runs, Then cancel attempts are issued for open orders. |
| TST-REQ-EXE-015-02 | Edge | REQ-EXE-015 | Given a venue cancel attempt fails, When kill switch handling runs, Then the failure is recorded and remaining cancel attempts continue. |
| TST-REQ-EXE-015-03 | Focus | REQ-EXE-015 | Given the operations dashboard renders, When dashboard operations checks run, Then cancel progress and manual-review state are visible. |
| TST-REQ-EXE-016-01 | Happy | REQ-EXE-016 | Given an order is refused, submitted, filled, canceled, or failed, When the event is processed, Then it is persisted and visible in dashboard status. |
| TST-REQ-EXE-016-02 | Edge | REQ-EXE-016 | Given event persistence fails, When an order event is processed, Then the system reports degraded status and avoids hiding the failure. |
| TST-REQ-EXE-016-03 | Focus | REQ-EXE-016 | Given the operations dashboard renders order events, When dashboard operations checks run, Then refused, submitted, filled, canceled, failed, and unknown states are displayed. |
| TST-REQ-EXE-016-07 | Focus | REQ-EXE-016 | Given live execution has provider-specific venue submitters, When OpenAI and Claude outputs are approved, Then each output is submitted through the account for its venue and model provider. |
| TST-REQ-EXE-016-08 | Edge | REQ-EXE-016 | Given one model provider lacks a venue submitter, When that provider has an approved live output, Then the order is refused instead of using another provider's account. |
| TST-REQ-EXE-016-11 | Happy | REQ-EXE-016 | Given durable order intents exist across environments and states, When an authenticated user requests order history, Then the system returns only selected-environment records in validated newest-first cursor pages with execution details. |
| TST-REQ-EXE-016-12 | Edge | REQ-EXE-016 | Given durable order history cannot be read, When an authenticated user requests order history, Then the system reports a service failure instead of an empty history. |
| TST-REQ-EXE-017-01 | Happy | REQ-EXE-017 | Given dry-run is disabled, venue is enabled, account mode is valid, and all checks pass, When live execution runs, Then live orders are permitted. |
| TST-REQ-EXE-017-02 | Edge | REQ-EXE-017 | Given dry-run is disabled but a venue is disabled or account mode fails checks, When live execution runs, Then live orders are blocked. |
| TST-REQ-EXE-017-03 | Focus | REQ-EXE-017 | Given live trading checklist docs, When an operator prepares live trading, Then account, dry-run, venue, risk, auth, SES, and kill-switch checks are required. |

### Exit Monitoring

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-EXT-001-01 | Happy | REQ-EXT-001 | Given open positions and configured exit triggers, When exit monitoring runs, Then positions are evaluated against the triggers. |
| TST-REQ-EXT-001-02 | Edge | REQ-EXT-001 | Given no open positions, When exit monitoring runs, Then no exit decisions are created and the loop records an empty result. |
| TST-REQ-EXT-002-01 | Happy | REQ-EXT-002 | Given a position reaches the configured profit target, When exit monitoring runs, Then an exit decision is created. |
| TST-REQ-EXT-002-02 | Edge | REQ-EXT-002 | Given a position is just below the profit target, When exit monitoring runs, Then no profit-target exit decision is created. |
| TST-REQ-EXT-003-01 | Happy | REQ-EXT-003 | Given volume spike exceeds the configured threshold, When exit monitoring runs, Then an exit decision is created. |
| TST-REQ-EXT-003-02 | Edge | REQ-EXT-003 | Given volume spike is below threshold or data is stale, When exit monitoring runs, Then no volume-spike exit decision is created. |
| TST-REQ-EXT-004-01 | Happy | REQ-EXT-004 | Given thesis age and price movement exceed stale-thesis thresholds, When exit monitoring runs, Then an exit decision is created. |
| TST-REQ-EXT-004-02 | Edge | REQ-EXT-004 | Given only one stale-thesis condition is met when both are required by config, When exit monitoring runs, Then no stale-thesis exit is created. |
| TST-REQ-EXT-005-01 | Happy | REQ-EXT-005 | Given dry-run mode is enabled and an exit is approved, When exit execution runs, Then a simulated exit is recorded. |
| TST-REQ-EXT-005-02 | Edge | REQ-EXT-005 | Given dry-run mode is enabled and venue clients are mocked, When exit execution runs, Then no venue exit order is submitted. |
| TST-REQ-EXT-006-01 | Happy | REQ-EXT-006 | Given live mode is enabled and an exit is approved, When exit execution runs, Then the exit is routed through risk and execution. |
| TST-REQ-EXT-006-02 | Edge | REQ-EXT-006 | Given live mode is enabled but risk checks fail, When exit execution runs, Then no venue exit order is submitted. |

### Dashboard and GitHub OAuth

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-UI-001-01 | Happy | REQ-UI-001 | Given backend and frontend services are running, When the dashboard loads, Then the Next.js UI retrieves data from FastAPI services. |
| TST-REQ-UI-001-02 | Edge | REQ-UI-001 | Given FastAPI is unavailable, When the dashboard loads status views, Then the UI shows degraded API state without exposing internals. |
| TST-REQ-UI-001-03 | Focus | REQ-UI-001 | Given the backend app is created, When health and dashboard API routes are called, Then FastAPI exposes liveness and authenticated dashboard endpoints. |
| TST-REQ-UI-001-04 | Focus | REQ-UI-001 | Given deployed dashboard environment variables, When the FastAPI app loads default settings, Then auth, CSRF, origin, and environment settings come from the environment. |
| TST-REQ-UI-002-01 | Happy | REQ-UI-002 | Given an unauthenticated user, When the dashboard is opened, Then GitHub OAuth login is required. |
| TST-REQ-UI-002-02 | Edge | REQ-UI-002 | Given an invalid OAuth callback or state value, When login completes, Then access is denied and the event is logged. |
| TST-REQ-UI-002-03 | Focus | REQ-UI-002 | Given a protected dashboard route and server-side session helper, When frontend auth checks run, Then unauthenticated users are redirected to login before protected views load. |
| TST-REQ-UI-003-01 | Happy | REQ-UI-003 | Given an authenticated GitHub username on the allowlist, When dashboard access is checked, Then access is granted. |
| TST-REQ-UI-003-02 | Edge | REQ-UI-003 | Given an authenticated GitHub username not on the allowlist, When dashboard access is checked, Then access is denied. |
| TST-REQ-UI-003-03 | Edge | REQ-UI-003 | Given unauthenticated and unallowlisted dashboard API callers, When protected endpoints are requested, Then the API returns 401 or 403 before returning protected data. |
| TST-REQ-UI-003-04 | Focus | REQ-UI-003 | Given a GitHub username outside the frontend allowlist, When dashboard auth checks run, Then the UI redirects to access denied and avoids mutation calls. |
| TST-REQ-UI-004-01 | Happy | REQ-UI-004 | Given an authorized user, When status pages load, Then venue, model, wallet, ingestion, loop, position, order, and notification status are visible. |
| TST-REQ-UI-004-02 | Edge | REQ-UI-004 | Given a status source is unavailable, When status pages load, Then the dashboard marks that source degraded rather than showing stale success. |
| TST-REQ-UI-004-03 | Focus | REQ-UI-004 | Given an authenticated allowlisted user, When dashboard summary data is requested, Then dashboard sections are returned without secrets. |
| TST-REQ-UI-004-04 | Focus | REQ-UI-004 | Given frontend dashboard controls exist, When dashboard control checks run, Then venue, wallet, ingestion, trading loop, notification, audit, and health sections are present. |
| TST-REQ-UI-004-05 | Focus | REQ-UI-004 | Given multiple authorized dashboard users save display preferences, When preferences and dashboard summary are requested, Then each response loads the authenticated user's database preferences. |
| TST-REQ-UI-004-06 | Regression | REQ-UI-004 | Given scanner candidate details are deferred, When the default dashboard summary loads, Then it reports the latest persisted scanner totals and venue-specific rejection reasons from the scanner pipeline step without reading candidate history. |
| TST-REQ-UI-014-01 | Regression | REQ-UI-014 | Given realtime WebSocket setup fails and snapshot latency exceeds the polling interval, When polling continues, Then only one snapshot request is active and the next retry starts after bounded backoff. |
| TST-REQ-UI-014-02 | Regression | REQ-UI-014 | Given multiple enabled venues and persisted market-data history, When the dashboard snapshot loads, Then it reads only the latest indexed market-data row for each enabled venue and reuses worker and tick-schedule state. |
| TST-REQ-UI-015-01 | Happy | REQ-UI-015 | Given an authorized WebSocket connection, When the connection opens and a matching committed-state invalidation arrives, Then it receives one initial snapshot, idle heartbeats without snapshot queries, and one updated snapshot containing portfolio data. |
| TST-REQ-UI-015-02 | Edge | REQ-UI-015 | Given the WebSocket closes or its database event source is unavailable, When recovery starts, Then the browser uses single-flight polling and retries the WebSocket with bounded backoff. |
| TST-REQ-UI-005-01 | Happy | REQ-UI-005 | Given an authorized user changes supported config fields, When the dashboard saves them, Then venue flags, dry-run/live, loop, strategy, budget, risk, slippage, and notification settings persist. |
| TST-REQ-UI-005-02 | Edge | REQ-UI-005 | Given invalid or unauthorized config changes, When the dashboard saves them, Then the changes are rejected and existing config remains. |
| TST-REQ-UI-005-03 | Focus | REQ-UI-005 | Given frontend config controls exist, When dashboard control checks run, Then saves are limited to allowlisted config paths. |
| TST-REQ-UI-006-01 | Happy | REQ-UI-006 | Given an authorized dashboard config change, When it is saved, Then user, old value, new value, timestamp, environment, and IP address are audited. |
| TST-REQ-UI-006-02 | Edge | REQ-UI-006 | Given audit persistence fails for a config change, When save is attempted, Then the config change is not applied silently. |
| TST-REQ-UI-006-03 | Focus | REQ-UI-006 | Given an authorized dashboard API caller changes config, When the config endpoint receives a valid patch, Then the API returns the new version and persists an audit event. |
| TST-REQ-UI-006-04 | Focus | REQ-UI-006 | Given browser code calls backend data, When frontend auth-boundary checks run, Then requests use the Next.js proxy and backend tokens remain server-only. |
| TST-REQ-UI-007-01 | Happy | REQ-UI-007 | Given dashboard config is saved, When the next trading loop starts, Then the changed config is applied without restart. |
| TST-REQ-UI-007-02 | Edge | REQ-UI-007 | Given config reload fails on the next loop, When the loop starts, Then prior valid config remains active and degraded status is surfaced. |
| TST-REQ-UI-007-03 | Focus | REQ-UI-007 | Given a frontend config save conflict, When dashboard control checks run, Then the UI shows the current server version and requires reload before resubmission. |
| TST-REQ-UI-007-04 | Focus | REQ-UI-007 | Given a user has no prior saved config row, When the dashboard saves a settings patch, Then the new user config starts from deployed runtime defaults. |
| TST-REQ-UI-007-05 | Focus | REQ-UI-007 | Given multiple dashboard users are allowed and one user saved runtime config, When the scheduler resolves config, Then it loads the user-owned database config instead of shared defaults. |
| TST-REQ-UI-008-01 | Happy | REQ-UI-008 | Given an authorized user activates the dashboard kill switch, When the request is processed, Then the global kill switch state is set. |
| TST-REQ-UI-008-02 | Edge | REQ-UI-008 | Given an unauthorized user attempts kill switch activation, When the request is processed, Then the request is denied. |
| TST-REQ-UI-008-03 | Focus | REQ-UI-008 | Given an authorized dashboard API caller activates the kill switch, When the kill switch endpoint is called, Then live trading is disabled and cancel progress is exposed. |
| TST-REQ-UI-009-01 | Focus | REQ-UI-009 | Given wallet metadata contains public identifiers and private secret references, When dashboard wallet views render, Then only public identifiers and health are shown. |
| TST-REQ-UI-009-02 | Focus | REQ-UI-009 | Given frontend wallet status renders, When dashboard control checks run, Then public identifiers are displayed and private key or secret terms are absent. |
| TST-REQ-UI-010-01 | Focus | REQ-UI-010 | Given Claude and OpenAI records exist, When dashboard model views render, Then positions, decisions, budgets, and P&L are separated by provider. |
| TST-REQ-UI-010-02 | Focus | REQ-UI-010 | Given frontend model routes exist, When dashboard operations checks run, Then Claude and OpenAI model views show provider-specific positions, decisions, budgets, and P&L. |
| TST-REQ-UI-011-01 | Happy | REQ-UI-011 | Given comparison metrics exist for Polymarket and Alpaca, When dashboard comparison views render, Then P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk are shown. |
| TST-REQ-UI-011-02 | Edge | REQ-UI-011 | Given one model or venue has insufficient comparison data, When comparison views render, Then unavailable metrics are labeled without showing misleading zero values. |
| TST-REQ-UI-011-03 | Focus | REQ-UI-011 | Given frontend comparison routes exist, When dashboard operations checks run, Then unavailable comparison metrics show caveats rather than zero values. |
| TST-REQ-UI-012-01 | Focus | REQ-UI-012 | Given recent scanner rejections point to configurable thresholds, When dashboard control checks run, Then the dashboard exposes a targeted recommendation that can save the suggested config through the existing audited config flow. |
| TST-REQ-UI-012-02 | Edge | REQ-UI-012 | Given a recommendation changes an integer-only cap and the latest market-data total includes multiple venues, When dashboard control checks run, Then the patch value remains a number and the funnel shows each venue's candidate count. |
| TST-REQ-UI-013-01 | Happy | REQ-UI-013 | Given current Polymarket US and Alpaca account snapshots, When the authenticated portfolio API is read, Then account value, realized P&L, unrealized P&L, open positions, and confirmed fills are returned by venue and model-provider account. |
| TST-REQ-UI-013-02 | Edge | REQ-UI-013 | Given a venue refresh fails after a successful snapshot, When the main dashboard reads portfolio data, Then the last confirmed values remain visible with stale status and the refresh failure is explained. |
| TST-REQ-UI-013-03 | Focus | REQ-UI-013 | Given the main dashboard frontend is checked, When dashboard contract tests run, Then the actual portfolio, venue breakdown, open holdings, confirmed fills, freshness, and unavailable states are present. |
| TST-REQ-UI-013-04 | Focus | REQ-UI-013 | Given configured venue credentials and provider responses, When portfolio sources refresh, Then current Polymarket US decimal positions, confirmed activity, settlements, and Alpaca account data are normalized without exposing credentials. |
| TST-REQ-UI-013-05 | Edge | REQ-UI-013 | Given venue accounts refresh in adjacent minute buckets, When portfolio history is produced, Then each point carries forward the latest confirmed value for accounts that did not refresh in that minute. |
| TST-REQ-UI-013-06 | Focus | REQ-UI-013 | Given venue-confirmed account snapshots include equity, cash, and optional buying power, When Performance renders account balances, Then each model-provider account shows equity, cash, and available-to-trade balance using buying power when present and cash otherwise, while missing values remain unavailable. |
| TST-REQ-UI-013-07 | Edge | REQ-UI-013 | Given Polymarket US returns cash without a buying-power field, When the venue account snapshot is normalized, Then buying power remains unavailable so the dashboard can use the confirmed cash balance instead of showing a fabricated zero. |
| TST-REQ-UI-013-08 | Focus | REQ-UI-013 | Given venue-confirmed portfolio state, When Overview renders, Then it shows only compact current status and a link to Performance rather than detailed account, holding, or fill data. |

### Cross-Market Comparison Analytics

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-CMP-001-01 | Happy | REQ-CMP-001 | Given trades and positions across providers, venues, environments, and instrument types, When metrics are calculated, Then results are grouped by those dimensions. |
| TST-REQ-CMP-001-02 | Edge | REQ-CMP-001 | Given records missing grouping dimensions, When metrics are calculated, Then invalid records are excluded or marked unavailable with a reason. |
| TST-REQ-CMP-002-01 | Happy | REQ-CMP-002 | Given Claude and OpenAI performance data for Polymarket and Alpaca, When comparison runs, Then model performance is compared across both markets. |
| TST-REQ-CMP-002-02 | Edge | REQ-CMP-002 | Given one market has no eligible data, When comparison runs, Then the missing market is marked unavailable without blocking other comparisons. |
| TST-REQ-CMP-003-01 | Happy | REQ-CMP-003 | Given complete trade, position, and model cost data, When comparison metrics are calculated, Then documented formulas produce realized P&L, unrealized P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk. |
| TST-REQ-CMP-003-02 | Edge | REQ-CMP-003 | Given divide-by-zero or missing input for a documented formula, When metrics are calculated, Then the metric is unavailable rather than invalid. |
| TST-REQ-CMP-004-01 | Focus | REQ-CMP-004 | Given insufficient data for a metric, When dashboard or API comparison output is produced, Then the metric value is unavailable rather than zero. |
| TST-REQ-CMP-005-01 | Happy | REQ-CMP-005 | Given confirmed fills, open positions, simulated orders, and duplicate model credentials for one account, When portfolio totals are calculated, Then only confirmed venue data is included and the shared account is counted once. |
| TST-REQ-CMP-005-02 | Edge | REQ-CMP-005 | Given no successful venue snapshot exists, When portfolio totals are calculated, Then monetary metrics are unavailable rather than reported as zero. |
| TST-REQ-CMP-005-03 | Edge | REQ-CMP-005 | Given separate model credentials resolve to the same venue account identity, When provider-backed reconciliation runs, Then both providers share one sanitized account reference and totals count the account once. |

### Notifications

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-NOT-001-01 | Happy | REQ-NOT-001 | Given the daily digest schedule fires and allowlisted users exist, When notifications run, Then SES sends digest email to allowlisted users. |
| TST-REQ-NOT-001-02 | Edge | REQ-NOT-001 | Given no allowlisted recipients exist, When digest notifications run, Then no email is sent and the skipped reason is recorded. |
| TST-REQ-NOT-001-03 | Focus | REQ-NOT-001 | Given the daily digest schedule is reached and allowlisted recipients exist, When the notification loop runs, Then SES sends the rendered digest to the configured allowlist. |
| TST-REQ-NOT-002-01 | Happy | REQ-NOT-002 | Given digest inputs are available, When the digest is rendered, Then it includes P&L, open positions, trades, exits, refused orders, budget, ingestion, and risk status. |
| TST-REQ-NOT-002-02 | Edge | REQ-NOT-002 | Given one digest input source is unavailable, When the digest is rendered, Then the missing section is marked unavailable and delivery can still proceed if policy allows. |
| TST-REQ-NOT-003-01 | Happy | REQ-NOT-003 | Given a position P&L change reaches 25 USD or 10 percent by default, When movement detection runs, Then SES sends a large-movement alert. |
| TST-REQ-NOT-003-02 | Edge | REQ-NOT-003 | Given a position P&L change is below both default thresholds, When movement detection runs, Then no large-movement alert is sent. |
| TST-REQ-NOT-003-03 | Focus | REQ-NOT-003 | Given position P&L crosses the alert threshold and no cooldown is active, When alert delivery runs, Then SES sends the alert and records cooldown for the alert key. |
| TST-REQ-NOT-004-01 | Happy | REQ-NOT-004 | Given daily realized or unrealized P&L crosses a configured threshold, When notification checks run, Then SES sends an alert. |
| TST-REQ-NOT-004-02 | Edge | REQ-NOT-004 | Given daily P&L remains within thresholds, When notification checks run, Then no threshold alert is sent. |
| TST-REQ-NOT-005-01 | Happy | REQ-NOT-005 | Given default notification config, When an alert was sent less than 30 minutes ago for the same market and provider, Then another alert is suppressed. |
| TST-REQ-NOT-005-02 | Edge | REQ-NOT-005 | Given the 30-minute cooldown has elapsed, When the alert condition still holds, Then a new alert is allowed. |
| TST-REQ-NOT-006-01 | Focus | REQ-NOT-006 | Given an authorized dashboard user changes recipients, thresholds, schedules, or cooldowns, When notification config is saved, Then the updated settings persist. |
| TST-REQ-NOT-006-02 | Focus | REQ-NOT-006 | Given notification settings change in the dashboard, When the next notification loop reads config, Then recipients, thresholds, schedule, and cooldown use the updated values. |
| TST-REQ-NOT-007-01 | Focus | REQ-NOT-007 | Given SES delivery fails, When retry policy runs, Then the failure is recorded and retry timing follows config. |
| TST-REQ-NOT-007-02 | Focus | REQ-NOT-007 | Given SES delivery fails, When notification delivery handles the result, Then the failure is recorded and next retry timing follows policy. |

### Deployment, CI/CD, and Codex Web Setup

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-DEP-001-01 | Happy | REQ-DEP-001 | Given local Docker and gitignored `.env` files, When local startup commands run, Then the app stack starts without production secrets. |
| TST-REQ-DEP-001-02 | Edge | REQ-DEP-001 | Given required local env values are missing, When local startup runs, Then startup fails with safe dry-run defaults or clear setup errors. |
| TST-REQ-DEP-001-03 | Focus | REQ-DEP-001 | Given local development docs, When a developer follows setup guidance, Then Docker startup and gitignored `.env` files are documented. |
| TST-REQ-DEP-001-04 | Focus | REQ-DEP-001 | Given the local Docker Compose contract, When the app stack services are inspected, Then backend and frontend services run the real app processes. |
| TST-REQ-DEP-002-01 | Happy | REQ-DEP-002 | Given CloudFormation parameters for us-east-1, When infrastructure templates are validated, Then ECS Fargate, RDS, S3, Secrets Manager, CloudWatch, SES, IAM, and ECR resources are defined. |
| TST-REQ-DEP-002-02 | Edge | REQ-DEP-002 | Given a non-us-east-1 deployment target, When deployment validation runs, Then deployment is blocked or requires explicit override. |
| TST-REQ-DEP-002-03 | Focus | REQ-DEP-002 | Given CloudFormation infrastructure, When public application resources are inspected, Then ALB, frontend service, backend service, runtime env settings, and the Postgres psycopg driver DSN are defined. |
| TST-REQ-DEP-002-04 | Focus | REQ-DEP-002 | Given ALB listener rules, When frontend auth and backend API routes are inspected, Then /api/auth/* is routed to the frontend before backend /api/* routing. |
| TST-REQ-DEP-003-01 | Happy | REQ-DEP-003 | Given code is merged to `develop`, When GitHub Actions runs, Then the development deployment workflow is selected. |
| TST-REQ-DEP-003-02 | Edge | REQ-DEP-003 | Given a branch other than `develop` or `main`, When GitHub Actions runs, Then automatic environment deployment is not triggered. |
| TST-REQ-DEP-003-03 | Focus | REQ-DEP-003 | Given code is merged to `develop`, When the workflow is inspected, Then development deployment is selected after tests, migration safety, and ECR publish. |
| TST-REQ-DEP-004-01 | Happy | REQ-DEP-004 | Given code is merged to `main`, When GitHub Actions runs, Then production deployment starts automatically. |
| TST-REQ-DEP-004-02 | Edge | REQ-DEP-004 | Given production deployment tests fail, When GitHub Actions runs, Then production deploy steps do not execute. |
| TST-REQ-DEP-004-03 | Focus | REQ-DEP-004 | Given code is merged to `main`, When the workflow is inspected, Then production deployment is selected after tests, migration safety, and ECR publish. |
| TST-REQ-DEP-004-04 | Focus | REQ-DEP-004 | Given operations runbook docs, When a bad deploy occurs, Then ECS rollback and RDS restore-point guidance are documented. |
| TST-REQ-DEP-005-01 | Happy | REQ-DEP-005 | Given CI is triggered, When workflow execution starts, Then tests run before build or deploy jobs. |
| TST-REQ-DEP-005-02 | Edge | REQ-DEP-005 | Given tests fail in CI, When workflow execution continues, Then container build and deploy jobs are blocked. |
| TST-REQ-DEP-005-03 | Focus | REQ-DEP-005 | Given the spec suite is ready for release review, When traceability verification scans spec tests, Then no pending red-phase placeholders remain. |
| TST-REQ-DEP-005-04 | Focus | REQ-DEP-005 | Given frontend code is present, When CI runs, Then npm install, typecheck, and auth-boundary checks run before build or deploy jobs. |
| TST-REQ-DEP-005-05 | Focus | REQ-DEP-005 | Given a migration is destructive or contract-phase, When CI evaluates migration safety, Then automatic deploy is rejected and an expand/contract split is required. |
| TST-REQ-DEP-005-06 | Release | REQ-DEP-005 | Given recurring-funding infrastructure is release-ready, When the deployment contract runs, Then CloudFormation validation, deploy-script shell syntax, environment-separated optional Broker secret references, and disabled zero funding defaults pass before deploy. |
| TST-REQ-DEP-006-01 | Happy | REQ-DEP-006 | Given tests pass, When deployment workflow runs, Then backend and frontend images are built and published to ECR before ECS deployment. |
| TST-REQ-DEP-006-02 | Edge | REQ-DEP-006 | Given ECR publish fails, When deployment workflow runs, Then ECS deployment is skipped and failure status is reported. |
| TST-REQ-DEP-006-03 | Focus | REQ-DEP-006 | Given tests and migration safety pass, When the workflow is inspected, Then backend and frontend images are pushed to ECR before ECS deployment. |
| TST-REQ-DEP-007-01 | Happy | REQ-DEP-007 | Given repo setup files are inspected, When `.env.example` files are validated, Then required local config keys are documented without secrets. |
| TST-REQ-DEP-007-02 | Edge | REQ-DEP-007 | Given `.env.example` contains a real-looking secret value, When secret scanning runs, Then validation fails. |
| TST-REQ-DEP-008-01 | Happy | REQ-DEP-008 | Given Codex web setup docs and scripts, When a developer follows setup, Then dependencies, tests, and safe dry-run config are available. |
| TST-REQ-DEP-008-02 | Edge | REQ-DEP-008 | Given setup runs without trading secrets, When dependency install and tests run, Then setup still succeeds with dry-run-safe defaults. |
| TST-REQ-DEP-008-03 | Focus | REQ-DEP-008 | Given Codex web setup docs, When a developer installs dependencies and runs tests, Then production trading secrets are not required. |
| TST-REQ-DEP-009-01 | Happy | REQ-DEP-009 | Given a Codex web environment without production trading secrets, When dependencies install, tests run, or code is inspected, Then those actions succeed. |
| TST-REQ-DEP-009-02 | Edge | REQ-DEP-009 | Given code tries to require production secrets during import or tests, When CI or Codex setup runs, Then the test fails. |
| TST-REQ-DEP-010-01 | Focus | REQ-DEP-010 | Given development and production deployments, When infrastructure and secret names are validated, Then resources, secrets, wallets, and config are separated by environment. |
| TST-REQ-DEP-011-01 | Regression | REQ-DEP-011 | Given the CloudFormation RDS resource, When infrastructure validation runs, Then the database uses gp3 storage instead of gp2 burst storage. |

### Observability and Audit Logging

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-OBS-001-01 | Happy | REQ-OBS-001 | Given system events across ingestion, scoring, strategy, risk, orders, exits, notifications, config, and deployment health, When logging runs, Then structured logs are emitted. |
| TST-REQ-OBS-001-02 | Edge | REQ-OBS-001 | Given a logging payload contains secrets, When structured logging runs, Then secrets are redacted before emission. |
| TST-REQ-OBS-002-01 | Happy | REQ-OBS-002 | Given AWS environment config, When app logs are emitted, Then logs are sent to CloudWatch. |
| TST-REQ-OBS-002-02 | Edge | REQ-OBS-002 | Given CloudWatch delivery fails, When app logs are emitted, Then local structured logs remain available and degraded status is recorded. |
| TST-REQ-OBS-003-01 | Happy | REQ-OBS-003 | Given a live order is refused, submitted, filled, canceled, or failed, When the order event is handled, Then an audit event is produced. |
| TST-REQ-OBS-003-02 | Edge | REQ-OBS-003 | Given audit event persistence fails for an order event, When the event is handled, Then failure is surfaced and not ignored. |
| TST-REQ-OBS-004-01 | Happy | REQ-OBS-004 | Given a dashboard user changes config, toggles live mode, or activates kill switch, When the action succeeds, Then an audit event is produced. |
| TST-REQ-OBS-004-02 | Edge | REQ-OBS-004 | Given a dashboard action is denied, When authorization fails, Then a security-relevant audit event is produced without applying the action. |
| TST-REQ-OBS-005-01 | Focus | REQ-OBS-005 | Given recent audit events and health indicators exist, When dashboard observability views render, Then recent events and health are visible. |
| TST-REQ-OBS-005-02 | Focus | REQ-OBS-005 | Given requirements, spec tests, implementation files, and design docs, When traceability verification runs, Then every requirement has at least one test and one implementation or approved design trace. |
| TST-REQ-OBS-006-01 | Focus | REQ-OBS-006 | Given a background worker fails, When worker supervision records the failure, Then dashboard health shows degraded status. |
| TST-REQ-OBS-006-02 | Edge | REQ-OBS-006 | Given one requirement has no matching test or implementation trace, When readiness verification receives the uncovered requirement, Then the result fails and identifies the missing coverage. |
| TST-REQ-OBS-006-03 | Focus | REQ-OBS-006 | Given audit, health, deployment, and live-trading safety checks, When release readiness is reviewed, Then each area is passing or explicitly deferred with a reason. |
| TST-REQ-OBS-006-04 | Release | REQ-OBS-006 | Given the recurring-funding change is ready, When release evidence is audited, Then its tracking issue links a branch rebased on current develop, the development and main promotion pull requests, both final GitHub Actions run URLs and statuses, and attached environment verification before issue closure. |

### Dashboard Information Architecture

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-UI-016-01 | Focus | REQ-UI-016 | Given the authenticated dashboard shell, When primary navigation renders, Then Overview, Activity, Performance, Settings, and Help remain visible, More is absent, `/dashboard/operations` remains directly reachable, and Activity and Settings both link to it. |
| TST-REQ-UI-017-01 | Focus | REQ-UI-017 | Given live-trade, attention, and all-clear data fixtures, When Overview derives state, Then exactly one data-driven state renders with the documented precedence and no manual selector. |
| TST-REQ-UI-018-01 | Focus | REQ-UI-018 | Given attention blockers and recommendations, When Overview renders, Then blockers are prioritized, no more than three recommendations appear, and other states show none. |
| TST-REQ-UI-019-01 | Focus | REQ-UI-019 | Given Overview data, When the page renders, Then it owns only current facts, latest result, and contextual links without detailed records, tables, forms, or help duplication. |
| TST-REQ-UI-020-01 | Focus | REQ-UI-020 | Given persisted or realtime operations data and degraded fixtures, When Activity renders, Then it shows the latest funnel, recent checks, update time, and explicit unavailable states without invented counts. |
| TST-REQ-UI-021-01 | Focus | REQ-UI-021 | Given venue-confirmed portfolio data, When Performance renders, Then it shows required metrics and by-market columns, excludes simulated and unfilled orders, and preserves unavailable money states. |
| TST-REQ-UI-022-01 | Focus | REQ-UI-022 | Given common and advanced settings, When Settings renders and saves, Then plain-language common controls, audited advanced persistence, emergency-stop link, and distinct live-money styling remain present. |
| TST-REQ-UI-023-01 | Focus | REQ-UI-023 | Given backend data is unavailable, When Help renders, Then the five documented process steps, common questions, and Overview link remain available. |
| TST-REQ-UI-024-01 | Focus | REQ-UI-024 | Given 390-pixel and desktop viewports plus keyboard and reduced-motion settings, When dashboard pages render, Then navigation is usable, focus is visible, status is not color-only, and page overflow and disallowed motion are absent. |
| TST-REQ-UI-025-01 | Focus | REQ-UI-025 | Given one upstream section fails after a valid snapshot, When redesigned pages render, Then valid data remains visible and one consolidated stale or unavailable message is shown. |
| TST-REQ-UI-026-01 | Focus | REQ-UI-026 | Given a recommendation and current config version, When apply and undo run, Then exact values require confirmation, both writes use the audited endpoint, a stale undo is rejected, and undo expires after the next mutation, navigation, or reload. |

### Recurring Funding and Direct Transfers

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-FND-001-01 | Happy | REQ-FND-001 | Given authenticated Alpaca and Polymarket US accounts, When portfolio reconciliation runs, Then documented deposit and withdrawal activity is retrieved with balances, positions, and fills. |
| TST-REQ-FND-001-02 | Edge | REQ-FND-001 | Given one venue funding-activity read fails, When reconciliation runs, Then prior confirmed funding rows remain, the account funding section is degraded, and other accounts continue. |
| TST-REQ-FND-001-03 | Contract | REQ-FND-001 | Given Alpaca CSD, CSW, supported TRANS, and ambiguous TRANS rows, When normalization runs, Then CSD and CSW are completed deposits and withdrawals, supported TRANS uses its documented direction, and ambiguous TRANS is skipped safely. |
| TST-REQ-FND-001-04 | Contract | REQ-FND-001 | Given Polymarket ACCOUNT_DEPOSIT, ACCOUNT_ADVANCED_DEPOSIT, ACCOUNT_WITHDRAWAL, and ambiguous TRANSFER activity, When normalization runs, Then documented deposit and withdrawal records are kept and ambiguous direction is skipped. |
| TST-REQ-FND-001-05 | Integration | REQ-FND-001 | Given one account activity source fails inside the runtime funding tick, When other accounts succeed, Then each successful account persists and reconciles independently and the failed account reports one safe error. |
| TST-REQ-FND-002-01 | Happy | REQ-FND-002 | Given venue funding activity, When normalization and persistence run, Then only environment, venue, providers, sanitized account reference, transaction ID, direction, amount, status, and timestamps are retained. |
| TST-REQ-FND-002-02 | Security | REQ-FND-002 | Given a venue payload contains credentials, account and routing numbers, relationship IDs, raw bank fields, or Plaid fields, When persistence, logging, and API serialization run, Then those fields are absent. |
| TST-REQ-FND-002-03 | Edge | REQ-FND-002 | Given an Alpaca CSD or CSW has a date without a timestamp, When normalized, Then `effective_at` is 09:00 America/New_York on that date and precision is marked date-only. |
| TST-REQ-FND-003-01 | Happy | REQ-FND-003 | Given OpenAI and Claude credentials resolve to one venue account and observe one transaction, When both upsert it, Then one cash-flow row contains both providers and one amount. |
| TST-REQ-FND-003-02 | Edge | REQ-FND-003 | Given an older venue update arrives after a newer or terminal cash-flow state, When upsert runs, Then status and effective fields do not regress. |
| TST-REQ-FND-003-03 | Edge | REQ-FND-003 | Given pagination repeats a venue transaction ID within or across pages, When sync runs, Then the duplicate-ID guard and database uniqueness retain one cash-flow row. |
| TST-REQ-FND-004-01 | Focus | REQ-FND-004 | Given old cash-flow and occurrence rows and no archive policy, When routine cleanup or migrations run, Then funding history is retained and no dashboard hard-delete path exists. |
| TST-REQ-FND-004-02 | Performance | REQ-FND-004 | Given more funding activity than one tick budget, When sync runs, Then current head and historical backfill each stop after 20 pages and persist a continuation cursor. |
| TST-REQ-FND-004-03 | Recovery | REQ-FND-004 | Given a stored head transaction and backfill cursor, When later ticks run, Then current head sync reaches the prior head before advancing coverage and historical backfill resumes without blocking current activity. |
| TST-REQ-FND-004-04 | History | REQ-FND-004 | Given funding rows older than the default API window, When an authenticated user pages or selects an older interval, Then retained history remains queryable without a hard-delete path. |
| TST-REQ-FND-005-01 | Happy | REQ-FND-005 | Given enabled weekly and monthly schedules, When 09:00 America/New_York becomes due, Then one occurrence per provider schedule is materialized. |
| TST-REQ-FND-005-02 | Edge | REQ-FND-005 | Given a weekend, federal holiday, daylight-saving boundary, or day 31 in a shorter month, When due time is calculated, Then the documented next-business-day and local-time rule is used. |
| TST-REQ-FND-005-03 | Recovery | REQ-FND-005 | Given an established schedule has a last materialized occurrence and the worker misses later due times, When it restarts, Then every due time after that occurrence through now materializes once. |
| TST-REQ-FND-005-04 | Edge | REQ-FND-005 | Given a newly enabled schedule has no occurrence history, When materialization first runs, Then only its most recent due occurrence is created without unlimited historical backfill. |
| TST-REQ-FND-006-01 | Happy | REQ-FND-006 | Given a fresh confirmed buying power below target, When low-balance evaluation runs, Then the expected gap is `max(0, target - buying power)` and one episode is created. |
| TST-REQ-FND-006-02 | Edge | REQ-FND-006 | Given the low-balance gap exceeds positive schedule, per-transfer, or remaining monthly caps, When a direct claim runs, Then the submitted amount is the minimum positive cap and both expected and submitted amounts remain visible. |
| TST-REQ-FND-006-03 | Recovery | REQ-FND-006 | Given balance remains below target across refreshes, When evaluation repeats, Then no second episode is created until a fresh at-or-above-target snapshot rearms the schedule. |
| TST-REQ-FND-006-04 | Safety | REQ-FND-006 | Given a failed, stale, or missing confirmed portfolio snapshot, When low-balance evaluation runs, Then no new low-balance episode or transfer claim is created. |
| TST-REQ-FND-007-01 | Happy | REQ-FND-007 | Given the same schedule, account, provider, adjusted due time, direction, and mode, When occurrence materialization runs twice, Then one deterministic persisted occurrence is returned. |
| TST-REQ-FND-007-02 | Concurrency | REQ-FND-007 | Given concurrent workers and one due occurrence, When both materialize under database constraints, Then one row exists and the funding run lock prevents overlapping work. |
| TST-REQ-FND-007-03 | Integration | REQ-FND-007 | Given another task owns the session funding lock, When a runtime tick starts, Then it skips; when an acquired tick succeeds or fails, Then `finally` releases the lock without holding a transaction across venue calls. |
| TST-REQ-FND-007-04 | Integration | REQ-FND-007 | Given the latest portfolio refresh fails, When fixed weekly or monthly schedules are due, Then they still materialize while low-balance schedules remain gated. |
| TST-REQ-FND-007-05 | Migration | REQ-FND-007 | Given the funding migration plan, When schema contracts are inspected, Then cash-flow, occurrence, sync-state, and alert-outbox tables include required foreign keys, checks, indexes, unique keys, and the partial pending-slot constraint. |
| TST-REQ-FND-008-01 | Happy | REQ-FND-008 | Given one completed cash flow with matching account, direction, effective window, and amount within `0.01`, When reconciliation runs, Then it matches one occurrence one-to-one. |
| TST-REQ-FND-008-02 | Edge | REQ-FND-008 | Given zero or multiple same-amount candidates, a wrong direction, an out-of-window time, or amount outside tolerance, When reconciliation runs, Then it leaves the occurrence unmatched. |
| TST-REQ-FND-008-03 | Safety | REQ-FND-008 | Given the four-business-day deadline passed but activity coverage has not advanced past it, When reconciliation runs, Then missing state is delayed until a successful covered sync. |
| TST-REQ-FND-008-04 | Concurrency | REQ-FND-008 | Given two workers race to match or transition the same occurrence, When compare-and-set updates run, Then one cash flow wins, terminal state does not regress, and no matched cash flow is reused. |
| TST-REQ-FND-009-01 | Happy | REQ-FND-009 | Given an occurrence first becomes missing, rejected, returned, or failed, When its state commits, Then one unique failure outbox event is created before SES delivery. |
| TST-REQ-FND-009-02 | Edge | REQ-FND-009 | Given the same transition is evaluated again or SES delivery is uncertain, When outbox delivery retries, Then no second logical alert is created. |
| TST-REQ-FND-009-03 | Recovery | REQ-FND-009 | Given a missing occurrence later matches a completed cash flow, When reconciliation runs, Then one recovery outbox event is created. |
| TST-REQ-FND-009-04 | Delivery | REQ-FND-009 | Given SES delivery succeeds or fails, When the outbox worker records the result, Then sent or failed state, provider ID or safe error, capped attempt count, and bounded backoff are persisted and heartbeat metadata reports safe counts and coverage. |
| TST-REQ-FND-010-01 | Happy | REQ-FND-010 | Given funding rows and occurrences, When authenticated Performance loads, Then it shows safe account label, provider, venue, venue status, matched or missing state, direction, amount, and timestamps. |
| TST-REQ-FND-010-02 | Security | REQ-FND-010 | Given funding API and UI responses, When schemas and rendered text are inspected, Then raw account references, Broker account and relationship IDs, credentials, request fingerprints, and raw payloads are absent. |
| TST-REQ-FND-010-03 | API | REQ-FND-010 | Given more cash flows and occurrences than one API page, When funding history is requested, Then independent stable opaque cursors return descending non-overlapping pages. |
| TST-REQ-FND-010-04 | API | REQ-FND-010 | Given unauthenticated, unallowlisted, invalid interval or cursor, and persistence-unavailable requests, When the funding endpoint is called, Then it returns the existing 401, 403, 422, or 503 envelope. |
| TST-REQ-FND-010-05 | API | REQ-FND-010 | Given eligible and ineligible account boundary snapshots, When funding performance is requested, Then per-account results show each status and aggregate results include only eligible accounts. |
| TST-REQ-FND-010-06 | UI | REQ-FND-010 | Given capped and alerted occurrences, When Performance renders, Then expected and submitted amounts, alert state, safe account label, and venue cash-flow status are visible. |
| TST-REQ-FND-010-08 | Accessibility | REQ-FND-010 | Given funding views at 390 pixels and desktop with keyboard and reduced-motion preferences, When they render, Then controls remain reachable, status is not color-only, page overflow is absent, and disallowed motion is absent. |
| TST-REQ-FND-011-01 | Happy | REQ-FND-011 | Given beginning value 1000, ending value 1200, completed deposits 300, and withdrawals 50, When performance is calculated, Then adjusted trading P&L is `-50`. |
| TST-REQ-FND-011-02 | Edge | REQ-FND-011 | Given pending, unknown, rejected, returned, failed, or canceled cash flows, When performance is calculated, Then they do not change adjusted trading P&L. |
| TST-REQ-FND-012-01 | Happy | REQ-FND-012 | Given a four-day period, BMV 1000, EMV 1300, a 200 deposit after day one, and a 40 withdrawal after day three, When Modified Dietz is calculated, Then numerator is 140, denominator is 1140, and fixed-precision return is `0.12280702`. |
| TST-REQ-FND-012-02 | Edge | REQ-FND-012 | Given a zero or negative weighted denominator or stale or missing boundary snapshot, When adjusted performance is requested, Then both percentage return and boundary-dependent adjusted performance are unavailable with a reason. |
| TST-REQ-FND-012-03 | API | REQ-FND-012 | Given requested interval boundaries and snapshots outside two refresh intervals, When the funding API selects valuations, Then it reports stale boundary timestamps and does not mix them with requested-period cash-flow weights. |
| TST-REQ-FND-013-01 | Happy | REQ-FND-013 | Given entitled Broker credentials, a matching Broker account, an approved ACH relationship, and a claimed occurrence, When direct submission runs, Then it calls `/v1/accounts/{account_id}/transfers` once with incoming ACH, exact claimed amount, and the secret-resolved relationship. |
| TST-REQ-FND-013-02 | Security | REQ-FND-013 | Given a successful direct request, When persistence and logs are inspected, Then exact Broker account and relationship IDs and request bodies are absent. |
| TST-REQ-FND-013-03 | Boundary | REQ-FND-013 | Given no Plaid integration or token, When an existing venue-managed ACH relationship is configured through secrets, Then direct readiness does not require Plaid. |
| TST-REQ-FND-013-04 | Infrastructure | REQ-FND-013 | Given development and production CloudFormation, When optional Broker secret references are inspected, Then API, account, and relationship refs are environment-separated, values are not required, and no raw bank or Plaid resource exists. |
| TST-REQ-FND-013-05 | UI | REQ-FND-013 | Given funding settings guidance, When it renders, Then it states that bank setup is venue-managed, existing ACH relationships are provisioned outside the dashboard, and Plaid is not required. |
| TST-REQ-FND-014-01 | Safe default | REQ-FND-014 | Given bootstrap, development, and production defaults, When funding config loads, Then direct transfers are disabled and both limits are `0.00`. |
| TST-REQ-FND-014-02 | Edge | REQ-FND-014 | Given direct disabled, either zero limit, a non-positive amount, or direct withdrawal, When submission is evaluated, Then a refusal is persisted and the adapter has zero calls. |
| TST-REQ-FND-014-03 | Edge | REQ-FND-014 | Given missing Broker API key, secret, account ID, relationship ID, or mismatched provider/Broker account, When submission is evaluated, Then a safe refusal is persisted before the adapter call. |
| TST-REQ-FND-014-04 | Edge | REQ-FND-014 | Given the originating schedule is missing, disabled, changed, owned by another config, or resolves to another account, When claim revalidation runs, Then it refuses before the adapter call. |
| TST-REQ-FND-014-05 | Failure | REQ-FND-014 | Given persistence, lock, or compare-and-set claim is unavailable, When submission is evaluated, Then a safe refusal or degraded result is returned with zero adapter calls and no persisted-refusal assertion. |
| TST-REQ-FND-014-06 | Infrastructure | REQ-FND-014 | Given Broker secret values are absent, When local or deployed startup and health run, Then the app remains available and direct readiness stays blocked with disabled zero defaults. |
| TST-REQ-FND-014-07 | Release | REQ-FND-014 | Given development or production release verification, When authenticated funding config and CloudWatch adapter events are read, Then direct mode is disabled, both limits are `0.00`, and Broker POST count for the release window is zero. |
| TST-REQ-FND-014-08 | Deployment | REQ-FND-014 | Given funding infrastructure changes, When release validation runs, Then CloudFormation template validation, deployment-script shell syntax, environment isolation, optional-secret behavior, and disabled zero defaults pass before build or deploy. |
| TST-REQ-FND-015-01 | Happy | REQ-FND-015 | Given a positive direct amount within positive per-transfer and remaining monthly limits and no pending transfer, When claim runs, Then the amount is reserved and remains eligible. |
| TST-REQ-FND-015-02 | Boundary | REQ-FND-015 | Given current-month reserved, submitted, unknown, and matched direct amounts, When capacity is checked by `reserved_at` in America/New_York, Then all count and released terminal reservations do not. |
| TST-REQ-FND-015-03 | Edge | REQ-FND-015 | Given a fixed weekly or monthly amount exceeds a limit or another reserved, submitted, or unknown transfer exists, When claim runs, Then the full request is refused and no partial fixed transfer is sent. |
| TST-REQ-FND-015-04 | Boundary | REQ-FND-015 | Given the America/New_York calendar month rolls over, When capacity is recalculated, Then prior-month reservations do not consume the new month's limit. |
| TST-REQ-FND-016-01 | Safety | REQ-FND-016 | Given two claim attempts for one occurrence, When the conditional claim commits `post_attempted_at`, Then at most one process can call the Broker adapter. |
| TST-REQ-FND-016-02 | Recovery | REQ-FND-016 | Given a crash after the durable claim and before response persistence, When startup runs, Then reserved moves to unknown and reconciliation occurs without another POST. |
| TST-REQ-FND-016-03 | Edge | REQ-FND-016 | Given an unknown transfer without provider ID, When the account transfer list has exactly one direction, amount, relationship, and time-window candidate it matches; zero or multiple candidates remain unknown. |
| TST-REQ-FND-016-04 | Recovery | REQ-FND-016 | Given the Broker POST times out or returns an ambiguous 5xx, When response handling and later ticks run, Then status becomes unknown, the pending slot and reservation remain, and no later POST occurs. |
| TST-REQ-FND-017-01 | Edge | REQ-FND-017 | Given Alpaca rejects, returns, or fails a direct transfer, When response handling runs, Then terminal status is persisted, the failed reservation is released, and one alert is enqueued. |
| TST-REQ-FND-017-02 | Safety | REQ-FND-017 | Given a terminal direct occurrence is seen on a later tick, When submission runs, Then it requires a new authorized occurrence and never auto-retries. |
| TST-REQ-FND-018-01 | Safety | REQ-FND-018 | Given the global kill switch or funding emergency stop becomes active before claim, When submission is evaluated, Then it refuses before the adapter call. |
| TST-REQ-FND-018-02 | Happy | REQ-FND-018 | Given either stop is active, When the funding runtime tick runs, Then read-only activity sync, occurrence matching, missing detection with coverage, and recovery alerts continue. |
| TST-REQ-FND-019-01 | Happy | REQ-FND-019 | Given an authorized operator changes funding settings through one complete-object patch, When save succeeds, Then one owner-specific version and audit record contain username, complete old and new values, environment, timestamp, and IP address. |
| TST-REQ-FND-019-02 | Edge | REQ-FND-019 | Given an invalid schedule, partial funding object, stale expected version, or unauthorized actor, When save is attempted, Then the entire update is rejected without partial funding state. |
| TST-REQ-FND-019-03 | UI | REQ-FND-019 | Given Settings edits a funding schedule or control, When it saves, Then it sends one complete `replace funding` patch with reason and refreshes the new config version. |
| TST-REQ-FND-019-04 | Runbook | REQ-FND-019 | Given funding operations and rollback docs, When validated, Then they cover venue-managed setup, optional Broker entitlement and secrets, schedules, direct enable/disable, emergency stop, unknown review, alert recovery, rollback, and no real-transfer smoke test. |
| TST-REQ-FND-019-05 | UI | REQ-FND-019 | Given weekly, monthly, and low-balance schedules, When parameterized Settings actions add, edit, enable, disable, or remove each schedule, Then one complete audited funding-object save is sent and the new version is loaded. |
| TST-REQ-FND-020-01 | Safety | REQ-FND-020 | Given Polymarket funding activity and an enabled observe schedule, When reconciliation runs, Then reads and matching work without any funding-write call. |
| TST-REQ-FND-020-02 | Edge | REQ-FND-020 | Given direct Polymarket mode or a Polymarket funding-write resource or permission, When config and deployment validation run, Then validation fails. |
| TST-REQ-FND-020-03 | Infrastructure | REQ-FND-020 | Given CloudFormation, IAM, adapters, and runbooks, When the release gate scans them, Then no Polymarket funding-write resource, permission, endpoint, or Plaid integration exists. |
| TST-REQ-FND-020-04 | UI | REQ-FND-020 | Given a Polymarket funding schedule, When Settings renders, Then it labels the schedule observe-only and offers no direct-transfer control for that venue. |

## Traceability Matrix

| Requirement | Test IDs |
|-------------|----------|
| REQ-VEN-001 | TST-REQ-VEN-001-01, TST-REQ-VEN-001-02 |
| REQ-VEN-002 | TST-REQ-VEN-002-01, TST-REQ-VEN-002-02 |
| REQ-VEN-003 | TST-REQ-VEN-003-01, TST-REQ-VEN-003-02 |
| REQ-VEN-004 | TST-REQ-VEN-004-01, TST-REQ-VEN-004-02, TST-REQ-VEN-004-03 |
| REQ-VEN-005 | TST-REQ-VEN-005-01, TST-REQ-VEN-005-02, TST-REQ-VEN-005-03 |
| REQ-VEN-006 | TST-REQ-VEN-006-01 |
| REQ-ALP-001 | TST-REQ-ALP-001-01, TST-REQ-ALP-001-02 |
| REQ-ALP-002 | TST-REQ-ALP-002-01, TST-REQ-ALP-002-02 |
| REQ-ALP-003 | TST-REQ-ALP-003-01, TST-REQ-ALP-003-02, TST-REQ-ALP-003-03 |
| REQ-ALP-004 | TST-REQ-ALP-004-01, TST-REQ-ALP-004-02 |
| REQ-ALP-005 | TST-REQ-ALP-005-01, TST-REQ-ALP-005-02 |
| REQ-ALP-006 | TST-REQ-ALP-006-01, TST-REQ-ALP-006-02 |
| REQ-ALP-007 | TST-REQ-ALP-007-01, TST-REQ-ALP-007-02 |
| REQ-ALP-008 | TST-REQ-ALP-008-01, TST-REQ-ALP-008-02 |
| REQ-ALP-009 | TST-REQ-ALP-009-01, TST-REQ-ALP-009-02 |
| REQ-ALP-010 | TST-REQ-ALP-010-01, TST-REQ-ALP-010-02 |
| REQ-ALP-011 | TST-REQ-ALP-011-01, TST-REQ-ALP-011-02 |
| REQ-ALP-012 | TST-REQ-ALP-012-01, TST-REQ-ALP-012-02 |
| REQ-ALP-013 | TST-REQ-ALP-013-01, TST-REQ-ALP-013-02 |
| REQ-ALP-014 | TST-REQ-ALP-014-01, TST-REQ-ALP-014-02 |
| REQ-ALP-015 | TST-REQ-ALP-015-01, TST-REQ-ALP-015-02 |
| REQ-ALP-016 | TST-REQ-ALP-016-01, TST-REQ-ALP-016-02 |
| REQ-ALP-017 | TST-REQ-ALP-017-01, TST-REQ-ALP-017-02, TST-REQ-ALP-017-03 |
| REQ-ALP-018 | TST-REQ-ALP-018-01, TST-REQ-ALP-018-02 |
| REQ-ALP-019 | TST-REQ-ALP-019-01, TST-REQ-ALP-019-02 |
| REQ-ALP-020 | TST-REQ-ALP-020-01, TST-REQ-ALP-020-02 |
| REQ-ALP-021 | TST-REQ-ALP-021-01, TST-REQ-ALP-021-02 |
| REQ-ALP-022 | TST-REQ-ALP-022-01, TST-REQ-ALP-022-02 |
| REQ-ALP-023 | TST-REQ-ALP-023-01, TST-REQ-ALP-023-02 |
| REQ-ALP-024 | TST-REQ-ALP-024-01, TST-REQ-ALP-024-02 |
| REQ-ALP-025 | TST-REQ-ALP-025-01, TST-REQ-ALP-025-02 |
| REQ-ALP-026 | TST-REQ-ALP-026-01, TST-REQ-ALP-026-02 |
| REQ-DAT-001 | TST-REQ-DAT-001-01, TST-REQ-DAT-001-02 |
| REQ-DAT-002 | TST-REQ-DAT-002-01, TST-REQ-DAT-002-02 |
| REQ-DAT-003 | TST-REQ-DAT-003-01, TST-REQ-DAT-003-02 |
| REQ-DAT-004 | TST-REQ-DAT-004-01, TST-REQ-DAT-004-02 |
| REQ-DAT-005 | TST-REQ-DAT-005-01, TST-REQ-DAT-005-02, TST-REQ-DAT-005-03 |
| REQ-DAT-006 | TST-REQ-DAT-006-01, TST-REQ-DAT-006-02 |
| REQ-DAT-007 | TST-REQ-DAT-007-01, TST-REQ-DAT-007-02 |
| REQ-DAT-008 | TST-REQ-DAT-008-01 |
| REQ-DB-001 | TST-REQ-DB-001-01, TST-REQ-DB-001-02 |
| REQ-DB-002 | TST-REQ-DB-002-01, TST-REQ-DB-002-02 |
| REQ-DB-003 | TST-REQ-DB-003-01, TST-REQ-DB-003-02 |
| REQ-DB-004 | TST-REQ-DB-004-01, TST-REQ-DB-004-02 |
| REQ-DB-005 | TST-REQ-DB-005-01, TST-REQ-DB-005-02 |
| REQ-DB-006 | TST-REQ-DB-006-01 |
| REQ-DB-007 | TST-REQ-DB-007-01, TST-REQ-DB-007-02, TST-REQ-DB-007-03 |
| REQ-DB-008 | TST-REQ-DB-008-01, TST-REQ-DB-008-02 |
| REQ-DB-009 | TST-REQ-DB-009-01, TST-REQ-DB-009-02 |
| REQ-DB-010 | TST-REQ-DB-010-01, TST-REQ-DB-010-02 |
| REQ-WAL-001 | TST-REQ-WAL-001-01, TST-REQ-WAL-001-02, TST-REQ-EXE-016-07, TST-REQ-EXE-016-08 |
| REQ-WAL-002 | TST-REQ-WAL-002-01, TST-REQ-WAL-002-02 |
| REQ-WAL-003 | TST-REQ-WAL-003-01, TST-REQ-WAL-003-02, TST-REQ-WAL-003-03, TST-REQ-WAL-003-04 |
| REQ-WAL-004 | TST-REQ-WAL-004-01, TST-REQ-WAL-004-02 |
| REQ-WAL-005 | TST-REQ-WAL-005-01, TST-REQ-WAL-005-02 |
| REQ-WAL-006 | TST-REQ-WAL-006-01, TST-REQ-WAL-006-02 |
| REQ-WAL-007 | TST-REQ-WAL-007-01 |
| REQ-FND-001 | TST-REQ-FND-001-01, TST-REQ-FND-001-02, TST-REQ-FND-001-03, TST-REQ-FND-001-04, TST-REQ-FND-001-05 |
| REQ-FND-002 | TST-REQ-FND-002-01, TST-REQ-FND-002-02, TST-REQ-FND-002-03 |
| REQ-FND-003 | TST-REQ-FND-003-01, TST-REQ-FND-003-02, TST-REQ-FND-003-03 |
| REQ-FND-004 | TST-REQ-FND-004-01, TST-REQ-FND-004-02, TST-REQ-FND-004-03, TST-REQ-FND-004-04 |
| REQ-FND-005 | TST-REQ-FND-005-01, TST-REQ-FND-005-02, TST-REQ-FND-005-03, TST-REQ-FND-005-04 |
| REQ-FND-006 | TST-REQ-FND-006-01, TST-REQ-FND-006-02, TST-REQ-FND-006-03, TST-REQ-FND-006-04 |
| REQ-FND-007 | TST-REQ-FND-007-01, TST-REQ-FND-007-02, TST-REQ-FND-007-03, TST-REQ-FND-007-04, TST-REQ-FND-007-05 |
| REQ-FND-008 | TST-REQ-FND-008-01, TST-REQ-FND-008-02, TST-REQ-FND-008-03, TST-REQ-FND-008-04 |
| REQ-FND-009 | TST-REQ-FND-009-01, TST-REQ-FND-009-02, TST-REQ-FND-009-03, TST-REQ-FND-009-04 |
| REQ-FND-010 | TST-REQ-FND-010-01, TST-REQ-FND-010-02, TST-REQ-FND-010-03, TST-REQ-FND-010-04, TST-REQ-FND-010-05, TST-REQ-FND-010-06, TST-REQ-FND-010-08 |
| REQ-FND-011 | TST-REQ-FND-011-01, TST-REQ-FND-011-02 |
| REQ-FND-012 | TST-REQ-FND-012-01, TST-REQ-FND-012-02, TST-REQ-FND-012-03 |
| REQ-FND-013 | TST-REQ-FND-013-01, TST-REQ-FND-013-02, TST-REQ-FND-013-03, TST-REQ-FND-013-04, TST-REQ-FND-013-05 |
| REQ-FND-014 | TST-REQ-FND-014-01, TST-REQ-FND-014-02, TST-REQ-FND-014-03, TST-REQ-FND-014-04, TST-REQ-FND-014-05, TST-REQ-FND-014-06, TST-REQ-FND-014-07, TST-REQ-FND-014-08 |
| REQ-FND-015 | TST-REQ-FND-015-01, TST-REQ-FND-015-02, TST-REQ-FND-015-03, TST-REQ-FND-015-04 |
| REQ-FND-016 | TST-REQ-FND-016-01, TST-REQ-FND-016-02, TST-REQ-FND-016-03, TST-REQ-FND-016-04 |
| REQ-FND-017 | TST-REQ-FND-017-01, TST-REQ-FND-017-02 |
| REQ-FND-018 | TST-REQ-FND-018-01, TST-REQ-FND-018-02 |
| REQ-FND-019 | TST-REQ-FND-019-01, TST-REQ-FND-019-02, TST-REQ-FND-019-03, TST-REQ-FND-019-04, TST-REQ-FND-019-05 |
| REQ-FND-020 | TST-REQ-FND-020-01, TST-REQ-FND-020-02, TST-REQ-FND-020-03, TST-REQ-FND-020-04 |
| REQ-LLM-001 | TST-REQ-LLM-001-01, TST-REQ-LLM-001-02, TST-REQ-LLM-001-03 |
| REQ-LLM-002 | TST-REQ-LLM-002-01, TST-REQ-LLM-002-02, TST-REQ-LLM-002-03 |
| REQ-LLM-003 | TST-REQ-LLM-003-01, TST-REQ-LLM-003-02 |
| REQ-LLM-004 | TST-REQ-LLM-004-01, TST-REQ-LLM-004-02, TST-REQ-LLM-004-03 |
| REQ-LLM-005 | TST-REQ-LLM-005-01, TST-REQ-LLM-005-02 |
| REQ-LLM-006 | TST-REQ-LLM-006-01 |
| REQ-LLM-007 | TST-REQ-LLM-007-01 |
| REQ-STR-001 | TST-REQ-STR-001-01, TST-REQ-STR-001-02 |
| REQ-STR-002 | TST-REQ-STR-002-01, TST-REQ-STR-002-02 |
| REQ-STR-003 | TST-REQ-STR-003-01, TST-REQ-STR-003-02 |
| REQ-STR-004 | TST-REQ-STR-004-01, TST-REQ-STR-004-02 |
| REQ-STR-005 | TST-REQ-STR-005-01, TST-REQ-STR-005-02 |
| REQ-STR-006 | TST-REQ-STR-006-01, TST-REQ-STR-006-02 |
| REQ-STR-007 | TST-REQ-STR-007-01, TST-REQ-STR-007-02 |
| REQ-STR-008 | TST-REQ-STR-008-01, TST-REQ-STR-008-02 |
| REQ-STR-009 | TST-REQ-STR-009-01 |
| REQ-EXE-001 | TST-REQ-EXE-001-01, TST-REQ-EXE-001-02 |
| REQ-EXE-002 | TST-REQ-EXE-002-01, TST-REQ-EXE-002-02 |
| REQ-EXE-003 | TST-REQ-EXE-003-01, TST-REQ-EXE-003-02 |
| REQ-EXE-004 | TST-REQ-EXE-004-01, TST-REQ-EXE-004-02 |
| REQ-EXE-005 | TST-REQ-EXE-005-01, TST-REQ-EXE-005-02 |
| REQ-EXE-006 | TST-REQ-EXE-006-01, TST-REQ-EXE-006-02 |
| REQ-EXE-007 | TST-REQ-EXE-007-01, TST-REQ-EXE-007-02 |
| REQ-EXE-008 | TST-REQ-EXE-008-01, TST-REQ-EXE-008-02 |
| REQ-EXE-009 | TST-REQ-EXE-009-01, TST-REQ-EXE-009-02 |
| REQ-EXE-010 | TST-REQ-EXE-010-01, TST-REQ-EXE-010-02 |
| REQ-EXE-011 | TST-REQ-EXE-011-01, TST-REQ-EXE-011-02 |
| REQ-EXE-012 | TST-REQ-EXE-012-01, TST-REQ-EXE-012-02 |
| REQ-EXE-013 | TST-REQ-EXE-013-01, TST-REQ-EXE-013-02 |
| REQ-EXE-014 | TST-REQ-EXE-014-01, TST-REQ-EXE-014-02, TST-REQ-EXE-014-03 |
| REQ-EXE-015 | TST-REQ-EXE-015-01, TST-REQ-EXE-015-02, TST-REQ-EXE-015-03 |
| REQ-EXE-016 | TST-REQ-EXE-016-01, TST-REQ-EXE-016-02, TST-REQ-EXE-016-03, TST-REQ-EXE-016-07, TST-REQ-EXE-016-08, TST-REQ-EXE-016-11, TST-REQ-EXE-016-12 |
| REQ-EXE-017 | TST-REQ-EXE-017-01, TST-REQ-EXE-017-02, TST-REQ-EXE-017-03 |
| REQ-EXT-001 | TST-REQ-EXT-001-01, TST-REQ-EXT-001-02 |
| REQ-EXT-002 | TST-REQ-EXT-002-01, TST-REQ-EXT-002-02 |
| REQ-EXT-003 | TST-REQ-EXT-003-01, TST-REQ-EXT-003-02 |
| REQ-EXT-004 | TST-REQ-EXT-004-01, TST-REQ-EXT-004-02 |
| REQ-EXT-005 | TST-REQ-EXT-005-01, TST-REQ-EXT-005-02 |
| REQ-EXT-006 | TST-REQ-EXT-006-01, TST-REQ-EXT-006-02 |
| REQ-UI-001 | TST-REQ-UI-001-01, TST-REQ-UI-001-02, TST-REQ-UI-001-03, TST-REQ-UI-001-04 |
| REQ-UI-002 | TST-REQ-UI-002-01, TST-REQ-UI-002-02, TST-REQ-UI-002-03 |
| REQ-UI-003 | TST-REQ-UI-003-01, TST-REQ-UI-003-02, TST-REQ-UI-003-03, TST-REQ-UI-003-04 |
| REQ-UI-004 | TST-REQ-UI-004-01, TST-REQ-UI-004-02, TST-REQ-UI-004-03, TST-REQ-UI-004-04, TST-REQ-UI-004-05, TST-REQ-UI-004-06 |
| REQ-UI-005 | TST-REQ-UI-005-01, TST-REQ-UI-005-02, TST-REQ-UI-005-03 |
| REQ-UI-006 | TST-REQ-UI-006-01, TST-REQ-UI-006-02, TST-REQ-UI-006-03, TST-REQ-UI-006-04 |
| REQ-UI-007 | TST-REQ-UI-007-01, TST-REQ-UI-007-02, TST-REQ-UI-007-03, TST-REQ-UI-007-04, TST-REQ-UI-007-05 |
| REQ-UI-008 | TST-REQ-UI-008-01, TST-REQ-UI-008-02, TST-REQ-UI-008-03 |
| REQ-UI-009 | TST-REQ-UI-009-01, TST-REQ-UI-009-02 |
| REQ-UI-010 | TST-REQ-UI-010-01, TST-REQ-UI-010-02 |
| REQ-UI-011 | TST-REQ-UI-011-01, TST-REQ-UI-011-02, TST-REQ-UI-011-03 |
| REQ-UI-012 | TST-REQ-UI-012-01, TST-REQ-UI-012-02 |
| REQ-UI-013 | TST-REQ-UI-013-01, TST-REQ-UI-013-02, TST-REQ-UI-013-03, TST-REQ-UI-013-04, TST-REQ-UI-013-05, TST-REQ-UI-013-06, TST-REQ-UI-013-07, TST-REQ-UI-013-08 |
| REQ-UI-014 | TST-REQ-UI-014-01, TST-REQ-UI-014-02 |
| REQ-UI-015 | TST-REQ-UI-015-01, TST-REQ-UI-015-02 |
| REQ-UI-016 | TST-REQ-UI-016-01 |
| REQ-UI-017 | TST-REQ-UI-017-01 |
| REQ-UI-018 | TST-REQ-UI-018-01 |
| REQ-UI-019 | TST-REQ-UI-019-01 |
| REQ-UI-020 | TST-REQ-UI-020-01 |
| REQ-UI-021 | TST-REQ-UI-021-01 |
| REQ-UI-022 | TST-REQ-UI-022-01 |
| REQ-UI-023 | TST-REQ-UI-023-01 |
| REQ-UI-024 | TST-REQ-UI-024-01 |
| REQ-UI-025 | TST-REQ-UI-025-01 |
| REQ-UI-026 | TST-REQ-UI-026-01 |
| REQ-CMP-001 | TST-REQ-CMP-001-01, TST-REQ-CMP-001-02 |
| REQ-CMP-002 | TST-REQ-CMP-002-01, TST-REQ-CMP-002-02 |
| REQ-CMP-003 | TST-REQ-CMP-003-01, TST-REQ-CMP-003-02 |
| REQ-CMP-004 | TST-REQ-CMP-004-01 |
| REQ-CMP-005 | TST-REQ-CMP-005-01, TST-REQ-CMP-005-02, TST-REQ-CMP-005-03 |
| REQ-NOT-001 | TST-REQ-NOT-001-01, TST-REQ-NOT-001-02, TST-REQ-NOT-001-03 |
| REQ-NOT-002 | TST-REQ-NOT-002-01, TST-REQ-NOT-002-02 |
| REQ-NOT-003 | TST-REQ-NOT-003-01, TST-REQ-NOT-003-02, TST-REQ-NOT-003-03 |
| REQ-NOT-004 | TST-REQ-NOT-004-01, TST-REQ-NOT-004-02 |
| REQ-NOT-005 | TST-REQ-NOT-005-01, TST-REQ-NOT-005-02 |
| REQ-NOT-006 | TST-REQ-NOT-006-01, TST-REQ-NOT-006-02 |
| REQ-NOT-007 | TST-REQ-NOT-007-01, TST-REQ-NOT-007-02 |
| REQ-DEP-001 | TST-REQ-DEP-001-01, TST-REQ-DEP-001-02, TST-REQ-DEP-001-03, TST-REQ-DEP-001-04 |
| REQ-DEP-002 | TST-REQ-DEP-002-01, TST-REQ-DEP-002-02, TST-REQ-DEP-002-03, TST-REQ-DEP-002-04 |
| REQ-DEP-003 | TST-REQ-DEP-003-01, TST-REQ-DEP-003-02, TST-REQ-DEP-003-03 |
| REQ-DEP-004 | TST-REQ-DEP-004-01, TST-REQ-DEP-004-02, TST-REQ-DEP-004-03, TST-REQ-DEP-004-04 |
| REQ-DEP-005 | TST-REQ-DEP-005-01, TST-REQ-DEP-005-02, TST-REQ-DEP-005-03, TST-REQ-DEP-005-04, TST-REQ-DEP-005-05, TST-REQ-DEP-005-06 |
| REQ-DEP-006 | TST-REQ-DEP-006-01, TST-REQ-DEP-006-02, TST-REQ-DEP-006-03 |
| REQ-DEP-007 | TST-REQ-DEP-007-01, TST-REQ-DEP-007-02 |
| REQ-DEP-008 | TST-REQ-DEP-008-01, TST-REQ-DEP-008-02, TST-REQ-DEP-008-03 |
| REQ-DEP-009 | TST-REQ-DEP-009-01, TST-REQ-DEP-009-02 |
| REQ-DEP-010 | TST-REQ-DEP-010-01 |
| REQ-DEP-011 | TST-REQ-DEP-011-01 |
| REQ-OBS-001 | TST-REQ-OBS-001-01, TST-REQ-OBS-001-02 |
| REQ-OBS-002 | TST-REQ-OBS-002-01, TST-REQ-OBS-002-02 |
| REQ-OBS-003 | TST-REQ-OBS-003-01, TST-REQ-OBS-003-02 |
| REQ-OBS-004 | TST-REQ-OBS-004-01, TST-REQ-OBS-004-02 |
| REQ-OBS-005 | TST-REQ-OBS-005-01, TST-REQ-OBS-005-02 |
| REQ-OBS-006 | TST-REQ-OBS-006-01, TST-REQ-OBS-006-02, TST-REQ-OBS-006-03, TST-REQ-OBS-006-04 |
