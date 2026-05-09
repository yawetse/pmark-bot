# claude-poly-bot — Test Specification

**Methodology:** EARS-traceable test specification.
**ID format:** `TST-{REQ-ID}-{NN}` where NN is sequential per REQ.
**Test types:** `U` unit · `I` integration · `E` e2e · `P` property (hypothesis).
**Coverage rule:** Every P0 REQ has ≥ 1 happy-path test AND ≥ 1 edge-case test.
**Strategy:** Hybrid isolation (session-scoped Postgres testcontainer, per-test transaction with rollback). Hypothesis property tests for `domain/{kelly, risk, scoring, consensus}`.

---

## DATA — Data Pipeline

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-DATA-001-01 | I | REQ-DATA-001 | Given a clean S3 bucket, When data-refresh runs, Then trades.parquet appears under `polymarket-trades/yyyy=2026/mm=04/dd=24/`. |
| TST-DATA-001-02 | I | REQ-DATA-001 | Given S3 throttle (mock 503), When refresh runs, Then boto3 retries succeed; data lands. |
| TST-DATA-002-01 | I | REQ-DATA-002 | Given EventBridge fires at 06:00 UTC, When the rule triggers, Then ECS RunTask launches data-refresh task. |
| TST-DATA-002-02 | U | REQ-DATA-002 | Given a mocked EventBridge event, When handler dispatches, Then refresh begins. |
| TST-DATA-003-01 | I | REQ-DATA-003 | Given a refreshed dataset, When recompute runs, Then `target_wallets` rows match expected wallets passing thresholds. |
| TST-DATA-003-02 | U | REQ-DATA-003 | Given a synthetic 1000-wallet dataset (50 above threshold), When ranking runs, Then 50 winners returned sorted by P&L. |
| TST-DATA-004-01 | U | REQ-DATA-004 | Given thresholds (100, 0.70, 50), When applied to a wallet with (99 trades, 0.71 win), Then wallet rejected. |
| TST-DATA-004-02 | U | REQ-DATA-004 | Given thresholds, When applied to a wallet with exactly (100, 0.70), Then wallet accepted (boundary inclusive). |
| TST-DATA-005-01 | I | REQ-DATA-005 | Given a refresh job that throws mid-run, When job exits, Then `target_wallets` rows are unchanged AND SES alert sent. |
| TST-DATA-005-02 | I | REQ-DATA-005 | Given previous list of 47 wallets, When refresh fails, Then list still has 47 wallets afterwards. |
| TST-DATA-006-01 | I | REQ-DATA-006 | Given S3 lifecycle policy, When 30+ days pass, Then old daily snapshots deleted by S3 (policy validation only — moto). |
| TST-DATA-007-01 | I | REQ-DATA-007 | Given `target_wallets` populated, When `TargetWalletRepo.list_current()` called, Then wallets returned for whale check. |
| TST-DATA-008-01 | I | REQ-DATA-008 | Given a refresh in progress, When concurrent refresh attempts to start, Then second attempt blocks until first completes (advisory lock). |
| TST-DATA-008-02 | I | REQ-DATA-008 | Given a refresh that crashes mid-run, When startup re-runs, Then partial state cleared; previous list intact. |
| TST-DATA-009-01 | I | REQ-DATA-009 | Given `claude-poly-bot refresh-data` CLI, When invoked, Then refresh runs once; reports completion. |

---

## SCAN — Market Scanner

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-SCAN-001-01 | I | REQ-SCAN-001 | Given scanner timer fires, When loop runs, Then `venue.list_active_markets()` called once. |
| TST-SCAN-001-02 | I | REQ-SCAN-001 | Given configured cadence 300s, When clock advances 600s, Then 2 scan runs occurred. |
| TST-SCAN-002-01 | U | REQ-SCAN-002 | Given a Polymarket market with midpoint 0.5 + book + 24h to res, When scored, Then ScanScore has expected gap/depth/hours fields. |
| TST-SCAN-003-01 | U | REQ-SCAN-003 | Given default filters, When market with gap=0.06 scored, Then rejected with reason "insufficient_gap". |
| TST-SCAN-003-02 | U | REQ-SCAN-003 | Given filters, When market with gap=0.07 exactly, Then accepted (boundary inclusive). |
| TST-SCAN-003-03 | U | REQ-SCAN-003 | Given filters, When depth=$499, Then rejected. |
| TST-SCAN-003-04 | U | REQ-SCAN-003 | Given filters, When hours_to_resolution=3, Then rejected. |
| TST-SCAN-003-05 | U | REQ-SCAN-003 | Given filters, When hours_to_resolution=169, Then rejected. |
| TST-SCAN-004-01 | I | REQ-SCAN-004 | Given a market rejected for "insufficient_depth", When scan completes, Then `market_scans` row contains the reason. |
| TST-SCAN-005-01 | I | REQ-SCAN-005 | Given accepted market, When scan completes, Then `candidate_queue` row inserted with venue=polymarket. |
| TST-SCAN-006-01 | I | REQ-SCAN-006 | Given bot configured geo=US, When Polymarket scanner runs, Then geo=US passed to `list_active_markets()`. |
| TST-SCAN-007-01 | I | REQ-SCAN-007 | Given Polymarket returns 503 thrice, When scan runs, Then 3 retries occur then scan skipped + alert. |
| TST-SCAN-007-02 | I | REQ-SCAN-007 | Given Polymarket returns 200, When scan runs, Then no retry. |
| TST-SCAN-008-01 | I | REQ-SCAN-008 | Given scan completes, When inspecting DB, Then `market_scans` summary row with fetched/accepted/rejected counts. |
| TST-SCAN-009-01 | I | REQ-SCAN-009 | Given API endpoint `/api/scanner/trigger`, When called, Then immediate scan run starts. |
| TST-SCAN-010-01 | U | REQ-SCAN-010 | Given Alpaca instrument with vol_today=2x avg, When scored, Then relative_volume=2.0 in ScanScore. |
| TST-SCAN-011-01 | U | REQ-SCAN-011 | Given Alpaca filters (min rel vol 1.5), When instrument with rv=1.4, Then rejected. |
| TST-SCAN-011-02 | U | REQ-SCAN-011 | Given Alpaca filters, When instrument price=$2001, Then rejected. |
| TST-SCAN-012-01 | I | REQ-SCAN-012 | Given configured universe=sp500, When scanner runs, Then only S&P 500 tickers fetched. |
| TST-SCAN-013-01 | I | REQ-SCAN-013 | Given current time outside 09:30–16:00 ET, When Alpaca scanner timer fires, Then scan suspended. |
| TST-SCAN-013-02 | I | REQ-SCAN-013 | Given current time on a US holiday, When Alpaca scanner runs, Then scan suspended. |

---

## BRN — Brain (LLM Strategist)

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-BRN-001-01 | I | REQ-BRN-001 | Given a Polymarket candidate, When brain evaluates, Then 4 LLM calls made (base_rate, news, whale, disposition). |
| TST-BRN-001-02 | I | REQ-BRN-001 | Given an Alpaca candidate, When brain evaluates, Then 4 LLM calls made (whale replaced by unusual_volume). |
| TST-BRN-002-01 | I | REQ-BRN-002 | Given a candidate, When brain runs sub-agents, Then 3 LLM calls made (arbitrage, convergence, whale_copy/flow_copy). |
| TST-BRN-003-01 | I | REQ-BRN-003 | Given target wallets [A, B, C] and a market, When whale check runs, Then count of wallets holding the market returned. |
| TST-BRN-004-01 | I | REQ-BRN-004 | Given an Alpaca candidate, When unusual_volume check runs, Then relative volume + price z-score returned (no third-party API). |
| TST-BRN-005-01 | I | REQ-BRN-005 | Given news check, When LLM called, Then web_search tool present in request. |
| TST-BRN-005-02 | I | REQ-BRN-005 | Given disposition check, When LLM called, Then web_search tool absent. |
| TST-BRN-006-01 | I | REQ-BRN-006 | Given LLM response with valid JSON CheckResult, When parsed, Then CheckResult instance returned. |
| TST-BRN-006-02 | I | REQ-BRN-006 | Given LLM returns malformed JSON, When parser retries, Then 2 retries occur then SKIP returned with error. |
| TST-BRN-007-01 | I | REQ-BRN-007 | Given persisted decision, When inspecting DB, Then `decisions` row has prompt, response, model_id, tokens, cost, latency. |
| TST-BRN-008-01 | I | REQ-BRN-008 | Given AnthropicStrategist, When request built, Then `cache_control: ephemeral` on system prompt. |
| TST-BRN-009-01 | U | REQ-BRN-009 | Given 4 BUY checks with confidences [0.9,0.8,0.7,0.7], When thesis generated, Then verdict=BUY, confidence=mean of agreeing. |
| TST-BRN-009-02 | U | REQ-BRN-009 | Given 2 BUY + 2 SELL, When thesis generated, Then SKIP. |
| TST-BRN-010-01 | U | REQ-BRN-010 | Given mean_confidence=0.74, threshold=0.75, When evaluated, Then SKIP. |
| TST-BRN-010-02 | U | REQ-BRN-010 | Given mean_confidence=0.75, threshold=0.75, When evaluated, Then thesis produced (boundary inclusive). |
| TST-BRN-011-01 | I | REQ-BRN-011 | Given config sets base_rate model to claude-sonnet-4-6, When brain runs, Then base_rate call uses sonnet. |
| TST-BRN-012-01 | I | REQ-BRN-012 | Given LLM returns 429, When client retries, Then 3 retries occur with exponential backoff. |
| TST-BRN-013-01 | I | REQ-BRN-013 | Given 5 consecutive LLM errors, When brain runs, Then bot decisioning halted + alert. |
| TST-BRN-013-02 | I | REQ-BRN-013 | Given 4 errors followed by 1 success, When brain runs, Then no halt; counter reset. |
| TST-BRN-014-01 | I | REQ-BRN-014 | Given LLM spend is incremented after each call, When 12 calls complete, Then daily spend metric reflects sum. |
| TST-BRN-015-01 | U | REQ-BRN-015 | Given whale check cached, When called twice within 5 min, Then second call hits cache (no API). |

---

## EXE — Executor

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-EXE-001-01 | P | REQ-EXE-001 | Hypothesis: for valid p_win, market_price, bankroll, Kelly produces non-negative size or 0. |
| TST-EXE-002-01 | U | REQ-EXE-002 | Given p_win=0.9, market_price=0.5, max_fraction=0.25, When sized, Then f_applied capped at 0.25. |
| TST-EXE-002-02 | U | REQ-EXE-002 | Given p_win=0.6, market_price=0.5 (f_star ~ 0.2), When sized, Then f_applied = 0.2 (no clamp). |
| TST-EXE-003-01 | U | REQ-EXE-003 | Given p_win=0.4, market_price=0.5 (negative EV), When sized, Then size=0, reason=NEGATIVE_EV. |
| TST-EXE-004-01 | U | REQ-EXE-004 | Given 2 BUY + 1 SKIP sub-agents, When sized, Then FULL position. |
| TST-EXE-004-02 | U | REQ-EXE-004 | Given 1 BUY + 2 SKIP, When sized, Then HALF position. |
| TST-EXE-004-03 | U | REQ-EXE-004 | Given 1 BUY + 1 SELL + 1 SKIP, When sized, Then SKIP. |
| TST-EXE-005-01 | I | REQ-EXE-005 | Given Polymarket thesis with midpoint 0.6, slippage 0.02, side BUY, When place_order, Then limit_price=0.62 (midpoint + slippage on buy). |
| TST-EXE-006-01 | I | REQ-EXE-006 | Given Alpaca limit order unfilled after TTL, When TTL elapses, Then cancel + market order submitted. |
| TST-EXE-006-02 | I | REQ-EXE-006 | Given Alpaca limit order fills before TTL, When fill happens, Then no market fallback. |
| TST-EXE-007-01 | I | REQ-EXE-007 | Given DRY_RUN active for (claude, polymarket), When executor runs, Then `orders` row written with status=SIMULATED, no venue call. |
| TST-EXE-008-01 | I | REQ-EXE-008 | Given LIVE_ENABLED=False, When thesis approved, Then order routed via DRY path. |
| TST-EXE-009-01 | I | REQ-EXE-009 | Given Polymarket place_order, When executed live, Then EVM private key signs (mocked); request to clob_client made. |
| TST-EXE-010-01 | I | REQ-EXE-010 | Given order placed, When inspecting DB, Then orders row has client_order_id, venue, side, size, price, thesis_id. |
| TST-EXE-011-01 | I | REQ-EXE-011 | Given limit order with TTL=300, When unfilled, Then cancel called after 300s. |
| TST-EXE-012-01 | I | REQ-EXE-012 | Given (bot, venue) has 5 open positions, When new thesis, Then RISK_REJECTED with reason=MAX_OPEN_POSITIONS. |
| TST-EXE-013-01 | I | REQ-EXE-013 | Given proposed size=$30 on $100 bankroll, max_position_pct=0.25, When sized, Then capped at $25. |
| TST-EXE-014-01 | I | REQ-EXE-014 | Given order fills at price=0.65, When fill processed, Then position row created with entry_price=0.65. |
| TST-EXE-015-01 | I | REQ-EXE-015 | Given Alpaca entry fills, When fill recorded, Then bracket stop child order submitted at thesis.stop_price. |
| TST-EXE-015-02 | I | REQ-EXE-015 | Given bracket stop submission fails, When error caught, Then alert fires; position remains OPEN. |

---

## EXIT — Exit Engine

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-EXIT-001-01 | I | REQ-EXIT-001 | Given exit timer fires, When loop runs with 3 open positions, Then each evaluated. |
| TST-EXIT-002-01 | I | REQ-EXIT-002 | Given position entry=0.5, target=0.8, current=0.755, When evaluated, Then TARGET_HIT (>= 0.5+0.85*(0.8-0.5)=0.755). |
| TST-EXIT-002-02 | I | REQ-EXIT-002 | Given current=0.754, When evaluated, Then NOT TARGET_HIT (boundary). |
| TST-EXIT-003-01 | I | REQ-EXIT-003 | Given vol_10m=600, avg=200 (3x), When evaluated, Then VOLUME_EXIT. |
| TST-EXIT-003-02 | I | REQ-EXIT-003 | Given vol_10m=599, avg=200, When evaluated, Then NOT VOLUME_EXIT (boundary). |
| TST-EXIT-004-01 | I | REQ-EXIT-004 | Given position open 25h with 1% price change, When evaluated, Then STALE_THESIS. |
| TST-EXIT-004-02 | I | REQ-EXIT-004 | Given position open 23h with 0.5% change, When evaluated, Then NOT stale (age boundary). |
| TST-EXIT-005-01 | I | REQ-EXIT-005 | Given Alpaca position entry=$100, stop=$95, current=$94, When evaluated, Then STOP_LOSS. |
| TST-EXIT-006-01 | I | REQ-EXIT-006 | Given Alpaca position with horizon_ends_at=now-1m, When exit loop runs, Then HORIZON_EXIT. |
| TST-EXIT-007-01 | U | REQ-EXIT-007 | Given exit configs override, When loop reads, Then custom multiplier applied. |
| TST-EXIT-008-01 | I | REQ-EXIT-008 | Given LIVE_ENABLED=False, When exit triggers, Then simulated close (status=SIMULATED). |
| TST-EXIT-009-01 | I | REQ-EXIT-009 | Given open Polymarket position, When position created, Then WS subscription started for that market. |
| TST-EXIT-010-01 | I | REQ-EXIT-010 | Given open Alpaca position, When position created, Then Alpaca trade/quote stream subscribed. |
| TST-EXIT-011-01 | I | REQ-EXIT-011 | Given WS dropped, When 5 reconnect attempts fail, Then alert + REST polling fallback. |
| TST-EXIT-012-01 | I | REQ-EXIT-012 | Given exit order fills at 0.7, position entry 0.6 size $10, When closed, Then position.realized_pnl=$10*(0.7/0.6 - 1). |
| TST-EXIT-013-01 | I | REQ-EXIT-013 | Given Polymarket market resolves to YES, When event received, Then position closed with reason MARKET_RESOLVED. |
| TST-EXIT-014-01 | I | REQ-EXIT-014 | Given Alpaca position open at 15:55:00 ET on trading day, When exit loop runs, Then EOD_FLATTEN fires. |
| TST-EXIT-014-02 | I | REQ-EXIT-014 | Given Alpaca position at 15:54:59 ET, When exit loop runs, Then NOT EOD_FLATTEN (boundary). |

---

## RISK — Risk Manager

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-RISK-001-01 | I | REQ-RISK-001 | Given trades occur in a UTC day, When 00:00 UTC arrives, Then daily P&L resets to 0. |
| TST-RISK-001-02 | I | REQ-RISK-001 | Given trade fills at 23:59:59 UTC and another at 00:00:01 UTC next day, When P&L computed, Then attributed to respective UTC days. |
| TST-RISK-002-01 | I | REQ-RISK-002 | Given bankroll=$100 day_start, daily_pnl=-$50, When evaluated, Then halt active. |
| TST-RISK-002-02 | I | REQ-RISK-002 | Given daily_pnl=-$49, When evaluated, Then no halt. |
| TST-RISK-003-01 | I | REQ-RISK-003 | Given risk halt active for (claude, poly), When new thesis arrives, Then RISK_REJECTED. |
| TST-RISK-003-02 | I | REQ-RISK-003 | Given halt active and an open position, When exit trigger fires, Then close still placed. |
| TST-RISK-004-01 | I | REQ-RISK-004 | Given (claude, poly) halted, When OpenAI bot evaluates a candidate, Then no halt for OpenAI. |
| TST-RISK-005-01 | U | REQ-RISK-005 | Given max_open=5, current=5, When pre-trade check, Then MAX_OPEN_POSITIONS. |
| TST-RISK-006-01 | U | REQ-RISK-006 | Given max_position_pct=0.25, bankroll=$100, proposed=$30, When capped, Then $25. |
| TST-RISK-007-01 | I | REQ-RISK-007 | Given each LLM call records cost, When sum > daily cap, Then halt for that bot. |
| TST-RISK-008-01 | I | REQ-RISK-008 | Given daily_llm_spend=$20, cap=$20, When evaluated, Then halt. |
| TST-RISK-009-01 | I | REQ-RISK-009 | Given LIVE_ENABLED=true and active position, When LIVE flipped to false mid-session, Then new theses rejected; existing exit logic continues. |
| TST-RISK-010-01 | I | REQ-RISK-010 | Given any halt event, When triggered, Then SES alert sent. |
| TST-RISK-011-01 | I | REQ-RISK-011 | Given dashboard `/api/health`, When fetched, Then halt status surfaced per (bot, venue). |

---

## WAL — Wallet (EVM)

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-WAL-001-01 | I | REQ-WAL-001 | Given `setup-wallets` CLI, When run, Then 2 EVM wallets generated; addresses printed. |
| TST-WAL-002-01 | I | REQ-WAL-002 | Given setup-wallets ran, When inspecting Secrets Manager (moto), Then `claude-poly-bot-{env}-wallet-claude` and `-openai` exist. |
| TST-WAL-003-01 | I | REQ-WAL-003 | Given a stored secret, When EvmWalletService.load_wallet called, Then EvmWallet returned with correct address. |
| TST-WAL-004-01 | I | REQ-WAL-004 | Given dashboard /api/health, When fetched, Then USDC + MATIC balances displayed. |
| TST-WAL-005-01 | I | REQ-WAL-005 | Given USDC balance=$5, threshold=$10, When daily check runs, Then alert fires. |
| TST-WAL-006-01 | I | REQ-WAL-006 | Given MATIC=0.4, threshold=0.5, When daily check runs, Then gas alert. |
| TST-WAL-007-01 | I | REQ-WAL-007 | Given a CLOB order, When sign_clob_order called, Then valid EIP-712 signature returned. |
| TST-WAL-008-01 | I | REQ-WAL-008 | Given wallet operations, When logger flushed, Then no occurrence of private key string in logs (RedactProcessor). |
| TST-WAL-009-01 | I | REQ-WAL-009 | Given `setup-wallets` CLI, When run, Then preflight checks (Polygon RPC, Secrets Manager perms) pass before generation. |

---

## CFG — Config Service

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-CFG-001-01 | I | REQ-CFG-001 | Given empty config table, When defaults seeded, Then per-(bot, venue) rows present. |
| TST-CFG-002-01 | U | REQ-CFG-002 | Given Tier metadata in schema, When inspecting, Then 3 tiers present (1: editable, 2: env, 3: code). |
| TST-CFG-003-01 | I | REQ-CFG-003 | Given config update for `live_enabled`, When persisted, Then bot picks up on next loop iteration. |
| TST-CFG-004-01 | I | REQ-CFG-004 | Given Tier-2 fields, When set via env, Then service starts with values; Tier-1 defaults preserved. |
| TST-CFG-005-01 | U | REQ-CFG-005 | Given attempt to modify Tier-3 field via API, When patched, Then 400 (rejected). |
| TST-CFG-006-01 | I | REQ-CFG-006 | Given Tier-1 patch, When persisted, Then change visible to next bot loop. |
| TST-CFG-007-01 | I | REQ-CFG-007 | Given audit row written, When UPDATE attempted on audit table, Then DB raises (trigger). |
| TST-CFG-008-01 | I | REQ-CFG-008 | Given patch with invalid value type, When validated, Then 400. |
| TST-CFG-009-01 | I | REQ-CFG-009 | Given live_enabled patched to true, When applied, Then SES alert fires. |
| TST-CFG-010-01 | I | REQ-CFG-010 | Given /api/config?bot=claude&venue=polymarket, When fetched, Then merged effective config returned. |

---

## POLY — Polymarket Venue

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-POLY-001-01 | I | REQ-POLY-001 | Given py-clob-client mocked, When `list_active_markets` called, Then SDK invoked correctly. |
| TST-POLY-002-01 | I | REQ-POLY-002 | Given geo=US in config, When list_active called, Then US endpoint used. |
| TST-POLY-003-01 | I | REQ-POLY-003 | Given scanner runs, When `get_book` called, Then REST polling (not WS). |
| TST-POLY-004-01 | I | REQ-POLY-004 | Given open position, When subscribe_to_updates, Then WebSocket connection opened. |
| TST-POLY-005-01 | I | REQ-POLY-005 | Given Polymarket returns 503, When called, Then 3 retries with backoff. |
| TST-POLY-006-01 | I | REQ-POLY-006 | Given API call, When completed, Then metric `polymarket.api_call{endpoint, status}` emitted. |
| TST-POLY-007-01 | I | REQ-POLY-007 | Given API unreachable for 2m, When alert window crossed, Then SES alert. |

---

## ALPC — Alpaca Venue

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-ALPC-001-01 | I | REQ-ALPC-001 | Given alpaca-py mocked, When venue methods called, Then SDK invoked. |
| TST-ALPC-002-01 | I | REQ-ALPC-002 | Given live_mode=False, When connecting, Then paper-api endpoint used. |
| TST-ALPC-003-01 | I | REQ-ALPC-003 | Given (claude, alpaca) and (openai, alpaca), When loading keys, Then distinct keys per (bot × paper/live). |
| TST-ALPC-004-01 | I | REQ-ALPC-004 | Given `setup-alpaca` CLI with mocked Alpaca API, When run, Then keys validated and stored. |
| TST-ALPC-005-01 | I | REQ-ALPC-005 | Given live_enabled=False, When place_order, Then paper endpoint used. |
| TST-ALPC-006-01 | I | REQ-ALPC-006 | Given calendar refreshed, When `is_market_open` called at 14:00 ET on weekday, Then True. |
| TST-ALPC-006-02 | I | REQ-ALPC-006 | Given calendar fetched, When `is_market_open` called on Saturday, Then False. |
| TST-ALPC-007-01 | I | REQ-ALPC-007 | Given subscription tier=IEX, When stream connect, Then IEX feed used. |
| TST-ALPC-008-01 | I | REQ-ALPC-008 | Given AlpacaVenue, When isinstance(venue, Venue), Then True. |
| TST-ALPC-009-01 | I | REQ-ALPC-009 | Given /api/health, When fetched, Then equity, buying_power, day_trade_count present. |
| TST-ALPC-010-01 | I | REQ-ALPC-010 | Given buying_power < bankroll config, When daily check, Then alert. |
| TST-ALPC-011-01 | I | REQ-ALPC-011 | Given API unreachable for 2m during market hours, When alert window crosses, Then SES alert. |
| TST-ALPC-012-01 | U | REQ-ALPC-012 | Given equity=$24,000 and 3 day-trades, When pre-trade check, Then PDT_VIOLATION. |
| TST-ALPC-012-02 | U | REQ-ALPC-012 | Given equity=$25,000, When 4th day-trade attempted, Then allowed (no PDT). |
| TST-ALPC-013-01 | I | REQ-ALPC-013 | Given Alpaca operations, When logger flushed, Then no API key in logs. |

---

## VEN — Venue Abstraction

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-VEN-001-01 | U | REQ-VEN-001 | Given Venue Protocol, When PolymarketVenue/AlpacaVenue/FakeVenue, Then all isinstance(v, Venue). |
| TST-VEN-002-01 | I | REQ-VEN-002 | Given registry, When get(POLYMARKET), Then PolymarketVenue returned. |
| TST-VEN-003-01 | I | REQ-VEN-003 | Given registry, When list_all, Then 2 venues returned. |
| TST-VEN-004-01 | U | REQ-VEN-004 | Given AlpacaVenue, When is_market_open at 09:00 ET, Then False; at 10:00 ET, Then True. |
| TST-VEN-005-01 | I | REQ-VEN-005 | Given scanner loop, When iterating venues, Then operates via Venue interface only. |
| TST-VEN-006-01 | I | REQ-VEN-006 | Given bot disabled for alpaca, When list_enabled_for_bot, Then alpaca absent. |
| TST-VEN-007-01 | I | REQ-VEN-007 | Given health_check_all, When one venue raises, Then status returned for all venues with error noted. |
| TST-VEN-008-01 | U | REQ-VEN-008 | Given FakeVenue, When test queues responses, Then deterministic outputs. |

---

## LLM — LLM Abstraction

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-LLM-001-01 | U | REQ-LLM-001 | Given Strategist Protocol, When AnthropicStrategist/OpenAIStrategist/FakeStrategist, Then all isinstance(s, Strategist). |
| TST-LLM-002-01 | I | REQ-LLM-002 | Given Anthropic and OpenAI strategists, When evaluate called with same inputs, Then identical request shape. |
| TST-LLM-003-01 | I | REQ-LLM-003 | Given default config, When AnthropicStrategist evaluates, Then model=claude-opus-4-7. |
| TST-LLM-004-01 | I | REQ-LLM-004 | Given LLM response, When parsed, Then CheckResult with verdict, confidence, p_win, rationale. |
| TST-LLM-005-01 | I | REQ-LLM-005 | Given Anthropic call, When request built, Then `cache_control` on system prompt. |
| TST-LLM-006-01 | I | REQ-LLM-006 | Given news check, When called, Then web_search tool present. |
| TST-LLM-007-01 | I | REQ-LLM-007 | Given LLM response with usage, When parsed, Then tokens_in/out/cached + cost_usd populated. |
| TST-LLM-008-01 | I | REQ-LLM-008 | Given LLM error after retries, When evaluated, Then CheckResult.verdict=SKIP, error populated. |
| TST-LLM-009-01 | U | REQ-LLM-009 | Given FakeStrategist, When responses queued, Then dequeued in order. |
| TST-LLM-010-01 | I | REQ-LLM-010 | Given Polymarket prompt template, When rendered for a market, Then question + resolution_rules + book in prompt. |

---

## DASH — Dashboard API

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-DASH-001-01 | I | REQ-DASH-001 | Given app started, When GET /api/health/ping, Then 200. |
| TST-DASH-002-01 | I | REQ-DASH-002 | Given no session cookie, When GET /api/bots, Then 401. |
| TST-DASH-002-02 | I | REQ-DASH-002 | Given valid session, When GET /api/bots, Then 200. |
| TST-DASH-003-01 | I | REQ-DASH-003 | Given populated DB, When GET /api/bots/claude/venues/polymarket/positions, Then position list. |
| TST-DASH-004-01 | I | REQ-DASH-004 | Given valid PATCH config with checksum, When called, Then 200 + audit row. |
| TST-DASH-004-02 | I | REQ-DASH-004 | Given PATCH with wrong checksum, When called, Then 400. |
| TST-DASH-005-01 | I | REQ-DASH-005 | Given authenticated WebSocket connect to /api/live, When event published, Then client receives JSON message. |
| TST-DASH-006-01 | I | REQ-DASH-006 | Given invalid request, When validation fails, Then RFC 7807 problem-details JSON. |
| TST-DASH-007-01 | I | REQ-DASH-007 | Given app started, When fetching /openapi.json, Then OpenAPI 3.1 schema with all endpoints. |

---

## UI — Dashboard UI

(Frontend tests via Playwright + Vitest. EARS-traced like backend.)

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-UI-001-01 | E | REQ-UI-001 | Given app deploys, When GET /, Then HTML with React mount + Tailwind classes present. |
| TST-UI-002-01 | E | REQ-UI-002 | Given each page route, When navigated, Then page renders without errors. |
| TST-UI-003-01 | E | REQ-UI-003 | Given populated data, When visiting /, Then 4 P&L lines on chart. |
| TST-UI-004-01 | E | REQ-UI-004 | Given populated data, When visiting /, Then summary table shows 4 rows. |
| TST-UI-005-01 | E | REQ-UI-005 | Given authenticated, When visiting /bots/claude with venue tabs, Then positions/trades/decisions visible per tab. |
| TST-UI-006-01 | E | REQ-UI-006 | Given /decisions, When filtering by bot=claude, Then only claude decisions shown. |
| TST-UI-007-01 | E | REQ-UI-007 | Given /markets, When venue=polymarket, Then candidate queue + rejection list. |
| TST-UI-008-01 | E | REQ-UI-008 | Given /config, When changing max_position_pct, Then confirmation modal appears. |
| TST-UI-008-02 | E | REQ-UI-008 | Given /config, When toggling live_enabled, Then danger UX (red border + checkbox + phrase) required. |
| TST-UI-009-01 | E | REQ-UI-009 | Given /health, When loaded, Then balances + risk halts + LIVE_ENABLED visible per bot/venue. |
| TST-UI-010-01 | E | REQ-UI-010 | Given DRY mode, When dashboard loaded, Then DRY banner visible. |
| TST-UI-011-01 | E | REQ-UI-011 | Given P&L update event, When pushed via WS, Then chart updates without reload. |
| TST-UI-012-01 | E | REQ-UI-012 | Given unauthenticated, When visiting /, Then redirect to /api/auth/login. |
| TST-UI-013-01 | E | HLD §5.4 / R17 | Given LLM rationale containing `<script>`, When rendered, Then escaped as text (no script execution). |

---

## AUTH — Authentication

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-AUTH-001-01 | I | REQ-AUTH-001 | Given visit /api/auth/login, When called, Then 302 to GitHub authorize_url. |
| TST-AUTH-002-01 | I | REQ-AUTH-002 | Given allowlist=[yaw.etse@gmail.com], When OAuth completes for that email, Then session issued. |
| TST-AUTH-003-01 | I | REQ-AUTH-003 | Given OAuth completes for non-allowlisted email, Then 403 + auth_event=login_denied. |
| TST-AUTH-004-01 | I | REQ-AUTH-004 | Given session cookie set, When inspected, Then HttpOnly + Secure + SameSite=Lax. |
| TST-AUTH-004-02 | I | REQ-AUTH-004 | Given expired session JWT, When verified, Then None returned. |
| TST-AUTH-005-01 | I | REQ-AUTH-005 | Given `setup-oauth` CLI, When run, Then walk-through prompts + secrets stored. |
| TST-AUTH-006-01 | I | REQ-AUTH-006 | Given setup-oauth, When run, Then dev + prod callback URLs printed. |
| TST-AUTH-007-01 | I | REQ-AUTH-007 | Given login attempt, When persisted, Then auth_events row written. |

---

## OBS — Observability

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-OBS-001-01 | I | REQ-OBS-001 | Given log emit, When captured, Then JSON-parseable with all required fields. |
| TST-OBS-002-01 | I | REQ-OBS-002 | Given log within correlation_id context, When emitted, Then correlation_id field set. |
| TST-OBS-003-01 | I | REQ-OBS-003 | Given log containing api_key field, When emitted, Then [REDACTED]. |
| TST-OBS-003-02 | I | REQ-OBS-003 | Given log message containing pattern matching `0x[64-hex]`, When emitted, Then redacted. |
| TST-OBS-004-01 | I | REQ-OBS-004 | Given each of 11 alert event types, When triggered, Then SES email sent (moto). |
| TST-OBS-004-02 | I | REQ-OBS-004 | Given same alert fires 100x in 15min, When dedup, Then only 1 email sent. |
| TST-OBS-005-01 | I | REQ-OBS-005 | Given 08:00 UTC timer, When fires, Then daily summary email contains 4-stream P&L. |
| TST-OBS-006-01 | I | REQ-OBS-006 | Given decisions older than 90 days, When archive task runs, Then archived to S3 + deleted from Postgres. |
| TST-OBS-007-01 | I | REQ-OBS-007 | Given scanner run, When metrics flushed, Then EMF JSON contains scanner.runs counter. |

---

## INF — Infrastructure

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-INF-001-01 | I | REQ-INF-001 | Given CFN templates, When `cfn-lint` runs, Then no errors. |
| TST-INF-002-01 | I | REQ-INF-002 | Given root.yaml deployed in dev, When inspecting, Then resources prefixed `claude-poly-bot-dev-*`. |
| TST-INF-003-01 | I | REQ-INF-003 | Given root.yaml deployed, When inspecting, Then VPC/RDS/ECS/ECR/Secrets/IAM/CloudWatch/SES/ALB/Route53/ACM all present. |
| TST-INF-004-01 | I | REQ-INF-004 | Given dev + prod stacks, When diffed at topology level, Then identical resource types; sizes/retention may differ. |
| TST-INF-005-01 | I | REQ-INF-005 | Given env, When ECS services listed, Then 5 always-on services present. |
| TST-INF-006-01 | I | REQ-INF-006 | Given EventBridge, When rule listed, Then daily 06:00 UTC schedule for data-refresh. |
| TST-INF-007-01 | I | REQ-INF-007 | Given a service starts, When secrets loaded, Then values match expected (via IAM). |
| TST-INF-008-01 | I | REQ-INF-008 | Given deployed stack, When inspected, Then region=us-east-1. |
| TST-INF-009-01 | I | REQ-INF-009 | Given prod RDS, When described, Then BackupRetentionPeriod=7. |
| TST-INF-010-01 | I | REQ-INF-010 | Given ALB rules, When inspected, Then `/api/*` → api TG, default → ui TG. |

---

## CICD — CI/CD

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-CICD-001-01 | I | REQ-CICD-001 | Given a PR, When pr.yml runs, Then lint+type+test+build all pass on a sample green PR. |
| TST-CICD-001-02 | I | REQ-CICD-001 | Given a PR with broken lint, Then pr.yml fails. |
| TST-CICD-002-01 | I | REQ-CICD-002 | Given push to develop, When workflow runs, Then ECR push + CFN deploy + smoke pass. |
| TST-CICD-003-01 | I | REQ-CICD-003 | Given push to main, When workflow runs (with manual approval), Then prod deploy. |
| TST-CICD-004-01 | I | REQ-CICD-004 | Given GHA runs, When AWS auth, Then OIDC token used (no long-lived secrets). |
| TST-CICD-005-01 | I | REQ-CICD-005 | Given rollback workflow dispatched with previous tag, When run, Then prior image redeployed. |
| TST-CICD-006-01 | I | REQ-CICD-006 | Given smoke test fails post-deploy, When pipeline detects, Then auto-rollback + alert. |
| TST-CICD-007-01 | I | REQ-CICD-007 | Given local docker compose up, When inspected, Then DRY_RUN=true default in env. |
| TST-CICD-008-01 | I | REQ-CICD-008 | Given .devcontainer.json, When Codespaces opens, Then deps installed in postCreateCommand. |
| TST-CICD-009-01 | I | REQ-CICD-009 | Given integration tests, When run with no network, Then all pass (mocks only). |

---

## Cross-Cutting Tests

These tests validate cross-component invariants from HLD:

| Test ID | Type | Validates | Description |
|---|---|---|---|
| TST-XCUT-001 | I | DD-017 (per-bot claims) | Given a candidate, When both bots claim, Then 2 distinct candidate_claims rows; both bots' theses produced. |
| TST-XCUT-002 | I | DD-019 (correlation IDs) | Given a candidate processed by both bots, When inspecting decisions, Then deterministic decision_correlation_id per bot. |
| TST-XCUT-003 | I | DD-020 (idempotent submit) | Given a place_order with duplicate client_order_id, When submitted, Then DuplicateClientOrderIdError raised at repo. |
| TST-XCUT-004 | I | HLD §5.6 (startup reconcile) | Given a PENDING order in DB and missing from venue, When bot starts, Then marked LOST + alert. |
| TST-XCUT-005 | I | HLD §5.6 (startup reconcile) | Given an open position on venue but missing in DB, When bot starts, Then marked ADOPTED + alert. |
| TST-XCUT-006 | I | HLD §5.1 (RDS retry) | Given DB unreachable for 30s, When loop wraps in retrying_db, Then loop pauses; recovers when DB returns. |
| TST-XCUT-007 | I | HLD §5.4 (WS auth) | Given WS connect with no cookie, When upgrade, Then close 1008. |
| TST-XCUT-008 | I | HLD §5.4 (Origin allowlist) | Given WS connect with bad Origin, When upgrade, Then close 1008. |
| TST-XCUT-009 | I | HLD §5.6 (clock port) | Given FakeClock advancing across UTC midnight, When evaluating drawdown, Then daily reset boundary correct. |
| TST-XCUT-010 | I | HLD §5.6 (queue backpressure) | Given queue depth > 50 per bot, When scanner runs, Then publication paused; metric incremented. |

---

## Summary

| Category | # Tests |
|---|---|
| DATA | 14 |
| SCAN | 22 |
| BRN | 18 |
| EXE | 21 |
| EXIT | 18 |
| RISK | 14 |
| WAL | 9 |
| CFG | 10 |
| POLY | 7 |
| ALPC | 14 |
| VEN | 8 |
| LLM | 10 |
| DASH | 9 |
| UI | 14 |
| AUTH | 8 |
| OBS | 9 |
| INF | 10 |
| CICD | 10 |
| XCUT | 10 |
| **Total** | **235** |

**Coverage check:**
- Every P0 REQ has ≥ 1 test ✔
- Every P0 REQ has at least 1 happy-path + 1 edge-case test (boundary, error, or alternative path)
- HLD design decisions (DD-017, DD-019, DD-020, DD-021) covered via XCUT tests
- HLD cross-cutting concerns (§5.1 RDS retry, §5.4 WS auth, §5.6 reconciliation) covered

---

## Self-Review Findings (Test Spec)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | MED | TST-XCUT-006 (RDS retry) is hard to test deterministically without controlling Postgres availability | Use docker network manipulation or mock the connection at SQLAlchemy level; document approach |
| 2 | MED | TST-UI-013 (XSS) needs a malicious LLM rationale fixture | Construct a fake decision with `<script>` payload; assert React renders escaped text |
| 3 | LOW | Property tests need bounded input domains; hypothesis settings configured | Document `hypothesis.settings` per file |
| 4 | LOW | Several integration tests require live API keys (gated by `INTEGRATION_LIVE=1`) | Document env-flag policy in README |
| 5 | LOW | Frontend Playwright tests require running the full stack | Use docker-compose in CI; cache builds for speed |

---

## Open Items (Test Spec)

- Decide on coverage gate for CI: 90%? 100%? Default: **fail CI on any P0 REQ without a passing test** (Phase 7 traceability automation handles this).
- Decide on flaky-test policy: retry once? Document.
- Decide on hypothesis `max_examples` defaults: **200 for fast tests, 50 for slow**.
