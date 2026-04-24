# claude-poly-bot — High-Level Design

**Scope:** Architecture and cross-cutting design for the dual-LLM, dual-venue trading bot defined in `requirements.md`.
**Status:** Pending approval.
**Traces to:** All REQ-* in `requirements.md`.

---

## 1. Design Goals

Ranked in priority order. Higher-priority goals win when they conflict with lower-priority goals.

| Priority | Goal | Rationale |
|---|---|---|
| 1 | **Correctness** | Trades execute as specified; positions, orders, and P&L are never lost, double-counted, or silently corrupted. Real money on the line — bugs are expensive. |
| 2 | **Observability** | Every LLM decision traceable end-to-end (prompt → response → thesis → order → fill → P&L). The core goal of the project is measuring Claude vs OpenAI — without comprehensive decision logs, the experiment fails. |
| 3 | **Testability** | Every external dependency (Polymarket, Alpaca, Claude, OpenAI, AWS services) must be mockable. Full offline test suite in CI. Operator must be able to exercise the full pipeline in DRY_RUN without any real API calls. |
| 4 | **Security** | Wallet private keys, Alpaca API keys, and LLM API keys are the highest-value secrets. Dashboard can flip LIVE_ENABLED → real-money path. Strong auth and secret isolation. |
| 5 | **Simplicity** | Solo-operator project. Prefer one well-understood tool over two clever ones. Avoid distributed-system complexity (no event bus, no microservices, no service mesh). |
| 6 | **Extensibility** | Should be straightforward to add a 3rd LLM or 3rd venue. Hexagonal architecture enforces this without additional up-front work. |
| 7 | **Performance** | Scanner cadence is 5 min and exit cadence is 60 s. None of our loops are latency-critical. Fargate-default compute is plenty. Optimize only when measured. |

## 2. Non-Goals

Explicit boundaries. We will NOT build, optimize for, or support these, even if someone asks.

| Non-Goal | Rationale |
|---|---|
| Multi-user / multi-tenant support | Solo operator only. Single allowlist email. No user management system. |
| Mobile application | Dashboard is web-only; if needed, the browser on a phone is enough. |
| Backtesting framework | Deferred to v2. DRY_RUN against live markets provides qualitative feedback; historical replay is a separate project. |
| Strategy customization UI | The 4 checks and 3 sub-agents are code. Only quantitative thresholds are editable at runtime. Changing strategy = code change + deploy. |
| Hardware wallet / MPC / multisig custody | Plain EVM private key in Secrets Manager for v1. Operator-only dashboard with OAuth means attack surface is the operator's GitHub account, not a publicly exposed wallet. |
| Futures, options, crypto (non-Polygon), FX | Two venues (Polymarket + Alpaca equities) only. Adding a 3rd venue in v2 is supported by the architecture but out of scope for v1. |
| Extended-hours or overnight equity holds | Regular session only (09:30–16:00 ET). All positions flat by 15:55 ET. Avoids overnight gap risk and complicates neither architecture nor operator mental model. |
| Real-time price triggers sub-60s | The exit engine runs every 60 seconds. Sub-second triggers (e.g., micro-structure arbitrage) are not a goal. |
| High availability / zero downtime | Single-region, single-instance RDS with daily backups. Accepted RPO: 24h. Accepted RTO: 1h. If AWS us-east-1 has a regional outage, the bot is offline. |
| Data pipeline for equities historical trades | Only Polymarket has a poly_data-style historical-wallet dataset. Alpaca equities rely on LLM knowledge + live data. |

## 3. Architecture Overview

### 3.1 Architecture Pattern

**Hexagonal Architecture (Ports and Adapters)** with async Python as the runtime model.

- **Core domain** (pure logic, no I/O): scoring, Kelly math, consensus logic, risk predicates, thesis aggregation, P&L math.
- **Ports** (Protocols defined in `domain/protocols.py`): `Venue`, `Strategist`, `ConfigStore`, `PositionRepo`, `DecisionRepo`, `AlertSink`, `Clock`.
- **Adapters** (concrete implementations of ports):
  - `venues/polymarket/venue.py` — real Polymarket via `py-clob-client`.
  - `venues/alpaca/venue.py` — real Alpaca via `alpaca-py`.
  - `venues/mocks/fake_venue.py` — in-memory fake for tests.
  - `llm/anthropic_impl.py` — real Claude via Anthropic SDK.
  - `llm/openai_impl.py` — real GPT-5 via OpenAI SDK.
  - `llm/mocks/fake_strategist.py` — scripted responses for tests.
  - `storage/*.py` — SQLAlchemy 2.0 async adapters, one per repo protocol.
  - `observability/alerts.py` — SES adapter; `fake_alert_sink` for tests.

**Why this pattern:**
- Directly implements REQ-LLM-009 (mocked Strategist), REQ-VEN-008 (mocked Venue), REQ-CICD-009 (offline tests).
- Isolates the two LLM vendors behind a single Protocol, which is the enabling architectural move for the experiment.
- Makes the "swap in a 3rd venue later" path cheap without speculative work now.

**Considered alternatives:**

| Alternative | Pros | Cons | Why Rejected |
|---|---|---|---|
| Layered (api → services → repos → db) | Familiar to most Python devs | Couples core domain to ORM and vendor SDKs; mocking requires monkey-patching | Poor testability conflicts with Goal 3 |
| Event-driven with internal pub/sub | Decouples components at runtime | Adds event-bus complexity (Redis/Kafka or in-process); trace debugging harder | Conflicts with Goal 5 (simplicity); overkill at our throughput |
| Microservices (scanner, bot, dashboard as separate codebases) | Independent deploys per component | Multiply build/CI/deploy work; solo operator can't justify | Conflicts with Goals 5 and 1 (harder to keep coherent) |

### 3.2 System Diagram

```
                     ┌────────────────────────────────┐
                     │   GitHub (source, Actions CI)  │
                     └────────────┬───────────────────┘
                                  │ OIDC
                                  ▼
┌─────────────────────────── AWS us-east-1 ────────────────────────────┐
│                                                                      │
│  ┌──── ALB ─ TLS ───┐        ┌──── EventBridge (cron) ──┐            │
│  │    claude-poly-bot-{env}.domain                      │            │
│  └──┬────────┬──────┘        └────────────┬─────────────┘            │
│     │ /api/* │ others                     │ daily 06:00 UTC          │
│     ▼        ▼                            ▼                          │
│  ┌─────┐  ┌──────┐                  ┌──────────────┐                 │
│  │DASH │  │  UI  │                  │data-refresh  │  (ECS task)     │
│  │ API │  │ SSR  │                  │  scheduled   │                 │
│  └──┬──┘  └──┬───┘                  └──────┬───────┘                 │
│     │         │                             │                        │
│     └─┬───────┘                             │                        │
│       │                                     │                        │
│       │       ┌────────── ECS Fargate ──────┼──────────┐             │
│       │       │                             │          │             │
│       │       │  ┌────────┐  ┌───────────┐ │          │             │
│       │       │  │scanner │  │claude-bot │ │          │             │
│       │       │  └───┬────┘  └────┬──────┘ │          │             │
│       │       │      │            │        │          │             │
│       │       │      │       ┌────┴──────┐ │          │             │
│       │       │      │       │openai-bot │ │          │             │
│       │       │      │       └────┬──────┘ │          │             │
│       │       └──────┼────────────┼────────┘          │             │
│       ▼              ▼            ▼                   ▼             │
│   ┌──────────── RDS Postgres ─────────────┐      ┌──────┐           │
│   │ positions, orders, trades, decisions, │      │  S3  │           │
│   │ candidate_queue, config, audit, …     │      │ data │           │
│   └────────────────┬──────────────────────┘      └──────┘           │
│                    │                                                │
│            ┌───────┴───────┐   ┌───────────────┐                    │
│            │Secrets Manager│   │ CloudWatch    │                    │
│            │  keys, OAuth  │   │ logs+metrics  │                    │
│            └───────────────┘   └───────────────┘                    │
│                                                                     │
│   ┌──── SES ────┐                                                   │
│   │  alerts,    │                                                   │
│   │  summaries  │                                                   │
│   └─────────────┘                                                   │
└─────────────────────────────────────────────────────────────────────┘
                  │                 │                      │
                  ▼                 ▼                      ▼
       ┌────────────────┐   ┌──────────────┐   ┌─────────────────────┐
       │  Polymarket    │   │   Alpaca     │   │ Anthropic + OpenAI  │
       │  CLOB + WS     │   │  Broker API  │   │   APIs (+ search)   │
       └────────────────┘   └──────────────┘   └─────────────────────┘
```

### 3.3 Component Overview

| Component | Service/Container | Responsibility | Owns Data? | Key Interfaces |
|---|---|---|---|---|
| scanner | `scanner` ECS service | Polls all venues, filters, publishes to candidate queue | No (writes candidate_queue) | Consumes: `Venue.list_active_markets()`. Publishes: `candidate_queue` rows. |
| claude-bot | `claude-bot` ECS service | Runs thesis + executor + exit loops for Claude | Yes (own positions, orders, decisions, bankrolls) | Consumes: candidate_queue, Strategist(Anthropic), Venue. Publishes: orders, decisions, positions. |
| openai-bot | `openai-bot` ECS service | Runs thesis + executor + exit loops for OpenAI | Yes (own positions, orders, decisions, bankrolls) | Mirrors claude-bot. |
| data-refresh | EventBridge-scheduled ECS task | Daily Polymarket trade dataset refresh + target wallet recompute | Writes: target_wallets, S3 parquet | Daily at 06:00 UTC. |
| dashboard-api | `dashboard-api` ECS service | FastAPI REST + WebSocket | No (reads all, writes config/audit) | HTTP/WS clients from UI. |
| dashboard-ui | `dashboard-ui` ECS service | Next.js SSR frontend | No | Human browser clients. |
| RDS Postgres | `db` | Durable state for everything except cold data | Yes — authoritative for positions, orders, decisions, config, audit, candidate_queue, target_wallets, auth_events | Accessed via SQLAlchemy from all services. |
| S3 | `trade-data` bucket | Cold storage: poly_data parquet, archived LLM logs | Yes | Boto3 from data-refresh and archiver. |
| Secrets Manager | secrets | LLM keys, EVM private keys, Alpaca key pairs per-bot per-mode, OAuth client secret, session secret | Yes | Retrieved at service startup. |

### 3.4 Primary Data Flow

**Scenario: a single Polymarket market is evaluated and traded by the Claude bot.**

1. **t=0** — Scanner timer fires (every 300 s).
2. Scanner iterates registered venues. For `polymarket`: `venue.list_active_markets()` → fetches via `py-clob-client` REST.
3. For each market: scanner computes gap, depth, hours_to_resolution. Applies filters (REQ-SCAN-003). Rejections logged to `market_scans`.
4. Accepted markets inserted into `candidate_queue` table with `venue='polymarket'`, `status='new'`.
5. **t=~10s** — `claude-bot`'s `thesis_loop` finds new candidates: for each `candidate_queue` row without a `(candidate_id, bot='claude')` entry in `candidate_claims`, insert a claim row `INSERT INTO candidate_claims (candidate_id, bot, status) VALUES (?, 'claude', 'new') ON CONFLICT DO NOTHING`. Then claim via `UPDATE candidate_claims SET status='processing', claimed_at=now() WHERE candidate_id=? AND bot='claude' AND status='new' RETURNING *` with `FOR UPDATE SKIP LOCKED`. OpenAI-bot's loop does the same with `bot='openai'` — both bots process every candidate independently.
6. Bot invokes 4 checks × 3 sub-agents = up to 12 parallel LLM calls via `Strategist.evaluate(check, venue, market, context)`.
   - `base_rate` and `news` checks: web-search tool use enabled.
   - `whale` check (Polymarket): queries Polymarket positions endpoint for each target wallet; result cached 5 min.
   - `disposition` check: no tools.
7. LLM responses parsed as `CheckResult` JSON. Each call logged to `decisions` (bot-scoped) with prompt, response, tokens, cost, latency.
8. Thesis aggregator applies 3-of-4 consensus: if ≥3 agree on verdict and mean confidence ≥ 0.75, produce a thesis. Else SKIP.
9. If thesis passes, `thesis_loop` persists a `thesis` row and pushes to the executor's in-process queue.
10. **Executor loop** picks up the thesis. Runs pre-execution checks (via RISK module):
    - LIVE_ENABLED for (claude, polymarket)?
    - Risk halt active?
    - Max open positions reached?
    - LLM daily spend cap reached?
11. Computes Kelly f* with quarter-Kelly cap. If f* ≤ 0, skip. Applies sub-agent consensus sizing (full/half/skip).
12. Calls `venue.place_order(order_spec)` — if DRY_RUN or LIVE_ENABLED=false, this short-circuits to a `status=SIMULATED` record.
13. Real path: `py-clob-client` signs EIP-712 order with EVM key (from Secrets Manager), submits to Polymarket.
14. Order row persisted. If unfilled after TTL (300 s default), cancel via `venue.cancel_order()`.
15. On fill: position row updated. Exit engine's WebSocket worker subscribes to this market's book.
16. **Exit loop** (runs every 60 s) evaluates all open positions. For this one, checks: TARGET_HIT, VOLUME_EXIT, STALE_THESIS. Any trigger → close via `venue.place_order(close_spec)`.
17. On close fill: realized P&L computed, (claude, polymarket) bankroll updated, daily P&L counter incremented.
18. If daily P&L drops below −50% bankroll, RISK halts (claude, polymarket) until 00:00 UTC. Alert via SES.

**Alpaca variant:** same flow, except scanner uses Alpaca calendar to suspend outside 09:30–16:00 ET; brain's 4th check is `unusual_volume` (deterministic calculation, not LLM); executor adds market-order fallback after TTL; executor submits bracket stop-loss immediately after entry fill; exit engine has 2 extra triggers (STOP_LOSS, HORIZON_EXIT + end-of-day flatten at 15:55 ET).

## 4. Design Decisions

| ID | Decision | Choice | Alternatives Considered | Trade-offs | Rationale |
|---|---|---|---|---|---|
| DD-001 | Architecture pattern | Hexagonal (ports & adapters) | Layered, event-driven, microservices | + Testability, + extensibility, − slight boilerplate from Protocols | Enables the fundamental experiment (swap LLMs) and meets REQ-LLM-009, REQ-VEN-008 |
| DD-002 | Async runtime | asyncio throughout | Sync + threads, APScheduler | + Natural fit for I/O-bound workload, + all required SDKs have async clients | All loops are I/O-bound; threading adds lock complexity for no gain |
| DD-003 | Persistence for queue | Postgres `candidate_queue` with `FOR UPDATE SKIP LOCKED` | SQS, Redis, RabbitMQ | + Zero added services, + transactional consistency with related state, − lower throughput ceiling | Throughput need is ~20/min; Postgres handles this trivially; saves $10+/mo and operational overhead |
| DD-004 | Money representation | `decimal.Decimal` + Postgres `NUMERIC(24, 8)` | float, int cents | + Precise, + no silent rounding, − slight code verbosity | Floats in financial code = bug factory. Non-negotiable for Goal 1. |
| DD-005 | Error strategy | Tiered: resilient inside loops, fail-fast at process boundary | Pure fail-fast, pure resilient | + One bad market doesn't halt the scanner, + unrecoverable DB errors still crash (Fargate restarts) | Correctness + operability balance. Single bad LLM response shouldn't stop all trading; missing DB absolutely should. |
| DD-006 | Module organization | Single Python package `claude_poly_bot/` + `frontend/` + `infra/` | Monorepo with multiple packages, single Docker image | + One pyproject.toml, − all bots run same code version (feature, not bug) | Solo dev; simpler CI; easier to reason about. |
| DD-007 | DB driver + migrations | SQLAlchemy 2.0 async + Alembic | Prisma, raw asyncpg | + Mature, + typed models, + Alembic is standard | asyncpg underneath SQLAlchemy gets speed; Alembic handles migrations deterministically |
| DD-008 | Infrastructure as code | CloudFormation | Terraform, CDK, Pulumi | + Native AWS, − verbose, − slower diff feedback | Explicit operator preference; native AWS removes third-party state backend |
| DD-009 | Bot process structure | Single Python process per bot with `asyncio.TaskGroup` owning scanner-consumer, thesis, executor, exit, and WS workers | One process per loop, one process per (bot × venue) | + In-process shared state, + fewer Fargate tasks, + simpler inter-loop communication | Clear blast radius (one bot restart doesn't affect the other); TaskGroup makes crashes propagate cleanly |
| DD-010 | Service topology | 5 always-on Fargate services + 1 scheduled task | 1 service per loop, or 1 service containing everything | + Right-sized containers, + independent scaling if needed, + matches REQ-INF-005 | Balances operational simplicity with appropriate isolation (e.g., dashboard crash doesn't stop bots) |
| DD-011 | AWS auth from CI | GitHub OIDC federation | IAM user + long-lived keys in GitHub secrets | + No long-lived credentials, + standard practice | Security goal; REQ-CICD-004 |
| DD-012 | Logging | Structured JSON via `structlog` → stdout → CloudWatch | Text logs, Sentry | + Queryable in CloudWatch Insights, + machine-readable | Goal 2 observability; REQ-OBS-001 |
| DD-013 | LLM call ergonomics | Claude with prompt caching; both with JSON mode / structured outputs | Text responses + regex parsing | + Deterministic parsing, + prompt caching cuts Claude cost ~50% on repeated system prompts | REQ-BRN-010, REQ-LLM-005 |
| DD-014 | Halt scope | Per-(bot, venue) pair — 4 independent scopes | Per-bot, per-venue, combined | + Independent comparison streams, + maximal operator control | Core experiment requires independent P&L attribution |
| DD-015 | Order types | Polymarket: limit-only with TTL cancel. Alpaca: limit-first @ mid ± slippage, market fallback after TTL | Market-only, fixed limit | + Good fills when possible, + guaranteed execution fallback | Mirrors Polymarket philosophy within Alpaca's additional capabilities |
| DD-016 | Stop-loss on Alpaca | Server-side bracket order submitted immediately after entry fill | Client-side monitoring only | + Fires even if our bot is down, + reduces exit-loop dependency | Defense in depth for the hard risk floor |
| DD-017 | Candidate queue claim semantics | Per-bot claim via `candidate_claims(candidate_id, bot, status, claimed_at)` — one row per (candidate, bot). Bot advances by `INSERT ... ON CONFLICT DO NOTHING` then `UPDATE ... SET status='processing' WHERE candidate_id=? AND bot=? AND status='new' RETURNING *` with `FOR UPDATE SKIP LOCKED`. | Single-claim round-robin, distributed lock, per-bot watermark column | + Both bots process every accepted candidate independently, + direct decision-level comparison on identical inputs, + clean idempotency | Shared-scanner / independent-evaluation is a hard requirement — this is the only design that preserves it cleanly |
| DD-018 | Shared scanner, independent evaluation | One scanner publishes to `candidate_queue`; each bot independently evaluates every candidate via its own `candidate_claims` row | One-bot-one-candidate round-robin | + Fair comparison (both bots see identical input), + enables decision-level A/B per candidate | Core experimental requirement — without it, comparison is confounded by input differences |
| DD-019 | Correlation IDs | Each scanner-accepted candidate gets a `scan_correlation_id` (UUID). Every downstream record derives `decision_correlation_id = scan_id + bot`, flowing through decisions, theses, orders, positions, trades. | Single per-candidate ID, per-record random IDs | + Enables "diff the two bots on the same market" queries trivially, + traceable through Postgres join | Directly implements Goal 2 observability — this is how "why did Claude and OpenAI differ on market X?" gets answered |
| DD-020 | Entry order idempotency | Every `place_order` generates `client_order_id = uuid4()`, persists `orders` row with `status='PENDING'` **before** the network call, then submits. Startup reconciliation queries venue for any `PENDING` order and updates status from venue truth. | Store-after-submit, no idempotency key | + Container crash between persist and submit: reconciliation finds the orphan and either cancels (if not on venue) or adopts (if on venue) | Closes R16 mid-trade restart gap |
| DD-021 | Clock source | All time-sensitive code takes a `Clock` port from `domain/protocols.py`; default adapter returns `datetime.now(timezone.utc)`. Fargate NTP time-sync is relied on for < 1 s skew across containers. 15:55 ET Alpaca flatten is a predicate inside the exit loop, checked each tick. | Scattered `datetime.now()` calls, dedicated scheduler service | + Mockable clock for tests (fast-forward UTC boundaries), + no extra service, + simpler reasoning | 15:55 ET flatten fits naturally into the exit cadence (max 60 s tardiness, acceptable) |

## 5. Cross-Cutting Concerns

### 5.1 Error Handling Strategy

**Tiered error handling:**

- **Inside any single loop iteration** (e.g., evaluating one market, processing one position):
  - Catch any exception.
  - Log with level=ERROR, structured fields (bot, venue, market_id, exception_class, trace).
  - Emit a CloudWatch metric for the error class.
  - Continue to next iteration. Do not propagate.
- **Inside a loop setup / teardown** (e.g., DB connection failure at startup):
  - Fail fast. Let the exception propagate.
  - `asyncio.TaskGroup` cancels sibling tasks.
  - Process exits with non-zero code.
  - Fargate health check marks task unhealthy; new task is started.
- **Transient RDS unavailability (e.g., failover window):**
  - Each loop wraps DB calls in a 30-second retry with exponential backoff (base 1 s, max 8 s, 5 attempts).
  - During retry: loops PAUSE (do not crash, do not fail-fast). Scanner skips the current tick; executor defers new trades; exit loop withholds actions.
  - If retry exhausts: crash the process (Fargate restart).
  - Accepted outage window: ~5 minutes of degraded behavior during RDS failover. No trades are lost (DB is source of truth); some scanner ticks may be skipped.
  - Open positions on real venues keep their server-side stops (Alpaca) and WebSocket exit-trigger evaluation (Polymarket) — so the bot being briefly offline does not strand positions.
- **Sustained degradation** (e.g., 5+ consecutive LLM failures):
  - Internal circuit breaker in the adapter halts that bot's decisioning (REQ-BRN-015).
  - SES alert fires.
  - Exit loop continues running to manage existing positions.
- **Alert storm prevention:**
  - Every alert type has a 15-minute de-duplication window (keyed by alert-type + bot + venue).
  - The very first occurrence fires; subsequent within the window increment a counter but don't re-alert.

### 5.2 Data Integrity

**Invariants that must always hold:**
- A `position` row's `status` transitions monotonically: `OPEN` → `CLOSING` → `CLOSED`. Enforced by DB constraint + application.
- `orders.status` transitions: `PENDING` → (`FILLED` | `CANCELLED` | `REJECTED` | `EXPIRED`). Enforced similarly.
- Every `position` row has exactly one entry `order_id` and at most one exit `order_id`.
- `decisions.thesis_id` is either NULL (sub-check) or points to a row in `theses`.
- Every `trade` row links to both a filled `order` and a `position`.
- `config_audit` is append-only (no UPDATEs or DELETEs). Enforced by a table-level trigger forbidding UPDATE/DELETE.
- `bankroll` for a (bot, venue) pair at any instant = starting_bankroll + Σ realized P&L + Σ unrealized P&L. Validated on read; any discrepancy triggers a reconciliation alert.
- **Insufficient-capital guard:** If `available_capital <= min_trade_size` at executor evaluation time, skip with reason `INSUFFICIENT_CAPITAL`. First occurrence per bot per UTC day fires a low-balance SES alert.

**Daily boundary (00:00 UTC) attribution rules:**
- At 00:00 UTC, the daily-P&L counters reset atomically for all 4 (bot, venue) pairs in one transaction.
- A realized fill attributes to the UTC day of the **fill timestamp** (not the order submission day). A trade that fills across the boundary attributes to the latter day.
- Unrealized P&L is recomputed from live marks on read; reset at the boundary means "start-of-day unrealized mark" becomes the new zero point for the new day's drawdown calculation.
- Daily drawdown halt evaluates against current-UTC-day delta only.

**Consistency:**
- All multi-row state transitions occur inside a single DB transaction.
- No cross-bot or cross-venue atomic operations. (A Claude-bot order and an OpenAI-bot order are never part of the same transaction.)
- Idempotent external operations via `client_order_id` (UUID per order). A retried `place_order` with the same `client_order_id` is a no-op.

**Reconciliation:**
- Every bot boot performs a startup reconciliation: for each open position in the DB, query `venue.get_positions(bot)` and reconcile. Discrepancies (position in DB but not on venue, or vice-versa) → alert + mark for manual review.
- A periodic (hourly) reconciliation task compares DB state to venue state.

### 5.3 Performance Considerations

Non-critical. Bottlenecks by order of likelihood:

- **LLM call latency** — 1–5 s per call × 12 calls per market = 12–60 s per market. Parallelize across the 3 sub-agents, giving ~20 s per market. Batch size limited by venue API rate limits more than by compute.
- **Scanner API paging** — Polymarket's market list endpoint paginates. Acceptable if scanner completes in under 60 s even with 500 markets.
- **DB** — `db.t4g.micro` is 2 vCPU / 1 GB RAM. Sufficient for expected row volumes (thousands/day) and query rate.
- **Fargate sizing (initial):** 0.5 vCPU / 1 GB per bot service, 0.25 vCPU / 512 MB for scanner, 0.5 vCPU / 1 GB for dashboard-api, 0.5 vCPU / 1 GB for dashboard-ui.

Complexity callouts:
- Scanner filter: O(N markets). 500 × a handful of filter predicates = trivial.
- Brain consensus aggregation: O(1) per market.
- Kelly math: O(1).
- Exit loop: O(K open positions × triggers). K ≤ 20 total (5 per pair × 4 pairs). Trivial.
- Queue polling: `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 10` is O(1) with an index.

### 5.4 Security Considerations

**Trust boundary:** the dashboard UI and API are the primary external-facing surface. Everything else is private-subnet only.

**Layers of defense:**
- **Network:** ALB is the only public endpoint; ECS services run in private subnets; RDS in DB subnets with no public access; S3 with IAM-only access.
- **Auth:** GitHub OAuth; allowlist enforced on both OAuth-grant flow and every API request.
- **Session:** HttpOnly + Secure + SameSite=Lax cookies; signed JWT with rotating signing key pulled from Secrets Manager.
- **WebSocket auth:** The `/api/live` WebSocket upgrade inherits cookie auth from the HTTP handshake (browser sends session cookie on `Upgrade: websocket`). On `connection_open`, the server validates the cookie, re-checks the allowlist against the current `auth_allowlist` config, and validates `Origin` header against an allowlist of permitted dashboard origins per environment. Any failure closes the socket with code 1008 (policy violation).
- **LLM output as untrusted input (XSS defense):** LLM-generated text (rationales, prompts, responses) is treated as untrusted. The dashboard UI renders all LLM strings as React text nodes (default-escaped); `dangerouslySetInnerHTML` is lint-forbidden (ESLint rule `react/no-danger` set to `error`); the API response never wraps LLM output in HTML. Content Security Policy header enforces `default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'` on all dashboard pages. CSP violations report to a CloudWatch log group.
- **Secrets:** never in environment files committed to git. Always Secrets Manager in prod; local `.env` gitignored. Rotation: client_secret & LLM keys manually rotatable; EVM keys fixed per bot.
- **Key-material redaction:** Structured logger has a `RedactProcessor` that scrubs keys matching patterns `sk-*`, `ak-*`, `0x[0-9a-fA-F]{64}`, and well-known field names (`private_key`, `api_key`, `session_token`, `client_secret`).
- **LIVE_ENABLED as high-risk mutation:** requires POST body confirmation field + logs to `config_audit` + fires SES alert. No Undo button — toggling back is the mitigation.
- **Dependency hygiene:** `uv lock` + Dependabot; CI runs `pip-audit` and fails build on known high-severity vulns.
- **AWS IAM:** per-service roles with least privilege. Bot services can read their own Secrets Manager entries only (not other bots'). Dashboard-api can read/write config but cannot read wallet keys.

### 5.5 Observability

**Logs:**
- Structured JSON to stdout → CloudWatch.
- Required fields: `timestamp, level, service, bot, venue, correlation_id, message`.
- Correlation IDs: every scanner-discovered candidate gets a UUID that flows through every downstream record (decision, thesis, order, position, trade) via the `correlation_id` FK. One query in CloudWatch Insights shows a full decision's life.

**Metrics (CloudWatch):**
- Counters: `scanner.runs`, `scanner.candidates_{accepted|rejected}`, `thesis.generated{bot,venue}`, `orders.placed{bot,venue}`, `orders.filled{bot,venue}`, `orders.cancelled{bot,venue}`, `risk.halts{bot,venue,reason}`, `llm.calls{bot,model,check}`, `alerts.sent{type}`.
- Gauges: `bankroll{bot,venue}`, `open_positions{bot,venue}`, `llm.daily_spend{bot}`, `daily_pnl{bot,venue}`.
- Histograms: `llm.latency{bot,model,check}`, `order.fill_latency{venue}`, `scanner.duration{venue}`.

**Alerts (SES):**
- Taxonomy of 11 alert types enumerated in REQ-OBS-004.
- De-duplication window: 15 min.
- All alerts include a dashboard deep-link for the affected (bot, venue).

**Dashboards:**
- Custom UI is the primary observation tool.
- CloudWatch dashboards (one per env) track system-level health: ECS task count/CPU/memory, RDS CPU/connections, ALB 4xx/5xx rates.

### 5.6 Concurrency & Recovery

**Shared state discipline:**
- No process-local caches of mutable financial state (bankroll, open positions, risk-halt flags). Reads go through the repo layer with a single-request transaction scope.
- The whale-check cache (5 min TTL) and unusual-volume cache (5 min TTL) are permitted exceptions because they are advisory inputs, not financial truth.
- Within a bot process, the risk-halt flag is evaluated per-decision by querying the `risk_halts` table — no in-memory flag.
- `asyncio.Lock` guards any transient in-process structures that must serialize (e.g., websocket subscription registry, LLM-spend accumulator write).

**Restart recovery (startup reconciliation):**
- Every bot process on boot, before entering its main loop:
  1. Query `orders WHERE status='PENDING' AND bot=?` in the DB.
  2. For each pending order, query venue for that `client_order_id`:
     - Venue knows it and it's filled → update DB to `FILLED`, create position.
     - Venue knows it and it's open → leave as `PENDING`, put on watch list.
     - Venue knows it and it's cancelled/rejected → update DB accordingly.
     - Venue does NOT know it → mark as `LOST` and emit alert (operator decides).
  3. Query `positions WHERE status='OPEN' AND bot=?` and cross-check against `venue.get_positions()`.
     - Match → proceed.
     - Position in DB, not in venue → mark `ORPHANED`, emit alert.
     - Position in venue, not in DB → insert `ADOPTED` row, emit alert.
  4. Subscribe streams for all validated open positions.
  5. Only then enter the main loops.
- Hourly in-flight reconciliation runs the same position cross-check on a cadence.

**Idempotency boundary:**
- Every `place_order` call generates a UUID `client_order_id` and **writes a PENDING `orders` row first**, then submits to venue.
- Retries of a failed venue submission use the same `client_order_id` (idempotency key).
- If the submission itself is ambiguous (timeout, 5xx), the retry path queries venue for that `client_order_id` before re-submitting.

**Clock source:**
- A `Clock` port in `domain/protocols.py` returns `datetime.now(timezone.utc)` by default.
- All time-sensitive predicates (stale-thesis age, volume-window start, 15:55 ET flatten, UTC-day boundary) evaluate against the `Clock` port.
- Tests inject a fast-forwarding `FakeClock` to exercise UTC boundaries and Alpaca end-of-day.
- Fargate containers use AWS-managed NTP; assumed skew < 1 s. This is sufficient for 60-s exit cadence and 10-min volume windows.

**Queue backpressure:**
- `candidate_queue` has a soft cap: if the unprocessed count for any bot exceeds 50 (configurable), the scanner pauses publication for that cycle.
- Dashboard `/health` surfaces queue depth per bot.
- This caps LLM spend exposure when scanner sees an unusually permissive market regime.

## 6. Module Map

Code organization (single Python package + Next.js + CloudFormation).

```
claude-poly-bot/
├── python/
│   ├── pyproject.toml
│   ├── claude_poly_bot/
│   │   ├── __init__.py
│   │   ├── bot/
│   │   │   ├── runner.py              # Entry point: runs N loops inside TaskGroup
│   │   │   ├── loops/
│   │   │   │   ├── scanner.py
│   │   │   │   ├── thesis.py
│   │   │   │   ├── executor.py
│   │   │   │   ├── exit.py
│   │   │   │   └── data_refresh.py
│   │   │   └── state.py               # In-process registry
│   │   ├── domain/
│   │   │   ├── models.py              # Pydantic domain objects
│   │   │   ├── protocols.py           # Venue, Strategist, repos
│   │   │   ├── scoring.py             # Pure scan scoring
│   │   │   ├── kelly.py               # Pure Kelly math
│   │   │   ├── consensus.py           # Pure consensus
│   │   │   ├── risk.py                # Pure predicates (incl. PDT check for Alpaca)
│   │   │   ├── thesis.py              # Aggregation + confidence
│   │   │   └── clock.py               # Clock port default adapter
│   │   ├── venues/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py
│   │   │   ├── polymarket/
│   │   │   │   ├── venue.py           # Venue impl via py-clob-client
│   │   │   │   └── stream.py
│   │   │   ├── alpaca/
│   │   │   │   ├── venue.py
│   │   │   │   ├── stream.py
│   │   │   │   └── calendar.py
│   │   │   └── mocks/
│   │   │       └── fake_venue.py
│   │   ├── llm/
│   │   │   ├── anthropic_impl.py
│   │   │   ├── openai_impl.py
│   │   │   ├── prompts/
│   │   │   │   ├── polymarket/        # .md templates
│   │   │   │   └── alpaca/
│   │   │   └── mocks/
│   │   │       └── fake_strategist.py
│   │   ├── storage/
│   │   │   ├── db.py                  # SQLAlchemy engine + session factory
│   │   │   ├── orm.py                 # ORM tables
│   │   │   ├── repos/
│   │   │   │   ├── positions.py
│   │   │   │   ├── orders.py
│   │   │   │   ├── trades.py
│   │   │   │   ├── decisions.py
│   │   │   │   ├── theses.py
│   │   │   │   ├── config.py
│   │   │   │   ├── queue.py
│   │   │   │   ├── target_wallets.py
│   │   │   │   └── audit.py
│   │   │   └── s3.py
│   │   ├── config/
│   │   │   ├── schema.py              # Pydantic settings + field tier metadata
│   │   │   ├── service.py             # Load/apply/validate
│   │   │   └── defaults.py
│   │   ├── wallet/
│   │   │   └── evm.py                 # Key load, balance, signing
│   │   ├── auth/
│   │   │   ├── oauth.py
│   │   │   └── session.py
│   │   ├── api/
│   │   │   ├── main.py
│   │   │   ├── deps.py
│   │   │   ├── routes/
│   │   │   │   ├── bots.py
│   │   │   │   ├── markets.py
│   │   │   │   ├── config.py
│   │   │   │   ├── health.py
│   │   │   │   └── auth.py
│   │   │   ├── websocket.py
│   │   │   └── middleware/
│   │   ├── cli/
│   │   │   ├── __main__.py            # Typer CLI
│   │   │   ├── setup_wallets.py
│   │   │   ├── setup_alpaca.py
│   │   │   ├── setup_oauth.py
│   │   │   └── refresh_data.py
│   │   └── observability/
│   │       ├── logging.py
│   │       ├── metrics.py
│   │       └── alerts.py              # SES adapter
│   ├── alembic/
│   │   └── versions/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
├── frontend/
│   ├── package.json
│   ├── next.config.mjs
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                   # /
│   │   ├── bots/[name]/page.tsx
│   │   ├── decisions/page.tsx
│   │   ├── markets/page.tsx
│   │   ├── config/page.tsx
│   │   └── health/page.tsx
│   ├── components/
│   ├── lib/
│   └── tests/
├── infra/
│   ├── cloudformation/
│   │   ├── root.yaml                  # Nested stacks
│   │   ├── network.yaml
│   │   ├── rds.yaml
│   │   ├── ecs.yaml
│   │   ├── ecr.yaml
│   │   ├── secrets.yaml
│   │   ├── alb.yaml
│   │   ├── ses.yaml
│   │   └── eventbridge.yaml
│   └── params/
│       ├── dev.json
│       └── prod.json
├── .github/workflows/
│   ├── pr.yml
│   ├── deploy-dev.yml
│   ├── deploy-prod.yml
│   └── rollback.yml
├── .devcontainer/
│   └── devcontainer.json
├── docker/
│   ├── Dockerfile.bot
│   ├── Dockerfile.api
│   └── Dockerfile.ui
├── docker-compose.yml
├── requirements.md
├── design-hld.md
└── README.md
```

**Module dependency rules:**
- `domain/` imports from nothing else in the package (pure).
- `venues/`, `llm/`, `storage/`, `wallet/`, `auth/`, `observability/` may import from `domain/`.
- `bot/`, `api/`, `cli/` may import from everywhere.
- No cycles. Enforced by import-linter in CI.

## 7. Risk Register

| # | Risk | Impact | Likelihood | Mitigation | When to Address |
|---|---|---|---|---|---|
| R1 | LLM cost explosion under high candidate volume | H | M | Hard per-bot daily spend cap (REQ-RISK-008); monitoring + SES alert at 80% of cap | Phase 6 (RISK module) |
| R2 | Wallet private key leak | Critical | L | Secrets Manager only; log redaction; IAM least-privilege; no key output from any API endpoint | Phase 6 (WAL module) |
| R3 | Polymarket or Alpaca API breaking change | H | M | Vendor SDKs pinned to known-good versions; integration tests against recorded fixtures; alert on 4xx surge | Phase 6 (POLY/ALPC) + ongoing |
| R4 | Exit engine misses a position (e.g., WS drops undetected) | H | M | REST reconciliation every hour; startup reconciliation; WS heartbeat + reconnect logic | Phase 6 (EXIT module) |
| R5 | Bracket stop-loss on Alpaca fails to fire | H | L | Server-side stop via Alpaca (DD-016) + client-side stop-loss check in exit loop as defense in depth | Phase 6 (EXE + EXIT) |
| R6 | Race: both bots process same candidate differently, or candidate processed twice | M | M | `FOR UPDATE SKIP LOCKED` on claim; per-bot claim rows (DD-017); idempotent order placement via `client_order_id` | Phase 6 (queue repo) |
| R7 | Configuration change corrupts live bot | H | M | Server-side validation (REQ-CFG-011); audit log (REQ-CFG-010); Tier 1 changes apply on next loop (not mid-iteration) | Phase 6 (CFG module) |
| R8 | PDT rule violation on Alpaca (equity < $25k) triggers 90-day restriction | M | M | Client-side PDT counter (REQ-ALPC-012); refuse to open position that would trip the rule | Phase 6 (ALPC + RISK) |
| R9 | OAuth allowlist bypass or session hijack | H | L | HttpOnly+Secure+SameSite cookies; signed JWT; allowlist checked on every request | Phase 6 (AUTH) |
| R10 | CloudFormation stack drift vs deployed code | M | M | CI enforces template change triggers stack update; CloudFormation Drift Detection weekly cron | Phase 6 (INF) + ongoing |
| R11 | RDS capacity exhaustion from log explosion | M | L | Automated archival of decisions > 90 days to S3; alarm on RDS storage > 80% | Phase 6 (storage + OBS) |
| R12 | Daily data-refresh silently fails, stale target wallets | M | M | Alert on refresh failure (REQ-DATA-005); health-page freshness indicator; reject refresh results that shrink target list by > 50% | Phase 6 (DATA) |
| R13 | Smoke tests pass but real traffic fails | M | M | Synthetic-trade canary in DRY_RUN post-deploy; auto-rollback hook (REQ-CICD-006) | Phase 6 (CICD) |
| R14 | Claude and OpenAI models upgraded mid-experiment, contaminating comparison | H | H | Pin explicit model IDs in config (REQ-LLM-003); track model-change events as annotations on P&L charts | Ongoing operational discipline |
| R15 | Time-zone bugs in daily UTC resets affect halt logic | M | M | All timestamps stored UTC, all boundary calculations explicit `datetime.timezone.utc`; `Clock` port + `FakeClock` in tests exercises boundaries | Phase 6 (RISK + tests) |
| R16 | Mid-trade restart: order submitted before container kill, fill status unknown | H | M | Store-before-submit (DD-020); startup reconciliation (§5.6) queries venue for every PENDING `client_order_id`; adoption or cancellation of orphans | Phase 6 (EXE + reconciliation) |
| R17 | XSS via LLM-generated text in dashboard (prompts, rationales) | H | M | All LLM-sourced strings rendered as React text nodes only; `react/no-danger` ESLint error; CSP `default-src 'self'` (§5.4) | Phase 6 (UI + CSP headers) |
| R18 | RDS outage cascades into all services crashing and restart-storming | H | L | 30 s retry-with-pause in every DB-touching loop before crash (§5.1); Fargate throttled restart; positions remain managed by venue-side stops (Alpaca) or WS-driven exit logic (Polymarket reconnects on recovery) | Phase 6 (storage + loop wrappers) |
| R19 | Clock skew across Fargate containers breaks volume-window and 15:55 ET triggers | M | L | AWS-managed NTP assumed < 1 s skew; all time via `Clock` port (DD-021); `FakeClock` tests exercise boundaries; alert on volume-window reads returning negative intervals | Phase 6 (clock port + tests) |
| R20 | Data-refresh (06:00 UTC) runs long and daily summary (08:00 UTC) uses stale target-wallet data | L | M | `daily_summary` timer checks `target_wallets.refreshed_at` and annotates summary email if older than 24 h | Phase 6 (OBS) |

## 8. Deferred to LLD

The HLD intentionally does NOT specify:
- Exact ORM column names and indices (→ `storage/repos/*.py` LLDs).
- Exact LLM prompt wording (→ `llm/prompts/` LLDs).
- Exact dashboard component tree (→ frontend LLD).
- Exact CloudFormation parameter names (→ infra LLD).

These are module-level concerns and will be decided in Phase 3B.

## 9. Open Questions

None blocking. Minor to revisit during LLD:
- Should `data-refresh` use Athena over the Parquet snapshots, or always recompute in-process? (Leaning in-process for simplicity.)
- Should `unusual_volume` check on Alpaca be cached in Postgres or recomputed per scan? (Probably in-process cache with 5-min TTL, per §5.6.)
- `data-refresh` at 06:00 UTC and daily-summary at 08:00 UTC create a 2-hour dependency window; R20 covers the annotation, but should refresh move earlier (e.g., 04:00 UTC) to provide buffer?

## 10. Changes From v1 (subagent review follow-up)

The following sections were added or modified after an independent subagent review of v1:
- **DD-017** rewritten to unambiguously specify per-bot `candidate_claims` rows.
- **DD-019, DD-020, DD-021** added (correlation IDs, entry idempotency, clock source).
- **§3.4 step 5** rewritten to match DD-017's per-bot claim flow.
- **§5.1** gained RDS-outage retry/pause policy.
- **§5.2** gained daily-boundary P&L attribution rules and insufficient-capital invariant.
- **§5.4** gained WebSocket auth spec and XSS/CSP defense for LLM-rendered content.
- **§5.6 Concurrency & Recovery** added: shared-state discipline, startup reconciliation, idempotency boundary, clock source, queue backpressure.
- **Risk register** gained R16 (mid-trade restart), R17 (LLM XSS), R18 (RDS cascade), R19 (clock skew), R20 (refresh/summary timing).
- **Module map** `domain/` gained `clock.py`; `risk.py` noted to own PDT check.
