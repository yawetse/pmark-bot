# codex-poly-bot Test Specification

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.0  
**Date:** 2026-04-25  
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
| P0 | 105 | 210 |
| P1 | 18 | 18 |
| Total | 123 | 228 |

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
| TST-REQ-VEN-005-01 | Happy | REQ-VEN-005 | Given an unsupported venue configuration for the environment, When live order checks run, Then live orders are blocked and the refusal reason is persisted. |
| TST-REQ-VEN-005-02 | Edge | REQ-VEN-005 | Given multiple unsupported venue fields, When validation runs, Then the refusal event includes each relevant unsupported setting. |
| TST-REQ-VEN-006-01 | Focus | REQ-VEN-006 | Given an authorized dashboard update to venue config, When the next trading loop starts, Then the updated venue config is applied without restart. |

### Alpaca Stock and ETF Integration

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-ALP-001-01 | Happy | REQ-ALP-001 | Given Alpaca is configured and enabled, When venue adapters are registered, Then Alpaca is available for stocks and ETFs. |
| TST-REQ-ALP-001-02 | Edge | REQ-ALP-001 | Given Alpaca is not enabled, When the trading loop evaluates stock or ETF candidates, Then Alpaca scan and execution are skipped. |
| TST-REQ-ALP-002-01 | Happy | REQ-ALP-002 | Given stock and ETF candidates, When Alpaca filtering runs, Then only stocks and ETFs remain eligible. |
| TST-REQ-ALP-002-02 | Edge | REQ-ALP-002 | Given options, crypto, short, or margin candidates, When Alpaca filtering runs, Then each unsupported product is rejected with a reason. |
| TST-REQ-ALP-003-01 | Happy | REQ-ALP-003 | Given Alpaca account, market data, position, and order operations, When adapters execute them, Then the official SDK or documented HTTP APIs are used. |
| TST-REQ-ALP-003-02 | Edge | REQ-ALP-003 | Given an adapter without an approved Alpaca client binding, When live operations are requested, Then the operation is blocked. |
| TST-REQ-ALP-004-01 | Happy | REQ-ALP-004 | Given dev and prod settings for Claude and OpenAI, When Alpaca credentials are loaded, Then each environment and model has a distinct account identifier. |
| TST-REQ-ALP-004-02 | Edge | REQ-ALP-004 | Given a missing Alpaca account identifier for one model provider, When live checks run, Then Alpaca live trading is blocked for that provider. |
| TST-REQ-ALP-005-01 | Happy | REQ-ALP-005 | Given global dry-run mode is enabled, When an Alpaca stock or ETF order is approved, Then a simulated order is recorded without broker submission. |
| TST-REQ-ALP-005-02 | Edge | REQ-ALP-005 | Given dry-run mode and a mocked broker client, When execution runs, Then no Alpaca paper or live endpoint is called. |
| TST-REQ-ALP-006-01 | Happy | REQ-ALP-006 | Given dry-run mode is disabled, Alpaca is enabled, and risk checks pass, When an order is approved, Then it is submitted to the configured Alpaca account mode. |
| TST-REQ-ALP-006-02 | Edge | REQ-ALP-006 | Given dry-run mode is disabled but a risk check fails, When Alpaca execution is requested, Then no order is submitted. |
| TST-REQ-ALP-007-01 | Happy | REQ-ALP-007 | Given environment and dashboard config values, When Alpaca account mode is resolved, Then paper and live modes are supported values. |
| TST-REQ-ALP-007-02 | Edge | REQ-ALP-007 | Given an invalid Alpaca account mode, When config validation runs, Then the mode is rejected and live trading is blocked. |
| TST-REQ-ALP-008-01 | Happy | REQ-ALP-008 | Given a buy order that maintains a long-only position without margin, When Alpaca risk checks run, Then the order remains eligible. |
| TST-REQ-ALP-008-02 | Edge | REQ-ALP-008 | Given an order that would short a symbol or require margin, When Alpaca risk checks run, Then the order is refused. |
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
| TST-REQ-ALP-016-01 | Happy | REQ-ALP-016 | Given distinct Alpaca account identifiers for each model in the same environment and mode, When duplicate checks run, Then Alpaca live trading remains eligible. |
| TST-REQ-ALP-016-02 | Edge | REQ-ALP-016 | Given two model providers resolve to the same Alpaca account identifier in the same environment and mode, When checks run, Then live trading is blocked for the duplicate account. |
| TST-REQ-ALP-017-01 | Happy | REQ-ALP-017 | Given Alpaca and Postgres agree on positions, open orders, and buying power, When reconciliation runs, Then Alpaca live orders may proceed to remaining checks. |
| TST-REQ-ALP-017-02 | Edge | REQ-ALP-017 | Given reconciliation has not completed, When Alpaca live execution is requested, Then the order is blocked. |
| TST-REQ-ALP-018-01 | Happy | REQ-ALP-018 | Given reconciliation detects no unresolved mismatch, When Alpaca live checks run, Then the mismatch gate passes. |
| TST-REQ-ALP-018-02 | Edge | REQ-ALP-018 | Given an unresolved broker and Postgres mismatch, When Alpaca live checks run, Then live orders are blocked for the affected provider and mismatch details are recorded. |

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
| TST-REQ-DAT-006-01 | Focus | REQ-DAT-006 | Given raw snapshot lifecycle rules are synthesized, When infrastructure configuration is validated, Then raw snapshots have a 365-day retention policy. |
| TST-REQ-DAT-007-01 | Focus | REQ-DAT-007 | Given normalized snapshot lifecycle rules are synthesized, When infrastructure configuration is validated, Then normalized snapshots have a 730-day retention policy. |
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

### Wallet and Secrets Management

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-WAL-001-01 | Happy | REQ-WAL-001 | Given environment, venue, and model provider combinations, When credential references are resolved, Then each combination can use separate wallet or brokerage credentials. |
| TST-REQ-WAL-001-02 | Edge | REQ-WAL-001 | Given two combinations resolve to the same disallowed credential reference, When live checks run, Then the duplicate is rejected. |
| TST-REQ-WAL-002-01 | Happy | REQ-WAL-002 | Given wallet-generation CLI inputs for environment, venue, and provider, When the command runs, Then wallet material is generated for that target. |
| TST-REQ-WAL-002-02 | Edge | REQ-WAL-002 | Given missing or unsupported CLI inputs, When wallet generation runs, Then no wallet material is produced and validation errors are returned. |
| TST-REQ-WAL-003-01 | Happy | REQ-WAL-003 | Given deployed environment settings, When private keys and API credentials are requested, Then they are read only from AWS Secrets Manager. |
| TST-REQ-WAL-003-02 | Edge | REQ-WAL-003 | Given deployed environment settings and a local secret file path, When credential loading runs, Then local secret loading is rejected. |
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
| TST-REQ-LLM-002-01 | Happy | REQ-LLM-002 | Given Claude and OpenAI budget settings, When scoring costs are recorded, Then each provider budget is tracked separately. |
| TST-REQ-LLM-002-02 | Edge | REQ-LLM-002 | Given a scoring event attempts to consume the wrong provider budget, When budget accounting runs, Then the event is rejected or corrected before persistence. |
| TST-REQ-LLM-003-01 | Happy | REQ-LLM-003 | Given a successful model evaluation, When the score is persisted, Then provider, prompt version, input summary, thesis, confidence, probability, and cost estimate are stored. |
| TST-REQ-LLM-003-02 | Edge | REQ-LLM-003 | Given a model response missing required scoring fields, When parsing runs, Then the score is marked failed and no live order can use it. |
| TST-REQ-LLM-004-01 | Happy | REQ-LLM-004 | Given a model budget is exhausted, When scoring queues are built, Then no new requests are sent to that model. |
| TST-REQ-LLM-004-02 | Edge | REQ-LLM-004 | Given Claude is exhausted and OpenAI has budget, When scoring runs, Then OpenAI continues while Claude is skipped. |
| TST-REQ-LLM-005-01 | Happy | REQ-LLM-005 | Given LLM scoring succeeds for a model and market, When execution eligibility is checked, Then the scoring failure gate passes. |
| TST-REQ-LLM-005-02 | Edge | REQ-LLM-005 | Given LLM scoring fails for a model and market, When execution eligibility is checked in the same loop, Then live orders are blocked for that pair. |
| TST-REQ-LLM-006-01 | Focus | REQ-LLM-006 | Given an authorized dashboard user changes model budgets or scoring settings, When the update is saved, Then the new scoring config is persisted. |
| TST-REQ-LLM-007-01 | Focus | REQ-LLM-007 | Given scoring config changes are saved, When the next trading loop starts, Then the updated settings are used. |

### Strategy and Signal Engine

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-STR-001-01 | Happy | REQ-STR-001 | Given default scheduler config, When the worker starts, Then the trading loop interval is 60 seconds. |
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
| TST-REQ-EXE-015-01 | Happy | REQ-EXE-015 | Given kill switch activation and enabled live venues with open orders, When kill switch handling runs, Then cancel attempts are issued for open orders. |
| TST-REQ-EXE-015-02 | Edge | REQ-EXE-015 | Given a venue cancel attempt fails, When kill switch handling runs, Then the failure is recorded and remaining cancel attempts continue. |
| TST-REQ-EXE-016-01 | Happy | REQ-EXE-016 | Given an order is refused, submitted, filled, canceled, or failed, When the event is processed, Then it is persisted and visible in dashboard status. |
| TST-REQ-EXE-016-02 | Edge | REQ-EXE-016 | Given event persistence fails, When an order event is processed, Then the system reports degraded status and avoids hiding the failure. |
| TST-REQ-EXE-017-01 | Happy | REQ-EXE-017 | Given dry-run is disabled, venue is enabled, account mode is valid, and all checks pass, When live execution runs, Then live orders are permitted. |
| TST-REQ-EXE-017-02 | Edge | REQ-EXE-017 | Given dry-run is disabled but a venue is disabled or account mode fails checks, When live execution runs, Then live orders are blocked. |

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
| TST-REQ-UI-008-01 | Happy | REQ-UI-008 | Given an authorized user activates the dashboard kill switch, When the request is processed, Then the global kill switch state is set. |
| TST-REQ-UI-008-02 | Edge | REQ-UI-008 | Given an unauthorized user attempts kill switch activation, When the request is processed, Then the request is denied. |
| TST-REQ-UI-008-03 | Focus | REQ-UI-008 | Given an authorized dashboard API caller activates the kill switch, When the kill switch endpoint is called, Then live trading is disabled and cancel progress is exposed. |
| TST-REQ-UI-009-01 | Focus | REQ-UI-009 | Given wallet metadata contains public identifiers and private secret references, When dashboard wallet views render, Then only public identifiers and health are shown. |
| TST-REQ-UI-009-02 | Focus | REQ-UI-009 | Given frontend wallet status renders, When dashboard control checks run, Then public identifiers are displayed and private key or secret terms are absent. |
| TST-REQ-UI-010-01 | Focus | REQ-UI-010 | Given Claude and OpenAI records exist, When dashboard model views render, Then positions, decisions, budgets, and P&L are separated by provider. |
| TST-REQ-UI-011-01 | Happy | REQ-UI-011 | Given comparison metrics exist for Polymarket and Alpaca, When dashboard comparison views render, Then P&L, win rate, drawdown, cost, exposure, trade count, and return-to-risk are shown. |
| TST-REQ-UI-011-02 | Edge | REQ-UI-011 | Given one model or venue has insufficient comparison data, When comparison views render, Then unavailable metrics are labeled without showing misleading zero values. |

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

### Notifications

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-NOT-001-01 | Happy | REQ-NOT-001 | Given the daily digest schedule fires and allowlisted users exist, When notifications run, Then SES sends digest email to allowlisted users. |
| TST-REQ-NOT-001-02 | Edge | REQ-NOT-001 | Given no allowlisted recipients exist, When digest notifications run, Then no email is sent and the skipped reason is recorded. |
| TST-REQ-NOT-002-01 | Happy | REQ-NOT-002 | Given digest inputs are available, When the digest is rendered, Then it includes P&L, open positions, trades, exits, refused orders, budget, ingestion, and risk status. |
| TST-REQ-NOT-002-02 | Edge | REQ-NOT-002 | Given one digest input source is unavailable, When the digest is rendered, Then the missing section is marked unavailable and delivery can still proceed if policy allows. |
| TST-REQ-NOT-003-01 | Happy | REQ-NOT-003 | Given a position P&L change reaches 25 USD or 10 percent by default, When movement detection runs, Then SES sends a large-movement alert. |
| TST-REQ-NOT-003-02 | Edge | REQ-NOT-003 | Given a position P&L change is below both default thresholds, When movement detection runs, Then no large-movement alert is sent. |
| TST-REQ-NOT-004-01 | Happy | REQ-NOT-004 | Given daily realized or unrealized P&L crosses a configured threshold, When notification checks run, Then SES sends an alert. |
| TST-REQ-NOT-004-02 | Edge | REQ-NOT-004 | Given daily P&L remains within thresholds, When notification checks run, Then no threshold alert is sent. |
| TST-REQ-NOT-005-01 | Happy | REQ-NOT-005 | Given default notification config, When an alert was sent less than 30 minutes ago for the same market and provider, Then another alert is suppressed. |
| TST-REQ-NOT-005-02 | Edge | REQ-NOT-005 | Given the 30-minute cooldown has elapsed, When the alert condition still holds, Then a new alert is allowed. |
| TST-REQ-NOT-006-01 | Focus | REQ-NOT-006 | Given an authorized dashboard user changes recipients, thresholds, schedules, or cooldowns, When notification config is saved, Then the updated settings persist. |
| TST-REQ-NOT-007-01 | Focus | REQ-NOT-007 | Given SES delivery fails, When retry policy runs, Then the failure is recorded and retry timing follows config. |

### Deployment, CI/CD, and Codex Web Setup

| Test ID | Type | Validates | Test Description |
|---------|------|-----------|------------------|
| TST-REQ-DEP-001-01 | Happy | REQ-DEP-001 | Given local Docker and gitignored `.env` files, When local startup commands run, Then the app stack starts without production secrets. |
| TST-REQ-DEP-001-02 | Edge | REQ-DEP-001 | Given required local env values are missing, When local startup runs, Then startup fails with safe dry-run defaults or clear setup errors. |
| TST-REQ-DEP-002-01 | Happy | REQ-DEP-002 | Given CloudFormation parameters for us-east-1, When infrastructure templates are validated, Then ECS Fargate, RDS, S3, Secrets Manager, CloudWatch, and SES resources are defined. |
| TST-REQ-DEP-002-02 | Edge | REQ-DEP-002 | Given a non-us-east-1 deployment target, When deployment validation runs, Then deployment is blocked or requires explicit override. |
| TST-REQ-DEP-003-01 | Happy | REQ-DEP-003 | Given code is merged to `develop`, When GitHub Actions runs, Then the development deployment workflow is selected. |
| TST-REQ-DEP-003-02 | Edge | REQ-DEP-003 | Given a branch other than `develop` or `main`, When GitHub Actions runs, Then automatic environment deployment is not triggered. |
| TST-REQ-DEP-004-01 | Happy | REQ-DEP-004 | Given code is merged to `main`, When GitHub Actions runs, Then production deployment starts automatically. |
| TST-REQ-DEP-004-02 | Edge | REQ-DEP-004 | Given production deployment tests fail, When GitHub Actions runs, Then production deploy steps do not execute. |
| TST-REQ-DEP-005-01 | Happy | REQ-DEP-005 | Given CI is triggered, When workflow execution starts, Then tests run before build or deploy jobs. |
| TST-REQ-DEP-005-02 | Edge | REQ-DEP-005 | Given tests fail in CI, When workflow execution continues, Then container build and deploy jobs are blocked. |
| TST-REQ-DEP-005-03 | Focus | REQ-DEP-005 | Given the spec suite is ready for release review, When traceability verification scans spec tests, Then no pending red-phase placeholders remain. |
| TST-REQ-DEP-005-04 | Focus | REQ-DEP-005 | Given frontend code is present, When CI runs, Then npm install, typecheck, and auth-boundary checks run before build or deploy jobs. |
| TST-REQ-DEP-006-01 | Happy | REQ-DEP-006 | Given tests pass, When deployment workflow runs, Then backend and frontend images are built and published to ECR before ECS deployment. |
| TST-REQ-DEP-006-02 | Edge | REQ-DEP-006 | Given ECR publish fails, When deployment workflow runs, Then ECS deployment is skipped and failure status is reported. |
| TST-REQ-DEP-007-01 | Happy | REQ-DEP-007 | Given repo setup files are inspected, When `.env.example` files are validated, Then required local config keys are documented without secrets. |
| TST-REQ-DEP-007-02 | Edge | REQ-DEP-007 | Given `.env.example` contains a real-looking secret value, When secret scanning runs, Then validation fails. |
| TST-REQ-DEP-008-01 | Happy | REQ-DEP-008 | Given Codex web setup docs and scripts, When a developer follows setup, Then dependencies, tests, and safe dry-run config are available. |
| TST-REQ-DEP-008-02 | Edge | REQ-DEP-008 | Given setup runs without trading secrets, When dependency install and tests run, Then setup still succeeds with dry-run-safe defaults. |
| TST-REQ-DEP-009-01 | Happy | REQ-DEP-009 | Given a Codex web environment without production trading secrets, When dependencies install, tests run, or code is inspected, Then those actions succeed. |
| TST-REQ-DEP-009-02 | Edge | REQ-DEP-009 | Given code tries to require production secrets during import or tests, When CI or Codex setup runs, Then the test fails. |
| TST-REQ-DEP-010-01 | Focus | REQ-DEP-010 | Given development and production deployments, When infrastructure and secret names are validated, Then resources, secrets, wallets, and config are separated by environment. |

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

## Traceability Matrix

| Requirement | Test IDs |
|-------------|----------|
| REQ-VEN-001 | TST-REQ-VEN-001-01, TST-REQ-VEN-001-02 |
| REQ-VEN-002 | TST-REQ-VEN-002-01, TST-REQ-VEN-002-02 |
| REQ-VEN-003 | TST-REQ-VEN-003-01, TST-REQ-VEN-003-02 |
| REQ-VEN-004 | TST-REQ-VEN-004-01, TST-REQ-VEN-004-02 |
| REQ-VEN-005 | TST-REQ-VEN-005-01, TST-REQ-VEN-005-02 |
| REQ-VEN-006 | TST-REQ-VEN-006-01 |
| REQ-ALP-001 | TST-REQ-ALP-001-01, TST-REQ-ALP-001-02 |
| REQ-ALP-002 | TST-REQ-ALP-002-01, TST-REQ-ALP-002-02 |
| REQ-ALP-003 | TST-REQ-ALP-003-01, TST-REQ-ALP-003-02 |
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
| REQ-ALP-015 | TST-REQ-ALP-015-01 |
| REQ-ALP-016 | TST-REQ-ALP-016-01, TST-REQ-ALP-016-02 |
| REQ-ALP-017 | TST-REQ-ALP-017-01, TST-REQ-ALP-017-02 |
| REQ-ALP-018 | TST-REQ-ALP-018-01, TST-REQ-ALP-018-02 |
| REQ-DAT-001 | TST-REQ-DAT-001-01, TST-REQ-DAT-001-02 |
| REQ-DAT-002 | TST-REQ-DAT-002-01, TST-REQ-DAT-002-02 |
| REQ-DAT-003 | TST-REQ-DAT-003-01, TST-REQ-DAT-003-02 |
| REQ-DAT-004 | TST-REQ-DAT-004-01, TST-REQ-DAT-004-02 |
| REQ-DAT-005 | TST-REQ-DAT-005-01, TST-REQ-DAT-005-02 |
| REQ-DAT-006 | TST-REQ-DAT-006-01 |
| REQ-DAT-007 | TST-REQ-DAT-007-01 |
| REQ-DAT-008 | TST-REQ-DAT-008-01 |
| REQ-DB-001 | TST-REQ-DB-001-01, TST-REQ-DB-001-02 |
| REQ-DB-002 | TST-REQ-DB-002-01, TST-REQ-DB-002-02 |
| REQ-DB-003 | TST-REQ-DB-003-01, TST-REQ-DB-003-02 |
| REQ-DB-004 | TST-REQ-DB-004-01, TST-REQ-DB-004-02 |
| REQ-DB-005 | TST-REQ-DB-005-01, TST-REQ-DB-005-02 |
| REQ-DB-006 | TST-REQ-DB-006-01 |
| REQ-DB-007 | TST-REQ-DB-007-01, TST-REQ-DB-007-02 |
| REQ-WAL-001 | TST-REQ-WAL-001-01, TST-REQ-WAL-001-02 |
| REQ-WAL-002 | TST-REQ-WAL-002-01, TST-REQ-WAL-002-02 |
| REQ-WAL-003 | TST-REQ-WAL-003-01, TST-REQ-WAL-003-02 |
| REQ-WAL-004 | TST-REQ-WAL-004-01, TST-REQ-WAL-004-02 |
| REQ-WAL-005 | TST-REQ-WAL-005-01, TST-REQ-WAL-005-02 |
| REQ-WAL-006 | TST-REQ-WAL-006-01, TST-REQ-WAL-006-02 |
| REQ-WAL-007 | TST-REQ-WAL-007-01 |
| REQ-LLM-001 | TST-REQ-LLM-001-01, TST-REQ-LLM-001-02 |
| REQ-LLM-002 | TST-REQ-LLM-002-01, TST-REQ-LLM-002-02 |
| REQ-LLM-003 | TST-REQ-LLM-003-01, TST-REQ-LLM-003-02 |
| REQ-LLM-004 | TST-REQ-LLM-004-01, TST-REQ-LLM-004-02 |
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
| REQ-EXE-014 | TST-REQ-EXE-014-01, TST-REQ-EXE-014-02 |
| REQ-EXE-015 | TST-REQ-EXE-015-01, TST-REQ-EXE-015-02 |
| REQ-EXE-016 | TST-REQ-EXE-016-01, TST-REQ-EXE-016-02 |
| REQ-EXE-017 | TST-REQ-EXE-017-01, TST-REQ-EXE-017-02 |
| REQ-EXT-001 | TST-REQ-EXT-001-01, TST-REQ-EXT-001-02 |
| REQ-EXT-002 | TST-REQ-EXT-002-01, TST-REQ-EXT-002-02 |
| REQ-EXT-003 | TST-REQ-EXT-003-01, TST-REQ-EXT-003-02 |
| REQ-EXT-004 | TST-REQ-EXT-004-01, TST-REQ-EXT-004-02 |
| REQ-EXT-005 | TST-REQ-EXT-005-01, TST-REQ-EXT-005-02 |
| REQ-EXT-006 | TST-REQ-EXT-006-01, TST-REQ-EXT-006-02 |
| REQ-UI-001 | TST-REQ-UI-001-01, TST-REQ-UI-001-02, TST-REQ-UI-001-03 |
| REQ-UI-002 | TST-REQ-UI-002-01, TST-REQ-UI-002-02, TST-REQ-UI-002-03 |
| REQ-UI-003 | TST-REQ-UI-003-01, TST-REQ-UI-003-02, TST-REQ-UI-003-03, TST-REQ-UI-003-04 |
| REQ-UI-004 | TST-REQ-UI-004-01, TST-REQ-UI-004-02, TST-REQ-UI-004-03, TST-REQ-UI-004-04 |
| REQ-UI-005 | TST-REQ-UI-005-01, TST-REQ-UI-005-02, TST-REQ-UI-005-03 |
| REQ-UI-006 | TST-REQ-UI-006-01, TST-REQ-UI-006-02, TST-REQ-UI-006-03, TST-REQ-UI-006-04 |
| REQ-UI-007 | TST-REQ-UI-007-01, TST-REQ-UI-007-02, TST-REQ-UI-007-03 |
| REQ-UI-008 | TST-REQ-UI-008-01, TST-REQ-UI-008-02, TST-REQ-UI-008-03 |
| REQ-UI-009 | TST-REQ-UI-009-01, TST-REQ-UI-009-02 |
| REQ-UI-010 | TST-REQ-UI-010-01 |
| REQ-UI-011 | TST-REQ-UI-011-01, TST-REQ-UI-011-02 |
| REQ-CMP-001 | TST-REQ-CMP-001-01, TST-REQ-CMP-001-02 |
| REQ-CMP-002 | TST-REQ-CMP-002-01, TST-REQ-CMP-002-02 |
| REQ-CMP-003 | TST-REQ-CMP-003-01, TST-REQ-CMP-003-02 |
| REQ-CMP-004 | TST-REQ-CMP-004-01 |
| REQ-NOT-001 | TST-REQ-NOT-001-01, TST-REQ-NOT-001-02 |
| REQ-NOT-002 | TST-REQ-NOT-002-01, TST-REQ-NOT-002-02 |
| REQ-NOT-003 | TST-REQ-NOT-003-01, TST-REQ-NOT-003-02 |
| REQ-NOT-004 | TST-REQ-NOT-004-01, TST-REQ-NOT-004-02 |
| REQ-NOT-005 | TST-REQ-NOT-005-01, TST-REQ-NOT-005-02 |
| REQ-NOT-006 | TST-REQ-NOT-006-01 |
| REQ-NOT-007 | TST-REQ-NOT-007-01 |
| REQ-DEP-001 | TST-REQ-DEP-001-01, TST-REQ-DEP-001-02 |
| REQ-DEP-002 | TST-REQ-DEP-002-01, TST-REQ-DEP-002-02 |
| REQ-DEP-003 | TST-REQ-DEP-003-01, TST-REQ-DEP-003-02 |
| REQ-DEP-004 | TST-REQ-DEP-004-01, TST-REQ-DEP-004-02 |
| REQ-DEP-005 | TST-REQ-DEP-005-01, TST-REQ-DEP-005-02, TST-REQ-DEP-005-03, TST-REQ-DEP-005-04 |
| REQ-DEP-006 | TST-REQ-DEP-006-01, TST-REQ-DEP-006-02 |
| REQ-DEP-007 | TST-REQ-DEP-007-01, TST-REQ-DEP-007-02 |
| REQ-DEP-008 | TST-REQ-DEP-008-01, TST-REQ-DEP-008-02 |
| REQ-DEP-009 | TST-REQ-DEP-009-01, TST-REQ-DEP-009-02 |
| REQ-DEP-010 | TST-REQ-DEP-010-01 |
| REQ-OBS-001 | TST-REQ-OBS-001-01, TST-REQ-OBS-001-02 |
| REQ-OBS-002 | TST-REQ-OBS-002-01, TST-REQ-OBS-002-02 |
| REQ-OBS-003 | TST-REQ-OBS-003-01, TST-REQ-OBS-003-02 |
| REQ-OBS-004 | TST-REQ-OBS-004-01, TST-REQ-OBS-004-02 |
| REQ-OBS-005 | TST-REQ-OBS-005-01, TST-REQ-OBS-005-02 |
| REQ-OBS-006 | TST-REQ-OBS-006-01, TST-REQ-OBS-006-02, TST-REQ-OBS-006-03 |
