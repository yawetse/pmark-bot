# codex-poly-bot High-Level Design

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.2
**Date:** 2026-07-31
**Status:** APPROVED
**Requirements Source:** `requirements.md`

## 1. Design Goals

| Priority | Goal | Rationale |
|----------|------|-----------|
| 1 | Security | The system can place live trades and manage wallet material, so secrets, access control, and trade refusal states are the top priority. |
| 2 | Data integrity | Position, order, budget, and audit records must be correct before the system can be trusted with live funds. |
| 3 | Auditability | Every configuration change, signal, refusal, order, and exit needs a durable trail for review and debugging. |
| 4 | Testability | Venue, brokerage, LLM, AWS, and database adapters need mocks and contract tests so the bot can be changed without unsafe live behavior. |
| 5 | Maintainability | The first version should be understandable and easy to extend without splitting into multiple services too early. |
| 6 | Simplicity | A modular monolith keeps deployment and local debugging practical while the behavior is still being proven. |
| 7 | Performance | The first target is 500 markets per venue per 60-second loop, with deterministic filters before LLM scoring. |
| 8 | Extensibility | The design should allow workers to move into separate ECS services later without rewriting domain logic. |
| 9 | Funding accuracy | Deposits and withdrawals must be reconciled from venue records, separated from trading returns, and tied to deterministic expected occurrences. |

## 2. Non-Goals

| Non-Goal | Rationale |
|----------|-----------|
| Geo-bypass or platform restriction evasion | The system will not include VPN, proxy, or venue bypass behavior. |
| High-frequency trading | A 60-second loop and LLM scoring are not designed for sub-second execution. |
| Multi-tenant SaaS | The dashboard is for allowlisted GitHub users managing one bot deployment. |
| Separate worker services in v1 | The first deployment runs one ECS service to reduce operational setup. |
| Dashboard private key display | The dashboard can show wallet status and public identifiers, but never private keys. |
| Runtime dependency on referenced open-source repos | The referenced repos inform design, but v1 is standalone unless a later requirement changes that. |
| Manual production approval gate | Merges to `main` deploy production automatically per approved requirements. |
| Alpaca options, crypto, hard-to-borrow locates, or margin-funded long purchases | This release limits shorting to explicitly enabled easy-to-borrow U.S. equities. |
| Bank credential collection or application-database storage | Bank accounts and ACH relationships remain managed by the venue. Exact Broker account and ACH relationship identifiers are secret bootstrap values; persistence uses only sanitized account references. |
| Plaid integration | Alpaca accepts an existing ACH relationship identifier, so this release does not add a bank-linking vendor. |
| Polymarket direct funding | Polymarket US remains observe-only until a documented, entitled funding-write API is available. |

## 3. Architecture Overview

### 3.1 Architecture Pattern

The system uses a modular monolith with ports and adapters. Domain modules own trading decisions, risk checks, configuration rules, and audit events. Adapter modules handle Polymarket APIs, Alpaca APIs, LLM providers, AWS services, Postgres, GitHub OAuth, and email delivery.

**Considered alternatives:**

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Event-driven microservices | Clear scaling boundaries and isolated workers | More infrastructure, harder local debugging, more deployment paths | Too much operational weight for v1. The bot should prove strategy and risk behavior first. |
| Single combined script | Fastest to start | Poor dashboard integration, weak testability, hard to split later | It does not meet audit, CI/CD, dashboard, and deployment requirements. |
| Modular monolith with ports/adapters | Clear module boundaries, strong tests, easier local and ECS deployment | Requires discipline to keep adapters out of domain logic | Best fit for v1 scope and future worker split. |

### 3.2 System Diagram

```text
GitHub OAuth
     |
     v
+--------------------+    REST/WebSocket      +----------------------+
| Next.js Dashboard  | <--------------------> | FastAPI Backend      |
| frontend container |                        | backend container    |
+--------------------+                        +----------+-----------+
                                                       |
                                                       v
                                             +----------------------+
                                             | Domain Modules       |
                                             | config, strategy,    |
                                             | risk, execution,     |
                                             | exits, audit         |
                                             +----+------+-----+----+
                                                  |      |     |
                              +-------------------+      |     +------------------+
                              v                          v                        v
                     +----------------+          +---------------+        +----------------+
                     | Postgres RDS   |          | AWS Services  |        | External APIs  |
                     | shared schema  |          | S3, SES,      |        | Polymarket US, |
                     | claude schema  |          | Secrets Mgr,  |        | International, |
                     | openai schema  |          | CloudWatch    |        | Alpaca,        |
                     |                |          |               |        | OpenAI, Claude |
                     +----------------+          +---------------+        +----------------+

Same ECS service, one task definition:
  - frontend container
  - backend container

Backend process owns v1 background loops:
  - ingestion loop
  - trading loop
  - exit loop
  - notification loop
  - portfolio and funding reconciliation loop
```

### 3.3 Component Overview

| Component | Responsibility | Owns Data? | Key Interfaces |
|-----------|----------------|------------|----------------|
| Venue integration | Fetch market data and submit orders through official SDK/API clients | No | `VenueClient`, `MarketDataPort`, `OrderExecutionPort` |
| Alpaca brokerage integration | Trade long stocks and ETFs plus explicitly enabled easy-to-borrow U.S. equity shorts through separate Alpaca accounts per model provider | No | `BrokerageClient`, `AccountMode`, `StockMarketDataPort` |
| Data ingestion | Full and incremental downloads, normalization, S3 writes, checkpoints | Yes, ingestion checkpoints and S3 object metadata | `IngestionService`, `S3StoragePort` |
| Postgres persistence | Config, positions, orders, audits, budgets, model-specific schemas | Yes | SQLAlchemy repositories, Alembic migrations |
| Wallet and secrets | Wallet generation CLI, brokerage credential lookup, secret lookup, wallet and account status | Yes, wallet/account metadata only | `WalletService`, `SecretStorePort` |
| LLM scoring | Run OpenAI and Claude market evaluations with budget checks | Yes, scoring records and prompt versions | `ScoringService`, `LlmProviderPort` |
| Strategy engine | Arbitrage, convergence, whale-copy signals and consensus rules | Yes, signal records | `StrategyEngine`, strategy modules |
| Risk and execution | Kelly sizing, dry-run/live mode, guardrails, stock risk limits, order routing, kill switch | Yes, order decisions and refusal events | `RiskEngine`, `ExecutionService` |
| Exit monitor | Profit target, volume spike, and stale thesis exit decisions | Yes, exit decisions | `ExitMonitor` |
| Dashboard and auth | GitHub OAuth, config UI, status UI, kill switch UI | No, writes config through API | Next.js pages, API client |
| Notifications | SES digest and threshold alerts | Yes, delivery attempts and cooldown state | `NotificationService`, `EmailPort` |
| Comparison analytics | Compare model performance across Polymarket, Kalshi, and Alpaca | Yes, derived metric snapshots | `ComparisonService`, dashboard API |
| Funding reconciliation | Normalize venue cash flows, materialize expected occurrences, match deposits, calculate cash-flow-adjusted returns, and emit funding alerts | Yes, cash flows and funding occurrences | `FundingService`, `FundingRepository`, venue activity adapters |
| Alpaca Broker transfer adapter | Submit entitled incoming ACH transfers after local safety checks | No | `FundingTransferPort`, Alpaca Broker API |
| Deployment and Codex setup | CloudFormation, GitHub Actions, local Docker, Codex docs | No | workflow files, templates, setup scripts |
| Observability | Structured logs, audit events, dashboard health | Yes, audit and health records | `AuditService`, logger adapters |

### 3.4 Data Flow

Primary trading loop:

1. The backend scheduler reads active config from Postgres.
2. The venue adapter scans enabled venues only, including enabled Polymarket and Kalshi event markets and Alpaca stock or ETF universes.
3. The strategy engine applies deterministic filters to reduce candidate markets.
4. The LLM scoring service sends eligible candidates to Claude and OpenAI, subject to each model budget.
5. Each model provider writes scoring output to its own schema.
6. Strategy modules generate arbitrage, convergence, whale-copy, and stock/ETF candidate signals where applicable.
7. The risk engine calculates size, checks dry-run/live mode, venue flags, account mode, wallet or brokerage credential state, stale data, position limits, daily loss, open positions, short account and borrow eligibility, and slippage.
8. In dry-run mode, execution records simulated orders only.
9. In live mode, execution uses official SDK/API clients for each enabled venue and persists submitted, filled, canceled, failed, and refused order events.
10. The dashboard reads status, positions, orders, config, and audit events from the API.

Ingestion flow:

1. At 06:00 UTC, the ingestion loop downloads full snapshots for enabled venues.
2. On the configured incremental interval, the ingestion loop downloads changed records from the last checkpoint.
3. Raw full snapshots, raw incremental snapshots, and normalized outputs are stored in S3.
4. Checkpoints and metadata are stored in Postgres.
5. Staleness status is exposed to risk checks and the dashboard.

Configuration flow:

1. An allowlisted GitHub user signs in through the Next.js dashboard.
2. The dashboard sends configuration changes to the FastAPI API.
3. The API validates authorization and writes the new config to Postgres.
4. The audit service records user, old value, new value, timestamp, environment, and IP address.
5. Background loops reload config on their next cycle and apply changes without restart.

Funding flow:

1. After a confirmed portfolio refresh, the funding service retrieves deposit and withdrawal activity from each configured venue account.
2. The service normalizes and upserts venue cash flows using a venue transaction identifier and merges model-provider attribution when credentials resolve to the same account.
3. The service materializes due weekly, monthly, and low-balance occurrences with deterministic idempotency keys before any external call.
4. Observe-only occurrences wait for matching completed venue cash flows. Direct Alpaca occurrences pass all enablement, limit, credential, kill-switch, and pending-transfer checks before the Broker API adapter can submit them.
5. The service matches completed cash flows to expected occurrences, marks overdue occurrences missing after four business days, and sends one failure or recovery alert per transition.
6. Performance queries subtract deposits and add withdrawals when calculating trading P&L and use Modified Dietz for percentage returns across external cash flows.
7. The dashboard reads funding history from sanitized API responses and changes funding settings through the existing versioned and audited configuration path.

## 4. Design Decisions

| ID | Decision | Choice | Alternatives Considered | Trade-offs | Rationale |
|----|----------|--------|-------------------------|------------|-----------|
| DD-001 | Repository layout | Monorepo under `codex-poly-bot` with `backend/`, `frontend/`, `infra/`, and `docs/` | Separate repos | Easier local coordination, less independent release control | One product with shared requirements and one CI/CD path. |
| DD-002 | Backend language | Python with FastAPI | TypeScript backend, Rust | Easier data work and Polymarket Python SDK use, less type strictness than TS | Python fits `py-clob-client`, data processing, and debugging goals. |
| DD-003 | Frontend | Next.js React | FastAPI templates, Vite SPA | Better auth and dashboard structure, more framework surface | Fits custom dashboard and GitHub OAuth needs. |
| DD-004 | Auth ownership | Next.js owns GitHub OAuth; FastAPI performs API authorization checks | FastAPI owns OAuth | Cleaner dashboard auth, API still validates user context | This matches Next.js strengths without trusting the client blindly. |
| DD-005 | Architecture | Modular monolith with ports/adapters | Microservices, script-based bot | Easier deployment and tests, requires boundary discipline | Best balance for v1 and future split. |
| DD-006 | ECS shape | One ECS service, one task with separate frontend and backend containers | One combined container, separate services | Clearer process ownership, slightly more task config | Keeps v1 simple while avoiding one mixed runtime image. |
| DD-007 | Worker placement | Backend process runs ingestion, trading, exits, and notifications as background loops | Separate worker services in v1 | Simpler deployment, less horizontal isolation | Meets v1 needs and keeps split path open. |
| DD-008 | Infrastructure | CloudFormation templates | Terraform, CDK | Native AWS, more YAML, less abstraction | User chose CloudFormation. |
| DD-009 | Config storage | Postgres is source of truth, `.env` and Secrets Manager only bootstrap secrets | Static config files, SSM Parameter Store for all config | Runtime updates are easy, DB availability matters | Dashboard needs immediate config edits and audit trails. |
| DD-010 | Model data separation | Same RDS database with `claude`, `openai`, and shared schemas | Separate DBs, provider column only | Clear isolation, one DB to operate | User chose separate schemas in the same DB. |
| DD-011 | Money and probability types | Fixed precision decimals | Floats | More verbose, safer financial math | Avoids rounding surprises in sizing and P&L. |
| DD-012 | ORM and migrations | SQLAlchemy and Alembic | Raw SQL only, Django ORM | Good balance of control and maintainability | Standard Python stack for explicit schema management. |
| DD-013 | Validation | Pydantic models at API and config boundaries | Loose dicts | More boilerplate, clearer validation | Reduces unsafe config and input drift. |
| DD-014 | Error strategy | Defensive refusal for trading, keep dashboard/scanning alive where safe | Fail-fast, silent retries | More refusal records, safer live trading | Live trading should stop on uncertainty without taking the whole app down. |
| DD-015 | Testing | Pytest backend, mocked APIs by default, adapter contract tests, Playwright UI tests | Manual tests only, real API tests by default | More upfront setup, safer iteration | Required for live trading and CI/CD. |
| DD-016 | Dashboard live toggle | Simple authorized toggle with audit event | Typed confirmation, manual restart | Faster operation, higher need for auth and audit | User chose a simple toggle. |
| DD-017 | Market orders | Supported with configurable estimated slippage guardrail, default 2 percent | Limit orders only | More execution flexibility, more risk checks | User requested market orders. |
| DD-018 | Production deployment | Automatic deploy on merge to `main` | Manual approval | Faster delivery, requires strong CI gates | User requested automatic production deploys. |
| DD-019 | Codex web support | Safe setup docs, `.env.example`, setup scripts, no production secrets | Expose dev/prod secrets to cloud agents | Safer agent work, cloud tasks cannot run live trading | Coding agents should test and inspect without trading secrets. |
| DD-020 | Scheduler concurrency | Postgres-backed job locks and job run records | In-memory locks, external queue | Works across future multiple tasks, requires DB availability | Prevents overlapping trading, ingestion, exit, and notification loops. |
| DD-021 | Order idempotency | Persist order intent before submit with unique idempotency key | Submit first and persist later | Safer on timeout, requires reconciliation path | Prevents duplicate live orders after retries or process restarts. |
| DD-022 | Venue default | `selected_venue=polymarket_us`, `venue_enabled=false` until explicitly enabled | Enable US venue by default | Safer default, requires user action before scanning | Satisfies default venue selection and disabled-until-enabled behavior. |
| DD-023 | Auth trust boundary | Next.js sends a signed session token to FastAPI; FastAPI validates signature and username allowlist before writes | Trusted header only, API validates GitHub OAuth directly | Avoids trusting client headers, keeps OAuth UX in Next.js | Prevents dashboard/API auth drift. |
| DD-024 | Config versioning | Every config save creates an owner-scoped database version and workers run each loop against one resolved config snapshot | Mutable config reads throughout a loop or process-local settings only | Slightly more persistence work, consistent decisions | Prevents partial application during a trading loop and keeps multi-user dashboard changes tied to the correct config owner. |
| DD-025 | Strategy defaults | Default consensus requires at least two enabled strategy signals for a full position and one signal for half position | Any single signal full position, all strategies required | Lower overtrading risk, may miss trades | Matches the approved pmbot-style consensus behavior. |
| DD-026 | Kelly variant | Fractional Kelly with configurable cap, default max fraction 0.25 | Full Kelly, fixed order size | Safer sizing, depends on model probability quality | Aligns with the source strategy and risk cap requirements. |
| DD-027 | Slippage source | Estimate slippage from current order book depth before market orders | Static spread only, post-trade estimate | More API calls, safer market orders | Required for configurable market order guardrails. |
| DD-028 | S3 retention owner | CloudFormation S3 lifecycle rules enforce raw 365-day and normalized 730-day retention | Application cleanup job | Less app code, lifecycle behavior is managed by AWS | Retention is storage policy, so it belongs in infrastructure. |
| DD-029 | Credential refresh | Secrets are cached with a short TTL and can be invalidated by config version changes | Load once on startup | Slightly more secret lookups, supports rotation | Meets credential rotation without redeploy. |
| DD-030 | Kill switch priority | Kill switch is an immediate control-plane override, not a normal next-loop config change | Apply on next loop only | More special-case handling, safer live trading | New live order creation must stop immediately. |
| DD-031 | LLM scoring concurrency | Provider-specific bounded queues with budget reservation before submit | Fire all requests at once | Controls cost and rate limits, may defer candidates | Keeps 60-second loop stable without spending past budget. |
| DD-032 | Cross-loop order coordination | Market/model reservations prevent simultaneous entry and exit decisions | Independent entry and exit loops | Safer order lifecycle, more DB coordination | Avoids conflicting orders for the same model and market. |
| DD-033 | AWS environment separation | Development and production use separate CloudFormation stacks, names, secrets, buckets, databases, and wallets | Shared resources with prefixes only | More infrastructure, clearer isolation | Required for branch-based deploys and safer production. |
| DD-034 | Alpaca scope | Long stocks and ETFs plus disabled-by-default easy-to-borrow U.S. equity shorts | Options, crypto, hard-to-borrow locates, margin-funded long purchases | Adds bearish execution while retaining broker-backed fail-closed controls | Matches Alpaca Trading API position-intent, account, and asset eligibility contracts. |
| DD-047 | Alpaca short safety | Require registered account identity, current market clock and ask, account shorting eligibility, 2,000 USD equity, sufficient buying power, active/tradable/shortable U.S. equity, `easy_to_borrow`, current position/open-order reconciliation, whole shares, and explicit position intent | Infer eligibility from signal or use fractional/notional sells | More broker reads before sell-to-open | Prevents unsupported or misrouted short orders and fails closed when eligibility is unknown. |
| DD-057 | Short exit safety | Treat buy-to-close as risk-reducing, preserve provider/account routing, and close the exact reconciled quantity even when entry eligibility later fails | Apply entry gates to covers or round fractional residuals down | Requires direction-aware routing and an operator-action state when the broker cannot accept an exact close | Avoids trapping or misrouting an existing short and prevents residual exposure. |
| DD-035 | Global dry run | One global dry-run/live control gates Polymarket and Alpaca live submission | Separate dry-run toggle per venue | Simpler operation, less venue-specific flexibility | User requested one global dry-run mode. |
| DD-036 | Alpaca account isolation | Separate Alpaca account identifiers per environment and model provider | Shared account with tags only, separate API keys to the same account | Better attribution and risk separation, more account setup | Required to compare Claude and OpenAI cleanly. |
| DD-037 | Cross-market comparison | Normalize performance by model provider, venue, environment, and instrument type | Separate dashboards only | More analytics work, better experiment readout | Core product goal is comparing model behavior across venues. |
| DD-038 | Alpaca order shape | Use notional market and limit orders by default with fractional shares enabled where supported | Whole-share quantity orders only | Easier USD risk limits, broker support can vary by asset | User risk limits are USD-based, so notional orders fit v1. |
| DD-039 | Alpaca market-hours policy | Regular market hours only, no extended-hours trading in v1 | Extended-hours trading allowed | Fewer opportunities, lower execution ambiguity | Avoids thinner-liquidity and special-session behavior. |
| DD-040 | Comparison metric windows | Dashboard supports all-time, daily, trailing 7-day, and trailing 30-day windows | One all-time view only | More query work, better experiment readout | Makes Claude/OpenAI and venue comparison usable. |
| DD-041 | Main portfolio source of truth | Reconcile balances, positions, fills, and P&L from authenticated venue account APIs | Derive portfolio totals from internal order intents and simulated positions | Adds bounded venue polling and snapshots, prevents unfilled or simulated orders from appearing as actual performance | The main dashboard must answer whether confirmed venue trades are making money. |
| DD-042 | Dashboard change delivery | PostgreSQL commit notifications feed one listener per backend task, which fans out scoped WebSocket invalidations and retains polling only as recovery | Rebuild every connected user's snapshot on a fixed timer, add Redis, or remove polling fallback | Removes steady-state read amplification without adding infrastructure; notifications are non-durable, so reconnects require a full snapshot | PostgreSQL is already the source of truth and delivers `NOTIFY` only after commit. |
| DD-043 | Dashboard information architecture | Use five primary destinations: Overview, Activity, Performance, Settings, and Help; keep specialist model, market, scenario, and system routes behind contextual links | Keep the current mixed primary nav and More menu | Reduces top-level choices while preserving specialist tools and deep links | The design handoff makes the operator's next decision the organizing principle. |
| DD-044 | Overview state precedence | Derive one state with live trade first, actionable attention second, and all-clear last | Let the user select a display state or render all status panels together | The page remains deterministic and concise; state derivation must be covered by unit tests | Prototype controls must not reach production and a real order placement is the most urgent state. |
| DD-045 | Dashboard component strategy | Compose small route-specific views over the existing typed API client and realtime store, using the installed Lucide, Recharts, and AG Grid packages only where the information requires them | Rewrite the API, add another state system, or install a new design library | Limits change risk and bundle growth while allowing the UI hierarchy to change | Existing data contracts and infrastructure already satisfy the handoff. |
| DD-046 | Responsive primary navigation | Keep all five destinations visible in a single desktop row and a compact five-column mobile row with text labels | Hide destinations in an overflow menu or allow horizontal page scrolling | Uses more header height on small screens but keeps location and choices explicit | The handoff requires every primary destination to remain visible. |
| DD-047 | Recommendation safety | Confirm exact before-and-after values and retain a one-change undo action through the audited config endpoint | Apply recommendations immediately or build a separate rollback service | Adds one confirmation step but prevents accidental risk changes and reuses existing versioned config writes | Recommendations can affect live-money eligibility and need an attributable reversal path. |
| DD-048 | Funding source of truth | Treat documented venue account activity as the authoritative record for completed deposits and withdrawals | Bank-webhook ingestion, manual ledger entries, infer cash flow from balance changes | Venue activity can arrive late and needs reconciliation, but avoids storing bank data or misclassifying market P&L | Funding status should match the venue that holds the trading account. |
| DD-049 | Funding schedule storage | Store validated owner-specific funding schedules inside the existing versioned configuration document; store materialized occurrences in dedicated shared tables | Add mutable schedule tables, use an external scheduler | Reuses audit and conflict handling, while occurrences remain durable execution records | Configuration defines intent and occurrence rows prove what became due. |
| DD-050 | Funding idempotency | Derive one unique occurrence key from environment, venue, account reference, provider scope, schedule identifier, due time, direction, and execution mode before external work; permit at most one Broker API transfer POST for that occurrence | Broker-generated identifiers only, time-window deduplication | Deterministic keys require stable normalized inputs, but survive retries and process restarts; an ambiguous POST outcome requires read-only reconciliation | A persisted local intent and request fingerprint must precede any transfer request. |
| DD-051 | Business-day calendar | Use `America/New_York`, weekends, and the United States federal-holiday calendar; move due occurrences forward to the next business day and catch up unmaterialized due occurrences after worker downtime | Calendar days, previous business day, exchange-only holidays | Federal holidays do not cover every broker closure, but provide a deterministic banking schedule | The default applies to ACH expectations and is configurable only through a later requirement. |
| DD-052 | Missing-deposit matching | Match one completed cash flow one-to-one by sanitized account reference, direction, amount within `0.01 USD`, and completion time in the closed interval from due time through four business days after due time; mark it missing only after that interval closes | Exact timestamp match, FIFO amount-only match, operator-only matching | Same-amount overlapping deposits can remain ambiguous and must not be guessed | Conservative matching prevents double attribution and false success. |
| DD-053 | External-cash-flow returns | Use only completed cash flows at their effective completion time; represent deposits as positive and withdrawals as negative; calculate adjusted P&L as `EMV - BMV - sum(CF)` and Modified Dietz return as `(EMV - BMV - sum(CF)) / (BMV + sum(w * CF))` | Raw venue P&L only, simple return, time-weighted subperiod chaining | Modified Dietz is an approximation when intraday valuations are sparse | It removes external funding from strategy results and prevents pending, failed, rejected, or returned transfers from changing results. |
| DD-054 | Direct transfer boundary | Support only incoming Alpaca ACH through the Broker API with separate Broker credentials and an existing ACH relationship; do not integrate Plaid | Trading API transfer calls, raw bank fields, Plaid onboarding | Requires separate Alpaca entitlement and secret references | The application can submit a transfer without collecting bank-account data. |
| DD-055 | Direct transfer safety defaults | Deploy direct transfers disabled with per-transfer and monthly caps set to zero, allow at most one pending transfer per account, and never auto-retry terminal failures | Enable with seeded caps, reuse trading live mode alone, retry failures automatically | Operators must explicitly configure several controls before use | Funding moves external cash and needs an independent control plane in addition to the global kill switch. |
| DD-056 | Funding worker placement | Run funding reconciliation after confirmed portfolio refreshes in the existing backend task under a Postgres job lock | New ECS service, request-driven reconciliation only | Shares task capacity but avoids a second deployable service | The workload is small and already depends on current portfolio snapshots and scheduler locks. |

## 5. Cross-Cutting Concerns

### 5.1 Error Handling Strategy

The system uses defensive error handling. Trading paths refuse action when required inputs are missing, stale, unsupported, or unverified. Non-trading paths keep running when safe, with degraded dashboard status. Every refusal creates an audit event with a reason.

Examples:

- Missing wallet secret blocks live orders, not dashboard access.
- Stale market data blocks dependent trades, not ingestion retry.
- LLM scoring failure blocks the current model-market order, not other providers.
- Postgres unavailable blocks live orders because persistence is required before execution.

### 5.2 Data Integrity

Postgres is the source of truth for config, positions, orders, audits, budgets, brokerage account metadata, comparison metrics, and ingestion checkpoints. The schema uses separate model provider schemas for Claude and OpenAI. Shared records such as config, users, audit events, venue settings, Alpaca account mode settings, and deployment state live in the shared schema. In v1, audit, trade, order, and position records have no TTL, delete job, or archive policy; they are retained indefinitely.

Invariants:

- Live orders cannot be submitted unless the intended order event can be persisted.
- Every order decision has one model provider, venue, environment, and strategy context.
- Every dashboard config change has an audit record.
- Money, size, price, probability, P&L, and slippage use fixed precision decimals.
- Private keys are never stored in Postgres or returned by dashboard APIs.
- Every order intent has a unique idempotency key built from environment, venue, model provider, market, side, position intent, account mode, sanitized account reference, strategy set, config version, and loop run ID.
- Every worker loop runs against one immutable config version.
- Every background job has a durable `job_runs` record with status, lock owner, started timestamp, finished timestamp, heartbeat timestamp, and error summary.
- Order, position, config, and audit writes use database transactions.
- Unique constraints prevent duplicate open positions for the same environment, venue, model provider, market, and outcome unless a later requirement allows pyramiding.
- A market/model reservation prevents the trading loop and exit loop from creating conflicting live orders for the same environment, venue, model provider, market, and outcome.
- New Alpaca short positions may be created only when shorting is explicitly enabled and broker eligibility passes. Existing short positions remain signed and exactly coverable when entry eligibility later fails. Long exits are sell-to-close and short exits are buy-to-close for the exact reconciled absolute quantity.

### 5.2.1 Scheduler Concurrency and Config Snapshots

The v1 backend process owns the background loops, but each loop must acquire a Postgres advisory lock and create a `job_runs` row before doing work. If a previous run of the same job is still active and its heartbeat is current, the scheduler skips the new run and records a skipped status. If the previous heartbeat is stale, the scheduler marks the old run as abandoned before taking the lock.

Each loop reads a single active config version at start and uses that version until the loop finishes. Dashboard changes create new config versions and apply to the next loop. This prevents a trading decision from using one risk limit at scoring time and a different limit at execution time.

If the ECS service later scales beyond one backend task, the Postgres lock remains the single-runner guard. If Postgres is unavailable, trading and execution jobs do not run because they cannot persist decisions safely.

### 5.2.2 Order Lifecycle, Idempotency, and Reconciliation

The execution service persists an order intent before any live submission. The intent includes idempotency key, config version, dry-run/live mode, venue, model provider, market, side, position intent, Alpaca account mode, sanitized account reference, order type, requested size, price guardrails, strategy signals, and risk decision.

Before an entry or exit decision can create an order intent, the execution service creates a reservation for environment, venue, model provider, instrument identifier, and outcome or side. Entry reservations and exit reservations use the same table and cannot overlap. A reservation is released when the order reaches a terminal state, the decision is refused, or a stale reservation timeout is reached and reconciliation confirms no active order exists.

Order states:

```text
INTENDED -> SUBMITTING -> SUBMITTED -> PARTIALLY_FILLED -> FILLED
                         -> CANCEL_REQUESTED -> CANCELED
                         -> REJECTED
                         -> UNKNOWN_SUBMIT
                         -> FAILED
```

If a venue submit call times out after the request may have reached the venue, the system marks the order `UNKNOWN_SUBMIT` and starts reconciliation before retrying. Reconciliation queries open orders, fills, and positions through the official client where supported. The system does not submit a replacement order for the same idempotency key while the original order is unknown.

Partial fills update the position and remaining open order size. Cancel failures move the order to `CANCEL_REQUESTED` with retry metadata. The execution service retries cancel requests with exponential backoff and surfaces failures in the dashboard.

For Alpaca, reconciliation treats the broker as the source of actual holdings, open orders, buying power, account ID, and account status. Postgres remains the source of bot decisions and audit history. Before Alpaca live orders, the system reconciles Alpaca account ID, buying power, open orders, and positions against Postgres. If manual broker activity, partial fills, cancel races, splits, dividends, symbol changes, or broker adjustments create an unresolved mismatch, Alpaca live orders for the affected model provider are blocked until the mismatch is recorded and resolved or manually acknowledged.

### 5.2.3 Kill Switch Behavior

The kill switch is an immediate control-plane override. It does not wait for the next normal trading loop config reload. The API write path commits the disabled-live state and active kill-switch state in one transaction before returning success to the dashboard.

Kill switch activation is ordered:

1. Write a new config version with live trading disabled for all models and venues.
2. Persist an audit event for the user, timestamp, environment, and IP address.
3. Mark the kill switch as active in shared state.
4. Stop new live order creation immediately across in-flight and future loop work.
5. Attempt to cancel every known open live order for every venue that has open live orders, even if the venue was disabled after the order was created.
6. Record each cancel attempt, success, failure, retry, and unresolved order.
7. Show kill-switch status in the dashboard until all cancel attempts reach `CANCELED`, `NO_LONGER_OPEN`, or `MANUAL_REVIEW_ACKNOWLEDGED`.

If canceling open orders fails for one venue, the system keeps live trading disabled globally and marks dashboard status as degraded. Dry-run recording can continue only if configured to do so after kill switch activation.

### 5.2.4 Ingestion Consistency

Full and incremental ingestion jobs use separate job types, but incremental jobs cannot run while a full snapshot job is active for the same environment and venue. Each ingestion job writes raw payloads to deterministic S3 object paths partitioned by environment, venue, snapshot type, and UTC date:

```text
s3://{bucket}/{environment}/{venue}/{snapshot_type}/dt={YYYY-MM-DD}/{window_id}.{extension}
```

`snapshot_type` values include `raw-full`, `raw-incremental`, and `normalized`. `window_id` is derived from the full snapshot date or incremental checkpoint window, not from the job run ID, so a retry can reuse the same logical object path. The job run ID is stored in object tags and Postgres metadata. The job validates that the payload is non-empty when the venue reports available data, calculates a checksum, writes normalized output, then persists object metadata and checkpoint updates in one database transaction.

Checkpoints advance only after S3 writes and metadata persistence both succeed. If S3 succeeds but Postgres checkpoint persistence fails, the next job can reuse the deterministic object path and metadata checksum to avoid duplicate logical ingestion. If validation fails, the job marks the snapshot corrupt, does not advance the checkpoint, and surfaces degraded ingestion status.

S3 retention is enforced with CloudFormation-managed lifecycle rules:

- Raw full snapshots: expire after 365 days.
- Raw incremental snapshots: expire after 365 days.
- Normalized snapshots: expire after 730 days.
- Failed or corrupt snapshot quarantine objects: expire after 30 days.

The application writes object tags for `environment`, `venue`, `snapshot_type`, `normalized`, and `job_run_id` so lifecycle rules can target raw and normalized data separately.

### 5.2.5 Seeded Risk Defaults

The first migration seeds shared configuration with these defaults:

- `live_enabled`: `false`.
- `default_selected_venue`: `polymarket_us`.
- All venue enabled flags: `false`.
- `max_position_usd`: `25.00`.
- `max_daily_loss_usd`: `50.00`.
- `max_open_positions`: `5`.
- `market_order_slippage_threshold`: `0.02`.
- `alpaca_max_position_usd`: `100.00`.
- `alpaca_max_daily_loss_usd`: `100.00`.
- `alpaca_max_open_positions`: `5`.
- `alpaca_max_portfolio_allocation_per_symbol`: `0.10`.
- `alpaca_market_order_slippage_threshold`: `0.005`.
- `alpaca_allowed_asset_classes`: `stocks`, `etfs`.
- `alpaca.allow_shorting`: `false`.
- `alpaca_allow_margin`: `false`.
- `trading_loop_interval_seconds`: `900`.
- `max_kelly_fraction`: `0.25`.

Environment-specific overrides are stored as config versions in Postgres. The dashboard edits those config versions rather than editing bootstrap secrets.

### 5.2.6 Credential Refresh

The secrets adapter caches secrets by secret name, environment, venue, account mode, and model provider with a configurable TTL, defaulting to 5 minutes. A config version change that touches wallet, brokerage account, venue, or credential references invalidates the matching cache entries. If a venue rejects credentials, the adapter marks the credential state stale, clears the cache entry, and reloads from Secrets Manager or local `.env` on the next credential read.

For Alpaca, the adapter reads the account identifier from the broker after credential load. If two model providers in the same environment and Alpaca account mode resolve to the same account identifier, the system blocks Alpaca live trading for the duplicated account and surfaces the duplicate-account refusal in the dashboard.

Credential refresh never logs secret values. It logs only secret identifiers, provider, environment, venue, model provider, and refresh status.

### 5.3 Performance Considerations

The v1 scale target is up to 500 markets per venue every 60 seconds. The system reduces LLM cost and latency by applying deterministic filters before model scoring. API calls should use batch endpoints where official clients support them. Background loops should avoid blocking the FastAPI request path. If v1 background loops create API latency or deployment risk, the documented next step is to split them into separate ECS services.

Initial targets:

- Dashboard read endpoints should respond in under 500 ms at p95 for normal status views.
- Configuration writes should respond in under 1 second at p95 after audit persistence.
- LLM calls should have provider-specific timeouts, defaulting to 30 seconds per market scoring request.
- Venue and brokerage API calls should use retries with capped exponential backoff for read operations.
- Each LLM provider has a bounded scoring queue, configurable concurrency, and configurable rate-limit settings. Defaults are 5 concurrent requests per provider and provider-specific backoff on rate-limit responses.
- Budget is reserved before a scoring request is sent. If the provider returns actual cost, the reservation is reconciled to actual cost after completion.
- Candidate markets that pass deterministic filters but cannot be scored within provider budget, rate-limit, or loop deadline are recorded as `DEFERRED`, are not eligible for live orders in that loop, and are considered again in the next loop.
- A market is eligible for model-specific live trading only after that model provider has produced a current score for the market in the active config version.
- Full ingestion should complete before the next scheduled full run and should not block dashboard access.
- Worker loops should emit heartbeat records at least once per minute while active.

### 5.4 Security Considerations

The dashboard uses GitHub OAuth with a username allowlist. Next.js owns the OAuth flow and sends a signed session token to FastAPI for protected API calls. FastAPI validates token signature, expiration, issuer, audience, and username allowlist before configuration writes, live-mode toggles, wallet status reads, and kill-switch actions. FastAPI must not accept an unsigned trusted header as proof of identity.

Deployed secrets live in AWS Secrets Manager. Local secrets live in gitignored `.env` files. Codex web and CI should not need production trading secrets to run tests.

AWS and web controls:

- RDS storage is encrypted at rest with KMS.
- S3 buckets block public access and use KMS encryption.
- Secrets Manager secrets use KMS encryption and least-privilege IAM access.
- ECS task roles are scoped to only the buckets, secrets, logs, SES identities, and database access needed by the environment.
- GitHub Actions uses AWS OIDC roles scoped separately for development and production deployment.
- Dashboard cookies use `HttpOnly`, `Secure`, and `SameSite=Lax` or stricter settings.
- Mutation endpoints require CSRF protection or same-origin signed session validation.
- FastAPI CORS allows only the configured dashboard origin for the active environment.

Sensitive actions:

- Toggle dry-run/live mode.
- Change venue flags.
- Change Alpaca account mode.
- Change model budgets or risk limits.
- Generate wallets.
- Activate kill switch.
- Rotate secrets.

All sensitive actions require an allowlisted user and produce audit records.

### 5.5 Observability

The backend emits structured logs for ingestion, scoring, strategy decisions, risk checks, orders, exits, notifications, config changes, and health. AWS deployments send logs to CloudWatch. Every trading loop, scoring request, order intent, venue submission, and audit event carries a correlation ID. The dashboard shows recent audit events, worker health, stale data indicators, model budgets, positions, orders, refusals, and notification delivery status.

Metrics and alarms:

- Worker heartbeat age by job type.
- Trading loop duration and skipped loop count.
- Ingestion success, failure, and checkpoint age.
- Venue API error rate and timeout count.
- LLM provider error rate, timeout count, and budget remaining.
- Live order refusal, submit, fill, cancel, unknown, and failure counts.
- SES delivery success and failure counts.
- Alpaca market data age by symbol.
- Alpaca rate-limit and timeout count.
- Alpaca account buying-power age.
- Alpaca broker/Postgres reconciliation mismatch count.
- Alpaca rejected order reasons.
- Comparison metric freshness by model provider, venue, and time window.

Audit events are append-only at the application layer. Updates that correct data create new audit events rather than overwriting existing events.

### 5.6 Compliance and Venue Boundaries

The system supports Polymarket US, Polymarket International, Kalshi, and Alpaca through explicit venue flags. The default selected venue is Polymarket US, but event-market venues remain disabled until an authorized user enables one, while the active stock profile enables Alpaca explicitly. The design does not include VPN, proxy, or other bypass behavior. Kalshi local and development traffic is pinned to the recommended demo host and production traffic to the recommended production host. Alpaca supports long stocks and ETFs and, when explicitly enabled, easy-to-borrow U.S. equity shorts during regular market hours only. Extended-hours trading is disabled. Live trading is blocked if venue, credential scope, provider account identity, brokerage, account mode, jurisdiction, trading-hours, market calendar, halt status, tradability, account shorting eligibility, or market-data configuration is unsupported or incomplete.

### 5.7 Retry and Timeout Policy

Read operations, ingestion downloads, SES sends, and cancel attempts use capped exponential backoff with jitter. Live order submission does not blindly retry after ambiguous failure. If submit state is unknown, reconciliation runs before another order can be created for the same idempotency key.

Default timeout guidance:

- Venue reads: 10 seconds.
- Venue order submit: 15 seconds.
- Venue cancel: 15 seconds.
- Alpaca account and position reads: 10 seconds.
- Alpaca order submit: 15 seconds.
- Alpaca cancel: 15 seconds.
- LLM scoring: 30 seconds.
- SES send: 10 seconds.
- S3 put/get: 30 seconds.

The LLD may tune these defaults by module, but it must preserve the no-blind-retry rule for live order submission.

### 5.8 Strategy and Risk Defaults

The strategy engine produces separate signals for arbitrage, convergence, whale-copy, and Alpaca stock/ETF candidates. Deterministic filters run before LLM scoring and include venue enabled state, market active/closed state, stale data, minimum liquidity, hours to resolution, spread, trading hours, asset tradability, symbol universe, and category allow/deny settings. Disabled strategies are ignored in consensus. Neutral signals count as no vote. Missing LLM scores block model-specific live orders for that instrument in that loop.

Default strategy boundaries:

- Arbitrage groups related markets by configured relation metadata first, then by explicit admin-maintained relation groups. If no relation exists, the arbitrage strategy does not score the market.
- Convergence compares the model estimated probability to current midpoint and requires the configured minimum gap before emitting a directional signal.
- Whale-copy requires configured target wallets, a configured delay, and matching venue/market/outcome data before emitting a signal. The default delay is 60 seconds.
- Alpaca stock/ETF candidate scoring uses configured symbol universes, latest market data, account buying power, current positions, and LLM thesis output. It may emit long-entry, short-entry, hold, or neutral signals; reconciled position direction determines the exit side.
- Alpaca market-hours checks use Alpaca's clock/calendar endpoints where available and broker-provided asset tradability state. Holidays, early closes, suspended symbols, halted symbols, non-tradable assets, and per-symbol stale quotes block live orders for the affected symbol.
- Alpaca market-data rate limits are explicit refusal reasons. Rate-limited symbols are marked `DEFERRED_RATE_LIMITED`, shown in dashboard status, and reconsidered on the next loop.

The default consensus rule is:

- Two or more enabled strategies agree: full risk-approved position.
- One enabled strategy agrees: half of the risk-approved position.
- Enabled strategies disagree on direction: no trade.
- Equal buy and sell votes: no trade.
- No enabled strategy emits a directional signal: no trade.

The Kelly sizing formula uses fractional Kelly with a configurable cap. The default max Kelly fraction is 0.25 before applying max position, max daily loss, and max open position limits.

Market order slippage is estimated from current order book depth for Polymarket and from current Alpaca market data where available for stocks and ETFs. The default Polymarket threshold is 2 percent, the default Alpaca threshold is 0.5 percent, and market order size must still fit all position and daily loss limits. If order book or market data is unavailable or stale, market orders are refused.

Model budget accounting is checked before a scoring request is sent and recorded after a provider response or timeout. If the final provider cost differs from the estimate, the persisted budget ledger records both estimated and actual cost where the provider exposes actual cost. If only one provider scores an instrument, only that provider can create a model-specific decision; each model trades against its own budget, wallet, and Alpaca account credentials.

### 5.8.1 Alpaca Execution Defaults

Global dry-run mode gates Alpaca and Polymarket together. When global dry-run is enabled, Alpaca decisions are persisted as simulated orders and are not submitted to Alpaca paper or live endpoints. When global dry-run is disabled, Alpaca can submit approved orders to the configured Alpaca account mode for that environment and model provider.

Alpaca supports buy-to-open and sell-to-close for long positions. It supports sell-to-open only when `alpaca.allow_shorting` is true and current broker account, buying-power, asset, borrow, whole-share, reconciliation, and market-hours entry gates pass. An existing short uses buy-to-close for the exact reconciled absolute quantity even if shorting is later disabled or entry eligibility fails. Entry and exposure-increasing orders are refused for margin-funded long purchases, unsupported products, hard-to-borrow or unknown borrow status, an existing position or unresolved order, allocation breaches, position-limit breaches, daily-loss breaches, and open-position-count breaches. Exact risk-reducing exits bypass those entry limits but retain credential, persistence, routing, market-hours, and venue-availability gates.

Alpaca order defaults:

- Order sizing uses USD notional values.
- Fractional shares are allowed where Alpaca and the asset support them.
- New short entries require whole shares. Long entries may use supported fractional notional orders. Exits use the exact reconciled quantity and never round a residual position down.
- If rounding makes an order smaller than the broker minimum or configured minimum notional, the order is refused.
- Default time in force is `day`.
- Extended-hours flag is always `false` in v1.
- Partial fills update filled notional, filled quantity, average fill price, remaining quantity, and realized or unrealized P&L where applicable.

Risk limits apply cumulatively within their scope. Shared defaults apply to Polymarket unless a venue-specific limit is configured. Alpaca orders use Alpaca-specific position, daily loss, open-position, allocation, asset-class, direction, short-eligibility, and slippage checks, plus global live/venue/credential/stale-data checks. The default Alpaca position cap is `100.00 USD`, the default Alpaca daily loss cap is `100.00 USD`, and the default Alpaca open-position cap is `5`, unless the dashboard changes them. The 10 percent per-symbol allocation denominator is the configured Alpaca model capital for that model provider in that environment. If configured capital is missing or non-positive, Alpaca live orders are refused.

### 5.8.2 Alpaca Ingestion Scope

For Alpaca, daily full ingestion stores the configured symbol universe, asset metadata, previous-market-day bars where available, current account snapshot, current positions, open orders, and recent order activity. Incremental ingestion stores changed account state, positions, orders, fills, quotes or bars for configured symbols, and market-data staleness metadata since the last checkpoint.

Corporate actions, splits, dividends, and symbol changes are captured when Alpaca exposes them through the selected data plan or account activity feed. If corporate-action data is unavailable but a position mismatch suggests one occurred, reconciliation marks the symbol as blocked for live trading until reviewed.

### 5.9 Notification Defaults

The daily digest is sent through SES once per day after the 06:00 UTC full ingestion window. The default send time is 07:00 UTC. Recipients come from the GitHub OAuth username allowlist, mapped to configured email addresses in shared configuration. A user without a configured email address is skipped and shown as incomplete in dashboard notification settings.

Large-movement alert defaults:

- Position P&L move: at least `25.00 USD` or `10 percent`.
- Daily realized or unrealized P&L move: configurable, seeded to `25.00 USD`.
- Daily drawdown: configurable, seeded to `50.00 USD`.
- Cooldown: 30 minutes per environment, venue, model provider, and market.

Notification deduplication uses a unique alert key made from environment, venue, model provider, market, alert type, threshold, and cooldown window. SES send attempts are persisted with status, retry count, provider message ID when available, and error summary. Failed SES sends use capped exponential backoff with jitter.

### 5.10 Deployment Environment Separation

The `develop` branch deploys to a development CloudFormation stack. The `main` branch deploys to a production CloudFormation stack. The stacks use separate names, ECR services, ECS services, task definitions, RDS databases or database instances, S3 buckets, Secrets Manager secret paths, SES configuration, CloudWatch log groups, config rows, and wallets.

Naming pattern:

```text
codex-poly-bot-{environment}-{resource}
```

Secrets pattern:

```text
/codex-poly-bot/{environment}/{venue}/{model_provider}/{secret_name}
```

Development and production do not share wallet private keys, venue API credentials, model API keys, Postgres schemas, or S3 buckets. GitHub Actions chooses the target stack only from the branch ref, not from user-supplied workflow input.

### 5.11 Dashboard Model Separation

The dashboard has a combined overview plus separate Claude and OpenAI views. Each model view shows positions, decisions, strategy signals, budget usage, P&L, refusals, and recent order events for that provider, grouped by Polymarket, Kalshi, and Alpaca. Shared system views show ingestion, venue status, Kalshi credential and reconciliation freshness, Alpaca account mode and health, audit log, notifications, environment health, and kill switch state.

Performance uses venue-confirmed account APIs for actual portfolio value, realized and unrealized P&L, open holdings, and confirmed fills. It groups Polymarket US, Kalshi, and Alpaca by provider account, blocks Kalshi live exposure when provider account fingerprints collide, preserves the last confirmed snapshot when refresh fails, and marks missing values unavailable. Submitted, unfilled, and simulated orders are excluded. Overview receives only a compact current-status result and a link to Performance. AI and AWS costs remain in economics views rather than being mixed into actual venue P&L.

Comparison views calculate P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics by model provider, venue, environment, instrument type, and time window. Supported windows are all-time, current trading day, trailing 7 days, and trailing 30 days. Missing or insufficient data is shown as unavailable rather than zero.

Metric definitions:

- Realized P&L: closed trade proceeds minus cost basis and recorded fees for the selected window.
- Unrealized P&L: current mark value minus open cost basis. Alpaca uses latest broker market data; Polymarket uses latest market midpoint or settlement value when resolved.
- Net P&L: realized P&L plus unrealized P&L minus recorded fees and recorded model cost for the selected window.
- Win rate: closed winning trades divided by closed trades with non-zero realized P&L.
- Drawdown: maximum peak-to-trough decline in cumulative realized plus unrealized equity curve for the selected window.
- Model cost: recorded LLM provider cost for scoring requests in the selected window.
- Open exposure: current notional value at risk across open positions.
- Confirmed Performance trade count: venue orders that reached `FILLED` or `PARTIALLY_FILLED`. Canceled, rejected, refused, unknown, unfilled, and simulated orders are excluded.
- Experiment comparison trade count: confirmed trades use the same definition as Performance. A comparison view may show simulated terminal outcomes as a separate, explicitly labeled simulation metric, but shall not combine them with confirmed trade counts, win rate, or P&L.
- Return-to-risk: net P&L divided by maximum drawdown when drawdown is positive; unavailable when drawdown is zero or insufficient data exists.

Fees are included when captured from the venue or broker. If fees are unavailable, the metric records `fees_unavailable=true` and shows a caveat in the dashboard detail view.

### 5.12 Dashboard Information Architecture

The authenticated shell has five primary destinations: Overview, Activity, Performance, Settings, and Help. The header remains sticky, shows the current location without relying on color alone, and exposes all five destinations at desktop and mobile widths. Existing operations, model, market, scenario, comparison, data, and system routes remain valid. `/dashboard/operations` remains the detailed operations and emergency-stop route. It is linked from Activity and Settings. Specialist routes are reached from contextual links inside the five primary pages instead of a global overflow menu.

Overview answers whether the operator needs to act now. It derives one state from the latest persisted or realtime snapshot. A latest non-simulated placed order produces the live-trade state. Otherwise, a blocked funnel stage, degraded critical section, missing required configuration, or notification gap produces the attention state. Otherwise the page renders all-clear. The live-trade state takes precedence because it represents current market exposure. The attention state contains a prioritized blocker list and at most three recommendations. Other states do not render recommendations.

Activity owns the latest funnel and recent check records. Performance owns venue-confirmed Equity, Realized P&L, Unrealized P&L, Open positions, Win rate, and Trades, the Market, Trades, Win rate, and P&L table, confirmed holdings and fills, and links to specialist provider comparison. Settings owns configuration, presents common controls before advanced controls, and provides a visually distinct route to the existing emergency stop. Help is static and presents Collect prices, Find candidates, Score, Simulate or submit, and Monitor exits in that order. Each page consumes the existing typed REST and WebSocket snapshot contracts. Missing financial values remain unavailable, and stale data retains the last confirmed value with one consolidated explanation.

The redesign uses the existing frontend dependencies. Charts are limited to trends that cannot be read faster from a value or table. Animation is limited to short feedback transitions, is transform or opacity based, and is disabled by `prefers-reduced-motion`.

### 5.13 Funding Integrity and Safety

The shared schema stores two funding record types. `venue_cash_flows` contains normalized, venue-confirmed deposits and withdrawals. `funding_occurrences` contains deterministic expectations and direct-transfer attempts. Both use fixed-precision USD values and persist only an allowlist of normalized fields. Raw funding payloads are not retained. The tables retain records indefinitely and never accept hard deletion through the dashboard.

Cash-flow uniqueness uses environment, venue, sanitized account reference, and venue transaction identifier. Provider attribution is a set so two credential paths that resolve to one account do not double-count the transaction. Occurrence uniqueness uses the deterministic idempotency key. Database constraints enforce both keys. Ambiguous cash flows remain unmatched and visible for review.

Schedule configuration supports `weekly`, `monthly`, and `low_balance` cadence. A weekly schedule stores an ISO weekday. A monthly schedule stores a day from 1 through 31 and uses the last calendar day when a month is shorter. Weekly and monthly schedules run at 09:00 in `America/New_York`, following local daylight-saving transitions; weekend and United States federal-holiday dates move forward. Each worker run materializes every due but unmaterialized occurrence through the current time so downtime does not skip an occurrence. Low-balance evaluation runs only after a successful confirmed portfolio refresh and uses confirmed available-to-trade balance. Its requested amount is `max(0, target balance - confirmed available-to-trade balance)` and is never greater than the configured schedule amount, per-transfer cap, or remaining calendar-month cap. The monthly cap includes pending and completed direct transfers.

Execution modes are `observe` and `direct`. Observe mode never makes a funding write. Direct mode is valid only for Alpaca incoming ACH. Immediately before the external call, the funding service acquires an account-scoped Postgres lock, reads the current control state, and atomically reserves both the pending-transfer slot and monthly amount. The call is allowed only after the application confirms all of these controls:

- funding direct transfers are enabled;
- the global kill switch and funding emergency stop are inactive;
- the amount is positive and within nonzero per-transfer and monthly limits;
- the account has no pending direct transfer;
- separate Alpaca Broker API credentials, a Broker account reference, and an approved ACH relationship reference are available;
- Postgres is available, the occurrence and request fingerprint are committed, and the transfer reservation is current.

Any failed control persists a refusal without calling Alpaca and releases an unused reservation. One occurrence can issue at most one transfer POST. The occurrence persists its request fingerprint before that POST and the provider transfer identifier as soon as it is available. A network timeout or ambiguous response after submission leaves the occurrence in `unknown` and reconciliation-only state; the application never repeats the POST. `unknown` consumes the account pending-transfer slot and reserved monthly amount until reconciliation proves a terminal state. Rejected, returned, and failed transfers are terminal and require a newly authorized occurrence. The global kill switch and funding emergency stop are read again while the account lock is held, block writes immediately, and do not stop read-only reconciliation, missing-deposit detection, or recovery alerts.

Exact Alpaca Broker account and ACH relationship identifiers are resolved at call time from Secrets Manager or the equivalent gitignored local secret bootstrap. They never enter Postgres config versions, funding rows, audits, logs, or API responses. Config stores a non-secret secret-reference name and sanitized display label only.

The dashboard does not receive raw account identifiers, ACH relationship identifiers, Broker credentials, routing numbers, account numbers, or unredacted venue payloads. It receives stable display labels, provider attribution, amounts, direction, schedule state, venue state, timestamps, and alert state. Funding schedule changes use the existing allowlist authorization, optimistic config version, validation, audit event, and realtime invalidation flow.

Funding alerts use a stable key containing environment, account reference hash, occurrence id, and transition type. A unique transition outbox row is committed before delivery. A missing, rejected, returned, or failed transition creates at most one logical alert; a later match creates at most one recovery alert. Transport uncertainty can retry delivery through the existing capped retry policy without creating a second logical transition. Notification delivery failure does not change the occurrence state.

Performance keeps both raw venue equity movement and adjusted trading results available to the service layer. Only completed cash flows, at their effective completion timestamps, enter return calculations. Deposits are positive cash flows and withdrawals are negative cash flows. The main dashboard uses adjusted trading P&L `EMV - BMV - sum(CF)` and Modified Dietz return `(EMV - BMV - sum(CF)) / (BMV + sum(w * CF))`, where `w` is the fraction of the period remaining after each completed cash flow. If the weighted capital denominator is zero or negative, percentage return is unavailable rather than zero. The API includes total completed deposits and withdrawals so the adjustment is explainable.

## 6. Module Map

| Module | File or Directory | Responsibility | Dependencies |
|--------|-------------------|----------------|--------------|
| Backend app | `backend/app/main.py` | FastAPI application bootstrap and lifecycle | config, auth, routers, workers |
| API routers | `backend/app/api/` | REST and status endpoints for dashboard | services, schemas |
| Domain models | `backend/app/domain/` | Core types for markets, signals, orders, positions, config, audit | decimal, pydantic |
| Config service | `backend/app/services/config_service.py` | Read, validate, update, and audit runtime config | repositories, audit |
| Auth service | `backend/app/services/auth_service.py` | API-side GitHub allowlist authorization | config repository |
| Venue ports | `backend/app/ports/venue.py` | Interfaces for market data and order execution | domain |
| Polymarket adapters | `backend/app/adapters/polymarket/` | Polymarket US and International API/SDK integrations | venue ports, secrets |
| Alpaca adapter | `backend/app/adapters/alpaca/` | Alpaca account, market data, calendar, asset, position, and order integrations | venue ports, secrets |
| Ingestion service | `backend/app/services/ingestion_service.py` | Full and incremental data ingestion orchestration | venue adapters, S3, repositories |
| S3 adapter | `backend/app/adapters/aws/s3.py` | Snapshot storage and retention metadata | boto3 |
| Secrets adapter | `backend/app/adapters/aws/secrets.py` | AWS Secrets Manager access | boto3 |
| SES adapter | `backend/app/adapters/aws/ses.py` | Email sending | boto3 |
| Database | `backend/app/db/` | SQLAlchemy session, repositories, schemas | SQLAlchemy |
| Migrations | `backend/alembic/` | Database migrations | Alembic |
| Wallet service | `backend/app/services/wallet_service.py` | Wallet generation and wallet status | secrets, repositories |
| Wallet CLI | `backend/app/cli/wallets.py` | CLI wallet generation command | wallet service |
| LLM ports | `backend/app/ports/llm.py` | Provider-neutral scoring interface | domain |
| OpenAI adapter | `backend/app/adapters/llm/openai_provider.py` | OpenAI scoring implementation | LLM port |
| Claude adapter | `backend/app/adapters/llm/anthropic_provider.py` | Claude scoring implementation | LLM port |
| Scoring service | `backend/app/services/scoring_service.py` | Budget checks, prompt versioning, scoring persistence | LLM adapters, repositories |
| Strategy engine | `backend/app/strategies/engine.py` | Strategy coordination and consensus | strategy modules, scoring |
| Arbitrage strategy | `backend/app/strategies/arbitrage.py` | Related-market price dislocation signals | domain |
| Convergence strategy | `backend/app/strategies/convergence.py` | Model estimate convergence signals | domain |
| Whale-copy strategy | `backend/app/strategies/whale_copy.py` | Target wallet signals with delay settings | ingestion, repositories |
| Alpaca stock strategy | `backend/app/strategies/alpaca_stock.py` | Long-only stock and ETF candidate signals | Alpaca adapter, scoring |
| Risk engine | `backend/app/services/risk_engine.py` | Kelly sizing, limits, refusal checks, slippage checks | config, repositories |
| Execution service | `backend/app/services/execution_service.py` | Dry-run and live order routing | risk, venue adapters, repositories |
| Exit monitor | `backend/app/services/exit_monitor.py` | Exit trigger evaluation and exit decisions | repositories, execution |
| Notification service | `backend/app/services/notification_service.py` | Daily digest and large movement alerts | SES, repositories |
| Comparison service | `backend/app/services/comparison_service.py` | Cross-model and cross-venue performance metrics | repositories |
| Funding service | `backend/app/services/funding_service.py` | Schedule materialization, cash-flow reconciliation, safety checks, alerts, and adjusted return calculations | portfolio service, repositories, notification service, funding transfer port |
| Funding transfer port | `backend/app/ports/funding.py` | Provider-neutral direct-transfer and transfer-status contract | domain funding types |
| Alpaca Broker funding adapter | `backend/app/adapters/alpaca/funding.py` | Entitled incoming ACH submission and transfer status reads | HTTP client, secret references |
| Worker scheduler | `backend/app/workers/scheduler.py` | Background loops and config reload | services |
| Audit service | `backend/app/services/audit_service.py` | Audit event creation and retrieval | repositories |
| Frontend app | `frontend/` | Next.js React dashboard | backend API |
| Auth UI | `frontend/app/auth/` | GitHub OAuth session handling | NextAuth or equivalent |
| Dashboard UI | `frontend/app/dashboard/` | Status, config, positions, orders, model comparison, kill switch | API client |
| Frontend API client | `frontend/lib/api.ts` | Typed calls to FastAPI | fetch |
| Infrastructure | `infra/cloudformation/` | ECS, ECR, RDS, S3, Secrets Manager, SES, IAM, CloudWatch | AWS |
| CI/CD | `.github/workflows/` | Tests, image build, ECR push, ECS deploy | GitHub Actions, AWS OIDC |
| Local development | `docker-compose.yml`, `.env.example` | Local Postgres, backend, frontend setup | Docker |
| Codex setup | `AGENTS.md`, `scripts/setup_codex.sh` | Codex web guidance and safe test setup | docs, scripts |
| Documentation | `docs/` | Design notes, runbooks, deployment guide | requirements, design |

## 7. Risk Register

| Risk | Impact | Likelihood | Mitigation | When to Address |
|------|--------|------------|------------|-----------------|
| Live trading with incorrect config | High | Medium | Default dry-run, venue disabled by default, refusal checks, audit logs | Phase 1 implementation and tests |
| Private key leakage | High | Medium | Secrets Manager in AWS, gitignored `.env`, no dashboard private key display, Codex without prod secrets | Foundation and deployment |
| Polymarket or Alpaca API/SDK changes | High | Medium | Adapter boundary, contract tests, official docs references | Venue adapter design and tests |
| Postgres outage or driver mismatch during trading | High | Low | Use the packaged `psycopg` SQLAlchemy driver and block live orders when persistence is unavailable | Risk engine implementation and deployment checks |
| Dashboard auth bypass | High | Low | GitHub OAuth, username allowlist, API-side authorization checks, Playwright auth tests | Dashboard implementation |
| Background loops slow API requests | Medium | Medium | Async worker scheduling, non-blocking request path, future ECS split plan | Worker implementation and monitoring |
| LLM cost overrun | Medium | Medium | Per-provider budgets, deterministic pre-filters, budget exhaustion behavior | Scoring service |
| Market orders exceed acceptable slippage | High | Medium | Estimated slippage guardrails, default 2 percent for Polymarket and 0.5 percent for Alpaca, risk cap | Execution engine |
| Alpaca live account misconfiguration | High | Medium | Separate credentials per model/environment, account mode config, dry-run default, account health checks | Alpaca adapter and risk engine |
| Borrow, account, quote, market-hours, position, or order state changes between decision and submit | High | Medium | Refresh registered account identity, clock, latest ask, asset, current position, and open orders immediately before sell-to-open; fail closed on missing or stale values | Phase 10 adapter and execution tests |
| Short loss grows as price rises | High | Medium | Existing position, allocation, daily-loss, stop-loss, trailing-stop, and close-before-market-close limits apply to absolute short exposure; no pyramiding | Phase 10 risk and lifecycle tests |
| Broker recall or forced buy-in | High | Low | Reconcile broker state, preserve broker as holding source of truth, alert on unexpected fill/position changes, and block new entry on mismatch | Phase 10 reconciliation and operations evidence |
| Short cover is rounded, wrong-sided, or sent to the wrong account | High | Low | Exact reconciled quantity, buy-to-close intent, provider/account routing, and no-submit mismatch tests | Phase 10 execution and exit tests |
| Stock orders outside market hours | Medium | Medium | Trading-hours checks, stale data refusal, order status reconciliation | Alpaca adapter and execution engine |
| Cross-market comparison uses incomplete data | Medium | Medium | Unavailable metric state, provider/venue grouping, audit trails | Comparison service |
| S3 ingestion costs or data growth | Medium | Medium | Retention policy, partitioned paths, normalized outputs | Ingestion implementation |
| Automatic production deploy ships broken code | High | Medium | CI tests before build/deploy, migration checks, image build gates | CI/CD setup |
| SES alerts create noise | Low | Medium | Alert thresholds and 30-minute cooldown per market/model | Notification service |
| One ECS service becomes overloaded | Medium | Medium | Keep service boundaries clean and document split into worker services | HLD and future plan |
| Duplicate or ambiguous deposit attribution | High | Medium | Venue transaction uniqueness, provider-set merging, conservative occurrence matching, visible unmatched state | Funding repository and reconciliation tests |
| Unintended direct bank transfer | High | Low | Disabled and zero-limit defaults, separate Broker credentials, committed occurrence, one pending transfer, independent emergency stop, no live transfer in deployment tests | Funding service and deployment configuration |
| Late, rejected, or returned ACH state | High | Medium | Venue reconciliation, terminal failure states, one transition alert, recovery alert, no automatic terminal retry | Funding worker and notification tests |
| Deposit inflates reported trading return | High | Medium | Venue cash-flow ledger, adjusted P&L formula, Modified Dietz calculation, dashboard disclosure | Portfolio and performance tests |
| Bank or credential data reaches logs or UI | High | Low | Store sanitized references only, normalized-field persistence allowlist, response allowlist, and log-boundary tests | Adapter, API, and security tests |

## 8. Requirements Coverage Summary

| Requirement IDs | Covered By HLD Sections |
|-----------------|-------------------------|
| REQ-VEN-001, REQ-VEN-002, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-VEN-006 | Venue adapters, venue flags, risk refusals |
| REQ-ALP-001 through REQ-ALP-026 | Alpaca adapter, stock/ETF scope, account isolation, global dry-run, Alpaca risk defaults, short eligibility and position intent, signed reconciliation, exits |
| REQ-KAL-001 through REQ-KAL-014 | Kalshi adapter, market data, provider account isolation, fixed-point orders, durable reconciliation, portfolio, dashboard, and deployment evidence |
| REQ-DAT-001, REQ-DAT-002, REQ-DAT-003, REQ-DAT-004, REQ-DAT-005, REQ-DAT-006, REQ-DAT-007, REQ-DAT-008 | Ingestion service, S3 adapter, retention policy |
| REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005, REQ-DB-006, REQ-DB-007, REQ-DB-008, REQ-DB-009, REQ-DB-010 | Postgres repositories, schemas, migrations, venue portfolio records, scanner transactions, commit notifications |
| REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-005, REQ-WAL-006, REQ-WAL-007 | Wallet service, wallet CLI, Secrets Manager |
| REQ-FND-001, REQ-FND-002, REQ-FND-003, REQ-FND-004, REQ-FND-005, REQ-FND-006, REQ-FND-007, REQ-FND-008, REQ-FND-009, REQ-FND-010, REQ-FND-011, REQ-FND-012, REQ-FND-013, REQ-FND-014, REQ-FND-015, REQ-FND-016, REQ-FND-017, REQ-FND-018, REQ-FND-019, REQ-FND-020 | Funding source-of-truth decisions, occurrence idempotency, funding service and repository, Alpaca Broker funding adapter, audited settings, sanitized dashboard history, cash-flow-adjusted performance |
| REQ-LLM-001, REQ-LLM-002, REQ-LLM-003, REQ-LLM-004, REQ-LLM-005, REQ-LLM-006, REQ-LLM-007 | LLM ports, provider adapters, scoring service |
| REQ-STR-001, REQ-STR-002, REQ-STR-003, REQ-STR-004, REQ-STR-005, REQ-STR-006, REQ-STR-007, REQ-STR-008, REQ-STR-009 | Strategy engine and strategy modules |
| REQ-EXE-001, REQ-EXE-002, REQ-EXE-003, REQ-EXE-004, REQ-EXE-005, REQ-EXE-006, REQ-EXE-007, REQ-EXE-008, REQ-EXE-009, REQ-EXE-010, REQ-EXE-011, REQ-EXE-012, REQ-EXE-013, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-EXE-017 | Risk engine, execution service, global dry-run, kill switch |
| REQ-EXT-001, REQ-EXT-002, REQ-EXT-003, REQ-EXT-004, REQ-EXT-005, REQ-EXT-006 | Exit monitor and execution integration |
| REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010, REQ-UI-011, REQ-UI-012, REQ-UI-013, REQ-UI-014, REQ-UI-015, REQ-UI-016, REQ-UI-017, REQ-UI-018, REQ-UI-019, REQ-UI-020, REQ-UI-021, REQ-UI-022, REQ-UI-023, REQ-UI-024, REQ-UI-025, REQ-UI-026 | Next.js dashboard, GitHub OAuth, five-page information architecture, data-derived overview state, focused activity and performance views, audited settings, static help, accessible responsive navigation, confirmed portfolio, event-driven WebSocket updates, bounded polling recovery |
| REQ-CMP-001, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004, REQ-CMP-005 | Comparison service and dashboard model/venue analytics |
| REQ-NOT-001, REQ-NOT-002, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005, REQ-NOT-006, REQ-NOT-007 | Notification service and SES adapter |
| REQ-DEP-001, REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-DEP-010 | CloudFormation, GitHub Actions, Docker, Codex setup |
| REQ-OBS-001, REQ-OBS-002, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006 | Structured logs, audit service, dashboard health |

## 9. Kalshi Venue Extension

### 9.1 Goals and Non-Goals

The extension adds Kalshi to the existing layered monolith without changing the scheduler, model-provider comparison, or database ownership model. It optimizes for safe REST integration, exact fixed-point arithmetic, explicit credential boundaries, reuse of the prediction-market scanner and reasoning path, and fail-closed live execution.

This release does not support multivariate-event markets, RFQ, FIX, non-primary subaccounts, WebSocket streaming, historical public trade backfills, automated deposits, or live-money deployment smoke orders. Historical authenticated account reconciliation is in scope because Kalshi partitions older user records from live endpoints.

### 9.2 Architecture

```text
Kalshi REST markets and batch books
              |
              v
ProviderBackedMarketDataFetcher -> normalized prediction candidates
              |                              |
              v                              v
       Scanner and Brain ------------> Strategy Consensus
                                              |
                                              v
                                 Shared and Kalshi risk gates
                                              |
                         dry run -------------+------------- live
                            |                                  |
                            v                                  v
                     simulated intent                Kalshi V2 adapter
                                                               |
                                      balance, positions, fills, settlements
                                                               |
                                                               v
                                              venue portfolio and dashboard
```

### 9.3 Design Decisions

| ID | Decision | Choice | Rationale |
|----|----------|--------|-----------|
| DD-058 | Client boundary | Direct documented REST integration with `httpx` and `cryptography` | Kalshi identifies the OpenAPI specification and REST documentation as the production source of truth; direct integration also matches existing provider patterns and makes non-retry behavior explicit. |
| DD-059 | Market scope | Standard binary markets only, with multivariate markets excluded | The domain represents one market with YES and NO outcomes; excluding multivariate contracts prevents ambiguous instrument mapping. |
| DD-060 | Numeric representation | Use field-specific unit conversion and `Decimal`, including cents-to-USD balance conversion, dollar price strings, contract quantity strings, and six-decimal fee intermediates | Kalshi mixes integer cents with fixed-point dollar and quantity strings, so a generic conversion can produce 100x account errors. |
| DD-061 | Environment routing | Local and development use only `external-api.demo.kalshi.co`; production uses only `external-api.kalshi.com`; no dashboard host override | Demo and production credentials are not interchangeable, and an allowlisted host prevents endpoint crossover. |
| DD-062 | Order safety | V2 YES-book orders, market-specific tick validation, stable client order ID, persisted unknown-submit state, no automatic POST retry, primary subaccount, and fresh exchange/account checks | This prevents duplicate exposure, invalid prices, and new risk based on stale or ambiguous state. |
| DD-063 | Reconciliation | Read one live balance; paginate live positions, fills, settlements, and orders; and use only historical fills and orders behind cutoff checkpoints | Scheduled REST reconciliation matches the documented partition boundary without inventing historical position or settlement endpoints. |
| DD-064 | Deployment | Kalshi is configurable and market-data capable after deploy, but live submission remains credential-gated and no live order is used as release evidence | Production availability can be proven without creating financial exposure. |
| DD-065 | Provider isolation | OpenAI and Claude use distinct credentials; sorted authenticated `/api_keys` membership sets are hashed into sanitized account fingerprints; read scope is required for reconciliation and write scope for live orders | Separate verified accounts prevent position netting, self-trade collisions, and unreliable provider-level risk attribution. |
| DD-066 | Disablement and cancellation | Disablement blocks new exposure but preserves reconciliation, exits, and known-order cancellation | Operators must be able to reduce risk after disabling a venue or activating the kill switch. |

### 9.4 Cross-Cutting Concerns

- Security: RSA private keys are persisted only in the approved AWS secret store, injected into the process environment, parsed in memory, and excluded from application persistence, logs, API responses, fixtures, and screenshots. Requests use RSA-PSS SHA-256 over `<millisecond timestamp><UPPERCASE METHOD><full query-free path>`; credential or clock-skew rejection fails closed.
- Reliability: safe GET requests use at most three total attempts for network, 429, and retryable 5xx failures. A POST is never retried. A later cancel attempt occurs only after reconciliation confirms the same known order remains open. Scheduled execution rereads the persisted config and kill switch after scoring and immediately before execution. Disabled-venue quote reads target the exact confirmed open-position tickers and bypass scanning and reasoning.
- Data integrity: candidates, orders, positions, fills, fees, and settlements use field-specific `Decimal` unit conversions and stable venue identifiers. Failed refresh data is marked degraded and cannot authorize new exposure.
- Observability: venue calls emit sanitized provider, operation, status, duration, attempt, and error-code fields without tickers in high-cardinality metric names or any credential material.
- Performance: open markets use cursor pagination and batch order books capped at 100 tickers per request, then the configured scan limit bounds downstream candidates.

### 9.5 Module Additions

| Module | File | Responsibility | Dependencies |
|--------|------|----------------|--------------|
| Kalshi adapter | `backend/app/venues/kalshi.py` | RSA signing, authenticated REST calls, V2 orders, status, cancel, balance, positions, fills, and settlements | `httpx`, `cryptography`, venue result contract |
| Kalshi market data | `backend/app/services/market_data_provider.py` | Public market pagination, batch order books, candidate normalization | Kalshi REST API, scanner config |
| Kalshi orchestration | `backend/app/services/runtime_status_service.py`, `lifecycle_service.py` | Venue enablement, credentials, submitter routing, risk, and reconciliation | config, adapter, repositories |
| Kalshi portfolio | `backend/app/services/venue_portfolio_service.py` | Account, position, fill, settlement, and P&L normalization | Kalshi adapter, shared portfolio tables |
| Kalshi dashboard | `frontend/components/dashboard/`, `frontend/lib/` | Venue controls, labels, credential readiness, market activity, and performance | dashboard API |
| Kalshi deployment | `infra/cloudformation.yml`, environment examples, release scripts and docs | Endpoint flags and Secrets Manager injection | GitHub Actions, AWS ECS |
| Domain and config | `backend/app/domain/models.py`, `backend/app/main.py`, `backend/app/bootstrap.py`, `backend/app/services/config_service.py` | Venue enum, prediction-market classification, safe defaults, validation | shared domain and config contracts |
| Execution and risk | `backend/app/services/execution_service.py`, `backend/app/services/risk_engine.py` | YES-book translation, IOC limits, fresh-state and provider-isolation gates | lifecycle, adapter, repositories |
| Persistence and API | `backend/app/db/`, `backend/app/api/`, `backend/app/services/dashboard_service.py` | unknown-submit state, checkpoints, sanitized read models | Postgres, dashboard auth |
| Scheduler and tests | `backend/app/main.py`, `backend/tests/spec/`, frontend behavior scripts | polling cadence, reconciliation, full trace evidence | runtime wiring, CI |

### 9.6 Order Translation and State Safety

Kalshi V2 quotes only the YES book. The shared decision is translated as follows. Every submitted `price` is a YES-book price and is checked against the selected interval in `market.price_ranges`.

| Normalized outcome | Intent | V2 `side` | YES-book price source | `reduce_only` |
|--------------------|--------|-----------|-----------------------|---------------|
| YES | Enter or add long | `bid` | Slippage-capped YES ask | `false` |
| YES | Exit or reduce long | `ask` | Slippage-floored YES bid | `true` |
| NO | Enter or add long | `ask` | `1 -` slippage-capped NO ask | `false` |
| NO | Exit or reduce long | `bid` | `1 -` slippage-floored NO bid | `true` |

The lifecycle persists `SUBMITTING` before dispatch. A pre-dispatch validation or signing failure becomes `REFUSED`. A timeout, 429, or 5xx after dispatch begins becomes `UNKNOWN_SUBMIT`; the client order ID remains reserved and replacement exposure is blocked. Reconciliation reads current and historical orders and fills, live and archived positions, and live settlements until the intent resolves or an operator records review. Disablement and the kill switch still permit reconciliation, exits, and cancellation of known orders.

Authenticated batch order-book bids, including complementary asks derived from the opposite book, are authoritative for execution. Public summary prices are informational only. Empty book liquidity cannot be marked fresh or live eligible. Before sizing an entry, the service reads the event fee override and parent series fee configuration. Supported quadratic fees use the current multiplier, the taker formula, conservative centicent fragmentation overhead, and an order-level rounding accumulator reserve. Unsupported or missing fee configuration blocks the order.

### 9.7 Unit Contract

| Source field family | Source unit | Internal unit | Conversion and precision |
|---------------------|-------------|---------------|--------------------------|
| `balance`, `portfolio_value` | Integer cents | USD Decimal | Divide by 100; two-decimal display, exact Decimal storage |
| `*_dollars`, V2 `price` | Fixed-point dollars | USD or probability-price Decimal | Preserve up to four decimal places; validate by `price_ranges` |
| `*_fp`, V2 `count` | Fixed-point contracts | Contract Decimal | Preserve two decimal places; minimum 0.01 |
| Fees, costs, settlement revenue | Endpoint-specific cents or fixed-point dollars | USD Decimal | Convert by documented field, keep six-decimal intermediates, round final currency half-even |
| P&L | Derived USD | USD Decimal | Revenue minus cost minus fees, with stable fill and settlement deduplication; per-position unrealized P&L remains unavailable until a confirmed venue mark exists |

### 9.8 Live Gates and Release Evidence

Exposure-increasing orders require venue enablement, an active market and exchange, market and account snapshots no older than 60 seconds, distinct provider accounts, no unknown or conflicting entry or exit, valid market price ranges, current supported fee configuration, RSA credentials, and shared risk approval. Scheduled execution receives the persisted kill-switch state. Exit and cancel flows remain available when the venue is disabled or the kill switch is active, and scheduled market-data reads continue for confirmed open Kalshi positions.

Development and production release evidence records commit SHA, workflow URL and conclusion, stack ID and status, ECS task definition and image digest, effective sanitized host and secret references, credential-readiness state, HTTPS health and OAuth boundary results, a public market GET, missing-secret live refusal, and a time-bounded audit or CloudWatch query showing zero Kalshi POST or DELETE operations during the release window. When all six credential secrets are configured, evidence also includes a successful authenticated batch order-book read, each provider's authenticated balance converted from cents to USD, and unchanged order and fill counts. When none are configured, evidence records an explicit not-configured mode and blocked runtime readiness. A partial secret set fails the release. Rollback triggers include failed mandatory CI, unstable ECS services, failed health or auth checks, environment crossover, incomplete configuration, or any unexpected Kalshi mutation.

### 9.9 Requirements Coverage

| Requirement IDs | Covered By HLD Sections |
|-----------------|-------------------------|
| REQ-KAL-001 through REQ-KAL-003 | DD-059, DD-060; market-data and orchestration modules |
| REQ-KAL-004 through REQ-KAL-007 | DD-058, DD-061, DD-062; adapter, credentials, and lifecycle modules |
| REQ-KAL-008, REQ-KAL-009 | DD-063, DD-065; portfolio and dashboard modules |
| REQ-KAL-010 | DD-061, DD-064; deployment module and production release evidence |
| REQ-KAL-011, REQ-KAL-012 | DD-065, DD-066; lifecycle and cancellation modules |
| REQ-KAL-013, REQ-KAL-014 | DD-060, DD-063; normalization and historical reconciliation modules |
