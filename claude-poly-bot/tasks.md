# claude-poly-bot — Task List (Jira-Ready)

**Format:** Hybrid — one story per milestone, with sub-tasks per logical work unit.
**Story template:** `As a [user], I want [capability], so that [benefit].`
**Estimates:** T-shirt sizes (S, M, L, XL).
**Default Epic:** `claude-poly-bot-v1`
**Common labels:** `backend`, `frontend`, `infra`, `risk-critical`, `experiment`, `dry-run-only`, `live-money`, `observability`.

---

### TASK-001 (M0): Foundation — repo skeleton, devcontainer, CI scaffolding

**Story:** As a developer, I want a working repo with deps installed, devcontainer configured, lint/type/test running locally and in CI, so that I can begin implementing components against a stable foundation.

**Priority:** P0 · **Estimate:** M · **Phase:** M0 · **Dependencies:** None
**Labels:** `infra`, `backend`, `frontend`

**Requirements Covered:**
- REQ-CICD-001 (PR pipeline lint+type+test+build)
- REQ-CICD-007 (`docker compose up` with DRY_RUN default)
- REQ-CICD-008 (devcontainer for Codespaces / Claude Code Web)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-001-01 | When a developer clones the repo and runs `docker compose up`, the system shall start Postgres, MailHog (or LocalStack), and stub bot/api/ui containers. |
| AC-001-02 | When a developer runs `pytest` locally, the system shall execute the (initially empty) test suite to green completion. |
| AC-001-03 | When a pull request is opened, the system shall run lint (`ruff`, `eslint`), type-check (`mypy --strict`, `tsc --noEmit`), unit tests, and Docker build (no push) and report status. |
| AC-001-04 | When `.devcontainer/devcontainer.json` is present, GitHub Codespaces shall provision a workspace with Python 3.12, Node 22, AWS CLI, and Docker-in-Docker. |
| AC-001-05 | If lint or type-check fails, then the CI pipeline shall fail the PR check. |

**Definition of Done:**
- [ ] `python/pyproject.toml` with all v1 deps locked via `uv lock`
- [ ] `frontend/package.json` with all deps locked
- [ ] `alembic/env.py` configured; empty initial migration
- [ ] `docker-compose.yml` with `db`, `mailhog`, stub `bot`, `api`, `ui`
- [ ] `Dockerfile.bot`, `Dockerfile.api`, `Dockerfile.ui` build successfully
- [ ] `.devcontainer/devcontainer.json` working in Codespaces
- [ ] `.github/workflows/pr.yml` runs all jobs
- [ ] `ruff`, `mypy --strict`, `eslint`, `tsc` configured and passing on empty code
- [ ] `pytest` runs green on empty suite
- [ ] README documents local dev setup

---

### TASK-002 (M1): Polymarket Scanner skeleton

**Story:** As an operator, I want a scanner that fetches Polymarket markets, scores them by gap/depth/time, and writes accepted candidates to a queue, so that the brain has a curated input stream.

**Priority:** P0 · **Estimate:** L · **Phase:** M1 · **Dependencies:** TASK-001
**Labels:** `backend`, `experiment`

**Requirements Covered:**
- REQ-SCAN-001..009 (Polymarket parts of scanner)
- REQ-POLY-001..006 (Polymarket client read-only ops)
- REQ-VEN-001..008 (Venue protocol + Polymarket impl)
- domain/models (PolymarketMarket, Book, ScanScore, Candidate, MarketScanRun)
- domain/scoring (Polymarket scoring + filters)
- domain/clock (Clock port)
- storage (db, orm partial: candidate_queue, market_scans; CandidateRepo, scans repo)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-002-01 | When the scanner timer fires every 300 seconds (configurable), the system shall fetch all active Polymarket markets via py-clob-client. |
| AC-002-02 | The system shall reject markets failing any of: min gap (default 0.07), min depth (default $500 USDC), min hours-to-resolution (default 4), max hours-to-resolution (default 168). |
| AC-002-03 | When a market is rejected, the system shall persist the rejection reason to `market_scans`. |
| AC-002-04 | When a market is accepted, the system shall publish a `Candidate` row to `candidate_queue` and a `MarketScanRun` summary row. |
| AC-002-05 | If the Polymarket API returns 5xx, then the system shall retry up to 3 times with exponential backoff before skipping the scan and emitting an error log. |
| AC-002-06 | When the operator runs `claude-poly-bot scanner` (one-shot debug mode), the system shall execute one scan cycle and exit. |

**Definition of Done:**
- [ ] `domain/models.py` (subset: PolymarketMarket, Book, ScanScore, Candidate, MarketScanRun)
- [ ] `domain/clock.py` with `RealClock`, `FakeClock`, helpers
- [ ] `domain/scoring.py` Polymarket branch + filter logic
- [ ] `storage/db.py` with engine + `transaction()` + `retrying_db()`
- [ ] `storage/orm.py` for candidate_queue + market_scans
- [ ] Alembic migration 0001 applied
- [ ] `storage/repos/queue.py` (CandidateRepo subset for publish)
- [ ] `venues/polymarket/venue.py` read ops (`list_active_markets`, `get_book`, `get_market_data`, `health_check`)
- [ ] `bot/loops/scanner.py` with cadence loop
- [ ] CLI: `claude-poly-bot scanner` (debug-mode one-shot)
- [ ] Unit tests for scoring (Polymarket) with property tests
- [ ] Integration test: scanner publishes to candidate_queue against testcontainers Postgres
- [ ] Verify against live Polymarket API in dev with manual run

---

### TASK-003 (M2): Claude brain in DRY mode

**Story:** As an operator, I want a Claude-powered brain that consumes the candidate queue, runs 4 checks × 3 sub-agents per market, and persists theses with full decision logs, so that I can verify the LLM pipeline produces reasoning before any execution.

**Priority:** P0 · **Estimate:** XL · **Phase:** M2 · **Dependencies:** TASK-002
**Labels:** `backend`, `experiment`, `risk-critical`

**Requirements Covered:**
- REQ-BRN-001..018 (Polymarket variants)
- REQ-LLM-001..010 (Strategist Protocol, AnthropicStrategist, FakeStrategist, prompt templates)
- domain/consensus, domain/thesis
- storage/repos: decisions, theses, target_wallets (read-only seed)
- DD-017 (per-bot candidate_claims)
- DD-019 (correlation IDs)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-003-01 | When a candidate is claimed by the Claude bot, the system shall run the 4 checks (base_rate, news, whale, disposition) in parallel via the Strategist port. |
| AC-003-02 | The system shall run 3 sub-agent LLM calls (arbitrage, convergence, whale_copy) in parallel after checks complete. |
| AC-003-03 | When all 7 LLM calls complete, the system shall generate a thesis if 3-of-4 checks agree on verdict and mean confidence ≥ 0.75 (configurable); otherwise SKIP. |
| AC-003-04 | The system shall persist every LLM call (prompt, response, model_id, tokens, cost, latency) to `decisions` with `correlation_id = uuid5(scan_correlation_id, bot)`. |
| AC-003-05 | If an LLM returns malformed JSON, then the system shall retry up to 2 times before emitting a SKIP CheckResult with the error logged. |
| AC-003-06 | The Anthropic strategist shall enable prompt caching on the system prompt of every call. |
| AC-003-07 | If the LLM provider returns 5+ consecutive errors, then the system shall halt that bot's decisioning. |

**Definition of Done:**
- [ ] `domain/consensus.py` + `domain/thesis.py` with property tests
- [ ] `llm/prompts/polymarket/{base_rate,news,whale,disposition,arbitrage,convergence,whale_copy}.md`
- [ ] `llm/anthropic_impl.py` with prompt caching, JSON output, retry logic
- [ ] `llm/mocks/fake_strategist.py` for tests
- [ ] `bot/loops/thesis.py` with `claim_next` + 4×3 fan-out
- [ ] `storage/orm.py` + repos for decisions, theses, candidate_claims, target_wallets
- [ ] Alembic migration adds these tables
- [ ] Integration test using FakeStrategist: 4 BUY checks → thesis produced
- [ ] Live Anthropic call test gated by `INTEGRATION_LIVE=1`
- [ ] Sustained-error halt test (5 consecutive failures)
- [ ] Daily LLM spend tracking (incremental — full RISK in TASK-004)

---

### TASK-004 (M3): Risk + Executor (simulated)

**Story:** As an operator, I want pre-trade risk evaluation and Kelly-sized simulated orders, so that I can verify position sizing and halt logic without risking real money.

**Priority:** P0 · **Estimate:** L · **Phase:** M3 · **Dependencies:** TASK-003
**Labels:** `backend`, `risk-critical`, `dry-run-only`

**Requirements Covered:**
- REQ-EXE-001..014 (simulated paths)
- REQ-RISK-001..011 (all halt scopes)
- REQ-CFG-001..013 (Tier 1 fields, audit, validation, defaults seed)
- REQ-WAL-007 (signing primitives — loaded but not used yet)
- domain/kelly + domain/risk

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-004-01 | When a thesis is approved, the system shall compute Kelly fraction f* and cap at quarter-Kelly (default 0.25). |
| AC-004-02 | If Kelly f* ≤ 0, then the system shall skip the trade with reason NEGATIVE_EV. |
| AC-004-03 | The system shall apply consensus sizing (FULL / HALF / SKIP) from sub-agent votes before placing the simulated order. |
| AC-004-04 | While DRY_RUN is active for a (bot, venue) pair, the system shall persist orders with status=SIMULATED but not call the venue. |
| AC-004-05 | If daily drawdown reaches 50% of starting bankroll, then the system shall halt the (bot, venue) pair until 00:00 UTC and emit an alert. |
| AC-004-06 | If max open positions (default 5) is already reached, then the system shall reject new trades with reason MAX_OPEN_POSITIONS. |
| AC-004-07 | If max position % (default 25%) is exceeded, then the system shall cap the size at the limit. |
| AC-004-08 | When LIVE_ENABLED is toggled off mid-session, the system shall stop opening new positions but continue exit logic on existing positions. |
| AC-004-09 | If daily LLM spend cap (default $20/bot/day) is reached, then the system shall halt that bot's decisioning. |
| AC-004-10 | If the operator-set Alpaca PDT predicate would be violated, then the system shall reject the trade with reason PDT_VIOLATION. |

**Definition of Done:**
- [ ] `domain/kelly.py` with hypothesis property tests
- [ ] `domain/risk.py` with property tests covering all halt scopes
- [ ] `bot/loops/executor.py` with simulated path
- [ ] `wallet/evm.py` (loaded only; no signing yet)
- [ ] `config/{schema,service,defaults}.py` with full Tier 1 schema
- [ ] `storage/repos/{positions,orders,trades,risk_halts,bankroll}.py`
- [ ] `api/routes/config.py` PATCH endpoint with checksum (skeletal — full UI in TASK-010)
- [ ] Integration test: forced 50% drawdown halts that pair only (other pairs continue)
- [ ] Integration test: LLM spend cap halts decisioning
- [ ] Integration test: simulated order persisted with status=SIMULATED
- [ ] UTC-boundary test using FakeClock advancing across midnight

---

### TASK-005 (M4): Real Polymarket execution path

**Story:** As an operator, I want to verify that real EIP-712 order signing and submission to Polymarket works end-to-end with a tiny test trade and that container restarts don't strand orders, so that I can trust the live execution path.

**Priority:** P0 · **Estimate:** L · **Phase:** M4 · **Dependencies:** TASK-004
**Labels:** `backend`, `risk-critical`, `live-money`

**Requirements Covered:**
- REQ-EXE-008 (signing)
- REQ-EXE-009 (recording venue order ID)
- REQ-WAL-001..009 (CLI + storage + signing)
- HLD §5.6 (startup reconciliation)
- DD-020 (store-before-submit idempotency)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-005-01 | When the operator runs `claude-poly-bot setup-wallets`, the system shall generate a fresh EVM wallet for each bot, print the public address, and write the private key to AWS Secrets Manager (or `.env` for `LOCAL=1`). |
| AC-005-02 | If a wallet already exists at the secret path, then the `setup-wallets` command shall require typing `yes` to overwrite. |
| AC-005-03 | When `place_order` is called with LIVE_ENABLED=true, the system shall first persist `orders` row with status=PENDING, then sign and submit to Polymarket, then update the row with venue_order_id. |
| AC-005-04 | If the bot container restarts while an order is PENDING, then on startup the system shall query the venue for that `client_order_id` and reconcile to FILLED, CANCELLED, or LOST. |
| AC-005-05 | If a position exists in DB but not on the venue, then the system shall mark it ORPHANED and emit an alert. |
| AC-005-06 | If a position exists on the venue but not in DB, then the system shall mark it ADOPTED and emit an alert. |

**Definition of Done:**
- [ ] `cli/setup_wallets.py` with pre-flight + overwrite confirmation
- [ ] `wallet/evm.py` real signing via eth-account
- [ ] `venues/polymarket/venue.place_order` real submit path
- [ ] `bot/runner.py` startup reconciliation logic (orders + positions)
- [ ] Integration test using FakeVenue: simulated mid-flight crash → reconcile finds the pending order
- [ ] **Manual real-money test**: place a $5 USDC order on a low-stakes Polymarket market in dev; verify fill; verify reconcile after restart
- [ ] Document the manual test result in `runbook.md`

---

### TASK-006 (M5): Polymarket Exit Engine

**Story:** As an operator, I want exit triggers (target-hit, volume-spike, stale-thesis, market-resolved) to fire correctly on Polymarket positions and a WebSocket subscription that survives reconnects, so that positions close at the right moments.

**Priority:** P0 · **Estimate:** L · **Phase:** M5 · **Dependencies:** TASK-005
**Labels:** `backend`, `risk-critical`

**Requirements Covered:**
- REQ-EXIT-001..004, REQ-EXIT-007..013 (Polymarket exits)
- REQ-POLY-004 (WebSocket)
- REQ-EXIT-008, REQ-EXIT-011 (reconnect)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-006-01 | When the exit timer fires every 60 seconds, the system shall evaluate every open position for the configured exit triggers in priority order. |
| AC-006-02 | If current price ≥ entry + (target − entry) × 0.85, then the system shall close the position with reason TARGET_HIT. |
| AC-006-03 | If volume in the trailing 10 minutes ≥ 3× rolling 20-day average, then the system shall close the position with reason VOLUME_EXIT. |
| AC-006-04 | If a position is older than 24 hours and absolute price change since entry < 2%, then the system shall close the position with reason STALE_THESIS. |
| AC-006-05 | When a Polymarket market resolves while a position is still open, the system shall close the position with reason MARKET_RESOLVED. |
| AC-006-06 | If the WebSocket disconnects, then the system shall fall back to REST polling and attempt reconnect with exponential backoff up to 5 attempts before alerting. |
| AC-006-07 | While LIVE_ENABLED is false, the exit engine shall still evaluate triggers and close simulated positions for accurate DRY P&L. |

**Definition of Done:**
- [ ] `bot/loops/exit.py` with all 4 Polymarket triggers
- [ ] `venues/polymarket/stream.py` with reconnect logic
- [ ] WebSocket worker registry tied to open positions
- [ ] Volume-window aggregator (rolling 10-min)
- [ ] 20-day rolling average volume source defined
- [ ] Integration tests for each trigger using FakeVenue + FakeClock
- [ ] Reconnect test with simulated drop
- [ ] DRY-mode exit accounting test

---

### TASK-007 (M6): OpenAI bot in parallel

**Story:** As an operator, I want both Claude and OpenAI bots running independently against the shared scanner, so that I can compare their decisions on identical market inputs.

**Priority:** P0 · **Estimate:** M · **Phase:** M6 · **Dependencies:** TASK-006
**Labels:** `backend`, `experiment`

**Requirements Covered:**
- REQ-LLM-002 (OpenAIStrategist)
- REQ-LLM-004, REQ-LLM-007 (JSON output, cost tracking)
- DD-017 (per-bot candidate_claims correctness)
- DD-018 (shared scanner / independent evaluation)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-007-01 | When the scanner publishes a candidate, both bots shall independently claim and process it via per-bot `candidate_claims` rows. |
| AC-007-02 | The system shall produce a `decision_correlation_id = uuid5(scan_correlation_id, bot)` deterministically per (candidate, bot). |
| AC-007-03 | The OpenAI strategist shall use structured outputs (`response_format=json_schema, strict=true`) to guarantee schema-conformant JSON. |
| AC-007-04 | The OpenAI strategist shall use the SAME prompts, temperature, retries, and web-search policy as the Anthropic strategist (provider parity for fair comparison). |
| AC-007-05 | When both bots complete a candidate, their decisions shall share `scan_correlation_id` enabling A/B comparison queries. |

**Definition of Done:**
- [ ] `llm/openai_impl.py` mirroring AnthropicStrategist contract
- [ ] Provider parity test (identical request shape)
- [ ] E2E test: scanner publishes 1 candidate → both bots produce theses → both decision rows match `scan_correlation_id`
- [ ] Cost tracking comparison verified (both report `cost_usd`)
- [ ] Local docker-compose runs both bots simultaneously

---

### TASK-008 (M7): Alpaca venue — equities trading

**Story:** As an operator, I want the bots to also trade US equities via Alpaca (paper mode by default, with bracket stops, market-hours gating, EOD flatten), so that I can compare LLM strategies across venue types.

**Priority:** P0 · **Estimate:** XL · **Phase:** M7 · **Dependencies:** TASK-007
**Labels:** `backend`, `risk-critical`, `experiment`

**Requirements Covered:**
- REQ-ALPC-001..013
- REQ-VEN-001..008 (Alpaca implementation conformance)
- REQ-EXE-006 (limit + market fallback), REQ-EXE-015 (bracket stop)
- REQ-EXIT-005 (STOP_LOSS), REQ-EXIT-006 (HORIZON_EXIT), REQ-EXIT-014 (EOD_FLATTEN)
- REQ-SCAN-010..013 (Alpaca scoring + filters)
- REQ-BRN-004 (unusual_volume check replacing whale)
- REQ-BRN-007 (target/stop/horizon thesis fields)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-008-01 | When the operator runs `claude-poly-bot setup-alpaca`, the system shall walk through key paste-in for each (bot × paper/live) tier and validate via `GET /v2/account`. |
| AC-008-02 | When the Alpaca scanner runs outside 09:30–16:00 ET on a trading day, the system shall suspend the scan. |
| AC-008-03 | The system shall score Alpaca equities on relative volume, price momentum, and dollar volume; reject any below configured thresholds. |
| AC-008-04 | When an Alpaca entry order fills, the system shall submit a server-side bracket stop-loss order at the LLM-provided `stop_price`. |
| AC-008-05 | If a limit order is unfilled after `order_ttl_sec` (default 300s), then the system shall cancel and submit a market order as fallback. |
| AC-008-06 | If the current price hits the stop_price (server-side or client-side check), then the system shall close the position with reason STOP_LOSS. |
| AC-008-07 | If a position's horizon (configurable, default 72h) elapses, then the system shall close at market with reason HORIZON_EXIT. |
| AC-008-08 | If the time is ≥ 15:55 ET on a trading day with `allow_overnight_holds=False`, then the system shall close all Alpaca positions with reason EOD_FLATTEN. |
| AC-008-09 | If account equity < $25,000 and recent day-trade count ≥ 3, then the system shall reject new trades with reason PDT_VIOLATION. |
| AC-008-10 | LIVE_ENABLED for (bot, alpaca) shall route to the live endpoint; otherwise to the paper endpoint. |

**Definition of Done:**
- [ ] `venues/alpaca/{venue,stream,calendar}.py`
- [ ] `cli/setup_alpaca.py`
- [ ] `domain/scoring.py` Alpaca branch
- [ ] `bot/loops/exit.py` STOP_LOSS + HORIZON_EXIT + EOD_FLATTEN triggers
- [ ] `domain/risk.py` PDT predicate
- [ ] `llm/prompts/alpaca/*` prompts with target/stop/horizon JSON fields
- [ ] Integration tests: each trigger fires correctly with FakeClock + FakeVenue
- [ ] PDT property test
- [ ] Live paper-account integration test gated by `INTEGRATION_LIVE=1`

---

### TASK-009 (M8): Dashboard MVP — read-only

**Story:** As an operator, I want a web dashboard with GitHub OAuth login that shows side-by-side P&L for both bots across both venues, decision logs, and system health, so that I can monitor the experiment without `psql`.

**Priority:** P0 · **Estimate:** XL · **Phase:** M8 · **Dependencies:** TASK-008
**Labels:** `backend`, `frontend`

**Requirements Covered:**
- REQ-DASH-001..007 (read-only)
- REQ-UI-001..012 (read parts; config edit deferred to TASK-010)
- REQ-AUTH-001..007 (GitHub OAuth + allowlist)
- HLD §5.4 (WS auth + XSS/CSP)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-009-01 | When a user navigates to the dashboard URL without a session, the system shall redirect to GitHub OAuth. |
| AC-009-02 | When the OAuth callback completes with an email NOT in the allowlist, the system shall return HTTP 403 and log an `auth_event`. |
| AC-009-03 | When an authenticated operator visits `/`, the system shall render side-by-side cumulative P&L charts for all 4 (bot, venue) streams. |
| AC-009-04 | When an operator visits `/bots/{name}`, the system shall render venue tabs with positions, trades, recent decisions including LLM prompt/response. |
| AC-009-05 | When an operator visits `/decisions`, the system shall list every LLM call with filters by bot, venue, check, verdict, date. |
| AC-009-06 | When an operator opens the WebSocket `/api/live`, the system shall validate the session cookie and Origin header before accepting; deny with code 1008 if either fails. |
| AC-009-07 | The dashboard shall render LLM-output text as text nodes only (no `dangerouslySetInnerHTML`); CSP `default-src 'self'` shall be set on all responses. |
| AC-009-08 | The dashboard shall display a prominent banner per (bot, venue) indicating DRY or LIVE mode. |

**Definition of Done:**
- [ ] `cli/setup_oauth.py`
- [ ] `auth/{oauth,session}.py` with JWT
- [ ] `api/main.py` with all middleware (Auth, Errors, RequestId, CSP, CORS, Logging)
- [ ] `api/routes/{bots,markets,health,auth}.py` (read-only)
- [ ] `api/websocket.py` `/api/live` with auth + Origin check
- [ ] OpenAPI 3.1 schema verified
- [ ] Frontend pages: `/`, `/bots/[name]`, `/decisions`, `/markets`, `/health`
- [ ] OpenAPI codegen → `lib/types.ts`
- [ ] WebSocket client with reconnect
- [ ] Playwright E2E: log in, navigate, see chart with mocked WS
- [ ] ESLint rule `react/no-danger: error` enforced
- [ ] CSP header verified in integration test

---

### TASK-010 (M9): Dashboard config editor

**Story:** As an operator, I want to edit Tier-1 config (including the LIVE_ENABLED toggle) from the dashboard with confirmation prompts and an audit log, so that I can adjust risk parameters and trading mode without redeploying.

**Priority:** P0 · **Estimate:** M · **Phase:** M9 · **Dependencies:** TASK-009
**Labels:** `backend`, `frontend`, `risk-critical`

**Requirements Covered:**
- REQ-DASH-004 (PATCH config)
- REQ-CFG-009 (apply on next loop), REQ-CFG-010 (audit), REQ-CFG-011 (validation), REQ-CFG-012 (alert on live-toggle)
- REQ-UI-008 (config editor UI)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-010-01 | When the operator submits a config patch via the dashboard, the system shall validate type/range against the Pydantic schema and return 400 if invalid. |
| AC-010-02 | The system shall require a `confirmation_checksum` matching `sha256(field + str(new_value))[:8]` and return 400 on mismatch. |
| AC-010-03 | When a config patch succeeds, the system shall persist the change AND insert a row in `config_audit` with timestamp, actor email, field, old value, new value. |
| AC-010-04 | When `live_enabled` is toggled, the system shall emit an SES alert. |
| AC-010-05 | When a Tier-1 config field changes, the bot shall pick up the new value on the next event-loop iteration. |
| AC-010-06 | The LIVE-toggle UI shall require typing a confirmation phrase AND checking an "I understand real money is at risk" checkbox before the submit button enables. |
| AC-010-07 | The dashboard shall display the audit log paginated alongside the config form. |

**Definition of Done:**
- [ ] `api/routes/config.py` PATCH + audit endpoints
- [ ] Frontend `app/config/page.tsx` with type-validated form
- [ ] `<ConfirmationModal>` component requiring confirmation phrase
- [ ] LIVE-toggle distinct UX (red border + danger banner + checkbox)
- [ ] Audit log panel
- [ ] Integration tests: change persists, audit row written, alert fires for live-toggle
- [ ] Validation rejection tests

---

### TASK-011 (M10): AWS deploy + CI/CD

**Story:** As an operator, I want CloudFormation-managed dev and prod environments that auto-deploy from `develop` and `main` branches via GitHub Actions, so that I can ship without manual AWS console work.

**Priority:** P0 · **Estimate:** XL · **Phase:** M10 · **Dependencies:** TASK-010
**Labels:** `infra`, `risk-critical`

**Requirements Covered:**
- REQ-INF-001..010 (CloudFormation, single AWS account, env-prefixed resources, 5 always-on services + 1 scheduled)
- REQ-CICD-001..009 (PR pipeline, develop→dev, main→prod, OIDC, smoke + rollback)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-011-01 | When code is merged to `develop`, the system shall run lint+test+build, push images to ECR, deploy to dev via CloudFormation, and run smoke tests. |
| AC-011-02 | When code is merged to `main`, the system shall do the same to prod after a manual approval gate. |
| AC-011-03 | If post-deploy smoke tests fail, then the system shall automatically roll back to the previous ECR image tag and emit an SES alert. |
| AC-011-04 | GitHub Actions shall authenticate to AWS via OIDC; no long-lived AWS keys shall be in GitHub secrets. |
| AC-011-05 | The CloudFormation stack shall provision VPC, ECS Fargate cluster, RDS Postgres, ECR, Secrets Manager, IAM, CloudWatch, ALB, Route 53, ACM, S3, EventBridge for both environments. |
| AC-011-06 | The dev and prod environments shall be identical in topology; only sizing, retention, and Alpaca paper-vs-live endpoint may differ. |
| AC-011-07 | The system shall provide a manually triggered rollback workflow that redeploys a specified ECR tag. |

**Definition of Done:**
- [ ] `infra/cloudformation/*.yaml` (root + 11 nested)
- [ ] `infra/params/{dev,prod}.json`
- [ ] `Dockerfile.bot`, `Dockerfile.api`, `Dockerfile.ui` production-ready
- [ ] `.github/workflows/{deploy-dev,deploy-prod,rollback}.yml`
- [ ] OIDC trust policy committed as a sample
- [ ] Manual one-time setup steps documented in `runbook.md` (ACM, Route 53, SES domain verification)
- [ ] Dev environment provisioned successfully
- [ ] Prod environment provisioned successfully
- [ ] Smoke tests pass on both
- [ ] Rollback tested manually

---

### TASK-012 (M11): Observability + SES alerts + daily summary

**Story:** As an operator, I want structured logs in CloudWatch, CloudWatch metrics, and SES-delivered alerts on every operationally significant event including a daily summary, so that I can run the bot without staring at a screen.

**Priority:** P0 · **Estimate:** L · **Phase:** M11 · **Dependencies:** TASK-011
**Labels:** `backend`, `observability`, `infra`

**Requirements Covered:**
- REQ-OBS-001..007
- REQ-DATA-001..009 (data refresh + target wallets fully wired with alerts)

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-012-01 | All application logs shall be emitted as structured JSON to stdout with timestamp, level, service, bot, venue, correlation_id, message. |
| AC-012-02 | The logger shall redact known secret patterns (private keys, API keys, session tokens) and field names. |
| AC-012-03 | The system shall emit SES alerts on 11 distinct event types: bot crash, risk halt, LIVE_ENABLED toggle, low USDC, low MATIC, Alpaca buying-power anomaly, LLM sustained errors, scanner failure, data-refresh failure, Polymarket unreachable ≥ 2m, Alpaca unreachable ≥ 2m. |
| AC-012-04 | When the daily-summary timer fires at 08:00 UTC, the system shall email yesterday's per-(bot, venue) P&L, trade count, win rate, and Sharpe. |
| AC-012-05 | Alerts shall de-duplicate over a 15-minute window keyed by `(alert_type, bot, venue)`. |
| AC-012-06 | The system shall emit CloudWatch metrics (counters + gauges + histograms) for scanner runs, theses generated, trades placed/filled, risk halts, LLM calls, LLM costs. |
| AC-012-07 | When the daily data refresh runs at 06:00 UTC and shrinks the target-wallet list by > 50%, the system shall ABORT and preserve the previous list. |

**Definition of Done:**
- [ ] `observability/logging.py` with RedactProcessor
- [ ] `observability/metrics.py` (CloudWatch EMF)
- [ ] `observability/alerts.py` SES + dedup
- [ ] `bot/loops/data_refresh.py` with sanity guard + advisory lock
- [ ] EventBridge rule for data-refresh
- [ ] Daily-summary scheduled task
- [ ] Integration tests using moto for SES + S3
- [ ] Manual test: force a fake risk halt → email arrives
- [ ] CloudWatch metrics dashboard configured

---

### TASK-013 (M12): Production hardening + traceability verification

**Story:** As an operator, I want every requirement traced to passing tests, hourly reconciliation running, and an incident runbook, so that I can confidently leave the bot running.

**Priority:** P0 · **Estimate:** L · **Phase:** M12 · **Dependencies:** TASK-012
**Labels:** `backend`, `risk-critical`, `observability`

**Requirements Covered:**
- All P0 REQs not yet covered: any tail items
- HLD §5.6 hourly reconciliation
- Phase 7 traceability matrix

**Acceptance Criteria (EARS):**

| AC ID | EARS Criterion |
|---|---|
| AC-013-01 | The system shall run an hourly reconciliation task that compares DB open positions to venue positions and alerts on mismatches. |
| AC-013-02 | When the operator runs the traceability checker, the system shall produce a matrix mapping every P0 REQ-* to test(s) and code-annotation(s). |
| AC-013-03 | If any P0 REQ has no passing test, then the traceability checker shall fail. |
| AC-013-04 | If any code path lacks a `# REQ:` annotation, then the static analyzer shall warn. |
| AC-013-05 | The repository shall contain a `runbook.md` with: incident response procedures, key-rotation steps, manual rollback steps, common alert remediations. |
| AC-013-06 | The system shall run for at least 24 hours in prod with `LIVE_ENABLED=true` for at least one bot before being declared production-ready. |

**Definition of Done:**
- [ ] Hourly reconciliation task added to bot runner TaskGroup
- [ ] Traceability matrix script: parses REQs, finds tests, finds code annotations
- [ ] All P0 REQs have ≥ 1 passing test
- [ ] All code paths annotated with `# REQ:`
- [ ] `runbook.md` written
- [ ] 24-hour live soak test completed in prod
- [ ] Final cost report generated (compare estimated vs actual)
- [ ] Phase 8 demo summary written

---

## Coverage Verification

Every REQ-* from `requirements.md` is covered by at least one task:

| REQ Component | Tasks |
|---|---|
| REQ-DATA-* | TASK-002 (skeleton), TASK-012 (full) |
| REQ-SCAN-* | TASK-002 (Polymarket), TASK-008 (Alpaca) |
| REQ-BRN-* | TASK-003 (Polymarket), TASK-008 (Alpaca unusual_volume), TASK-007 (OpenAI) |
| REQ-EXE-* | TASK-004 (simulated), TASK-005 (real Polymarket), TASK-008 (Alpaca-specific) |
| REQ-EXIT-* | TASK-006 (Polymarket), TASK-008 (Alpaca) |
| REQ-RISK-* | TASK-004 |
| REQ-WAL-* | TASK-005 |
| REQ-CFG-* | TASK-004 (skeleton), TASK-010 (full UI) |
| REQ-POLY-* | TASK-002 (read), TASK-005 (write) |
| REQ-ALPC-* | TASK-008 |
| REQ-VEN-* | TASK-002, TASK-008 |
| REQ-LLM-* | TASK-003 (Anthropic), TASK-007 (OpenAI) |
| REQ-DASH-* | TASK-009 (read), TASK-010 (PATCH) |
| REQ-UI-* | TASK-009 (read), TASK-010 (config) |
| REQ-AUTH-* | TASK-009 |
| REQ-OBS-* | TASK-012 |
| REQ-INF-* | TASK-011 |
| REQ-CICD-* | TASK-001 (PR), TASK-011 (deploy) |

**No orphan REQs. No orphan tasks.**

---

## Self-Review Findings (Tasks)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | MED | TASK-005 includes a real-money manual test — that's not a software acceptance criterion in the strict sense | Documented as a "Definition of Done" checkbox rather than EARS criterion (manual gate) |
| 2 | MED | TASK-008 (Alpaca) is XL — could be split into two stories (M7a: scanner/score/Alpaca client; M7b: brain integration + exits) | Acceptable as one XL for the milestone framing; sub-tasks decompose internally |
| 3 | LOW | TASK-013 has a 24-hour soak as DoD — calendar dependency, not effort | Acknowledged; acceptable |
| 4 | LOW | Some EARS criteria use "shall" + percentages (e.g., `≥ 50%`) which require careful equality wording | Reviewed all `≥` and `≤` against requirements — match boundaries explicitly |

---

## Open Items (Tasks)

- Decide if M4 should be split (TASK-005a "setup-wallets + reconciliation framework", TASK-005b "real-money manual test"). Lean: keep as one task; the manual test is a gate, not a separate work item.
- Decide if a `M7.5` task is warranted between Alpaca venue and Dashboard MVP for cross-bot diff view (per Batch 7 Finding #1). Lean: keep cross-bot diff in v1.1 scope.
