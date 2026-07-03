# codex-poly-bot High-Level Design

**Spec ID:** SPEC-CODEX-POLY-BOT  
**Version:** 1.0  
**Date:** 2026-04-24  
**Status:** DRAFT  
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
| Alpaca options, crypto, short selling, or margin trading | v1 stock-market trading is limited to long-only stocks and ETFs. |

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
+--------------------+        REST/SSE        +----------------------+
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
```

### 3.3 Component Overview

| Component | Responsibility | Owns Data? | Key Interfaces |
|-----------|----------------|------------|----------------|
| Venue integration | Fetch market data and submit orders through official SDK/API clients | No | `VenueClient`, `MarketDataPort`, `OrderExecutionPort` |
| Alpaca brokerage integration | Trade long-only stocks and ETFs through separate Alpaca accounts per model provider | No | `BrokerageClient`, `AccountMode`, `StockMarketDataPort` |
| Data ingestion | Full and incremental downloads, normalization, S3 writes, checkpoints | Yes, ingestion checkpoints and S3 object metadata | `IngestionService`, `S3StoragePort` |
| Postgres persistence | Config, positions, orders, audits, budgets, model-specific schemas | Yes | SQLAlchemy repositories, Alembic migrations |
| Wallet and secrets | Wallet generation CLI, brokerage credential lookup, secret lookup, wallet and account status | Yes, wallet/account metadata only | `WalletService`, `SecretStorePort` |
| LLM scoring | Run OpenAI and Claude market evaluations with budget checks | Yes, scoring records and prompt versions | `ScoringService`, `LlmProviderPort` |
| Strategy engine | Arbitrage, convergence, whale-copy signals and consensus rules | Yes, signal records | `StrategyEngine`, strategy modules |
| Risk and execution | Kelly sizing, dry-run/live mode, guardrails, stock risk limits, order routing, kill switch | Yes, order decisions and refusal events | `RiskEngine`, `ExecutionService` |
| Exit monitor | Profit target, volume spike, and stale thesis exit decisions | Yes, exit decisions | `ExitMonitor` |
| Dashboard and auth | GitHub OAuth, config UI, status UI, kill switch UI | No, writes config through API | Next.js pages, API client |
| Notifications | SES digest and threshold alerts | Yes, delivery attempts and cooldown state | `NotificationService`, `EmailPort` |
| Comparison analytics | Compare model performance across Polymarket and Alpaca | Yes, derived metric snapshots | `ComparisonService`, dashboard API |
| Deployment and Codex setup | CloudFormation, GitHub Actions, local Docker, Codex docs | No | workflow files, templates, setup scripts |
| Observability | Structured logs, audit events, dashboard health | Yes, audit and health records | `AuditService`, logger adapters |

### 3.4 Data Flow

Primary trading loop:

1. The backend scheduler reads active config from Postgres.
2. The venue adapter scans enabled venues only, including enabled Polymarket venues and Alpaca stock or ETF universes.
3. The strategy engine applies deterministic filters to reduce candidate markets.
4. The LLM scoring service sends eligible candidates to Claude and OpenAI, subject to each model budget.
5. Each model provider writes scoring output to its own schema.
6. Strategy modules generate arbitrage, convergence, whale-copy, and stock/ETF candidate signals where applicable.
7. The risk engine calculates size, checks dry-run/live mode, venue flags, account mode, wallet or brokerage credential state, stale data, position limits, daily loss, open positions, long-only constraints, and slippage.
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
| DD-034 | Alpaca scope | Stocks and ETFs only, long-only cash trading | Options, crypto, shorting, margin | Smaller opportunity set, lower complexity and risk | Matches v1 scope and avoids margin/short-specific controls. |
| DD-035 | Global dry run | One global dry-run/live control gates Polymarket and Alpaca live submission | Separate dry-run toggle per venue | Simpler operation, less venue-specific flexibility | User requested one global dry-run mode. |
| DD-036 | Alpaca account isolation | Separate Alpaca account identifiers per environment and model provider | Shared account with tags only, separate API keys to the same account | Better attribution and risk separation, more account setup | Required to compare Claude and OpenAI cleanly. |
| DD-037 | Cross-market comparison | Normalize performance by model provider, venue, environment, and instrument type | Separate dashboards only | More analytics work, better experiment readout | Core product goal is comparing model behavior across venues. |
| DD-038 | Alpaca order shape | Use notional market and limit orders by default with fractional shares enabled where supported | Whole-share quantity orders only | Easier USD risk limits, broker support can vary by asset | User risk limits are USD-based, so notional orders fit v1. |
| DD-039 | Alpaca market-hours policy | Regular market hours only, no extended-hours trading in v1 | Extended-hours trading allowed | Fewer opportunities, lower execution ambiguity | Avoids thinner-liquidity and special-session behavior. |
| DD-040 | Comparison metric windows | Dashboard supports all-time, daily, trailing 7-day, and trailing 30-day windows | One all-time view only | More query work, better experiment readout | Makes Claude/OpenAI and venue comparison usable. |

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
- Every order intent has a unique idempotency key built from environment, venue, model provider, market, side, strategy set, config version, and loop run ID.
- Every worker loop runs against one immutable config version.
- Every background job has a durable `job_runs` record with status, lock owner, started timestamp, finished timestamp, heartbeat timestamp, and error summary.
- Order, position, config, and audit writes use database transactions.
- Unique constraints prevent duplicate open positions for the same environment, venue, model provider, market, and outcome unless a later requirement allows pyramiding.
- A market/model reservation prevents the trading loop and exit loop from creating conflicting live orders for the same environment, venue, model provider, market, and outcome.
- Alpaca positions cannot become negative in v1. Sell orders for Alpaca are sell-to-close only and cannot exceed the lower of broker-reconciled quantity and Postgres-recorded quantity for that symbol.

### 5.2.1 Scheduler Concurrency and Config Snapshots

The v1 backend process owns the background loops, but each loop must acquire a Postgres advisory lock and create a `job_runs` row before doing work. If a previous run of the same job is still active and its heartbeat is current, the scheduler skips the new run and records a skipped status. If the previous heartbeat is stale, the scheduler marks the old run as abandoned before taking the lock.

Each loop reads a single active config version at start and uses that version until the loop finishes. Dashboard changes create new config versions and apply to the next loop. This prevents a trading decision from using one risk limit at scoring time and a different limit at execution time.

If the ECS service later scales beyond one backend task, the Postgres lock remains the single-runner guard. If Postgres is unavailable, trading and execution jobs do not run because they cannot persist decisions safely.

### 5.2.2 Order Lifecycle, Idempotency, and Reconciliation

The execution service persists an order intent before any live submission. The intent includes idempotency key, config version, dry-run/live mode, venue, model provider, market, side, order type, requested size, price guardrails, strategy signals, and risk decision.

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
- `alpaca_allow_shorting`: `false`.
- `alpaca_allow_margin`: `false`.
- `trading_loop_interval_seconds`: `60`.
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

The system supports Polymarket US, Polymarket International, and Alpaca through explicit venue flags. The default selected venue is Polymarket US, but all venues are disabled until an authorized user enables a venue in configuration. The design does not include VPN, proxy, or other bypass behavior. Alpaca v1 is limited to long-only stocks and ETFs during regular market hours only. Extended-hours trading is disabled in v1. Live trading is blocked if venue, brokerage, account mode, jurisdiction, trading-hours, market calendar, halt status, tradability, or market-data configuration is unsupported or incomplete.

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
- Alpaca stock/ETF candidate scoring uses configured symbol universes, latest market data, account buying power, current positions, and LLM thesis output. It emits long-entry, hold, sell-to-close, or neutral signals only.
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

Alpaca v1 supports buy-to-open and sell-to-close only. The risk engine refuses any order that would create a short position, require margin, trade an unsupported asset class, exceed the configured symbol allocation limit, exceed the stock position limit, exceed the daily loss limit, or exceed the open stock position count.

Alpaca order defaults:

- Order sizing uses USD notional values.
- Fractional shares are allowed where Alpaca and the asset support them.
- If fractional shares are not supported for a symbol, the risk engine rounds down to the largest whole-share quantity that stays within all risk limits.
- If rounding makes an order smaller than the broker minimum or configured minimum notional, the order is refused.
- Default time in force is `day`.
- Extended-hours flag is always `false` in v1.
- Partial fills update filled notional, filled quantity, average fill price, remaining quantity, and realized or unrealized P&L where applicable.

Risk limits apply cumulatively within their scope. Shared defaults apply to Polymarket unless a venue-specific limit is configured. Alpaca orders use Alpaca-specific position, daily loss, open-position, allocation, asset-class, long-only, and slippage checks, plus global live/venue/credential/stale-data checks. This means the default Alpaca position cap is `100.00 USD`, the default Alpaca daily loss cap is `100.00 USD`, and the default Alpaca open-position cap is `5`, unless the dashboard changes them. The 10 percent per-symbol allocation denominator is the configured Alpaca model capital for that model provider in that environment. If configured capital is missing or non-positive, Alpaca live orders are refused.

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

The dashboard has a combined overview plus separate Claude and OpenAI views. Each model view shows positions, decisions, strategy signals, budget usage, P&L, refusals, and recent order events for that provider, grouped by Polymarket and Alpaca. Shared system views show ingestion, venue status, Alpaca account mode and health, audit log, notifications, environment health, and kill switch state.

Comparison views calculate P&L, win rate, drawdown, model cost, open exposure, trade count, and return-to-risk metrics by model provider, venue, environment, instrument type, and time window. Supported windows are all-time, current trading day, trailing 7 days, and trailing 30 days. Missing or insufficient data is shown as unavailable rather than zero.

Metric definitions:

- Realized P&L: closed trade proceeds minus cost basis and recorded fees for the selected window.
- Unrealized P&L: current mark value minus open cost basis. Alpaca uses latest broker market data; Polymarket uses latest market midpoint or settlement value when resolved.
- Net P&L: realized P&L plus unrealized P&L minus recorded fees and recorded model cost for the selected window.
- Win rate: closed winning trades divided by closed trades with non-zero realized P&L.
- Drawdown: maximum peak-to-trough decline in cumulative realized plus unrealized equity curve for the selected window.
- Model cost: recorded LLM provider cost for scoring requests in the selected window.
- Open exposure: current notional value at risk across open positions.
- Trade count: live orders that reached `FILLED` or `PARTIALLY_FILLED` plus dry-run simulated orders that reached a terminal simulated-filled state. Canceled, rejected, refused, unknown, and unfilled orders are excluded from trade count and shown separately as order events.
- Return-to-risk: net P&L divided by maximum drawdown when drawdown is positive; unavailable when drawdown is zero or insufficient data exists.

Fees are included when captured from the venue or broker. If fees are unavailable, the metric records `fees_unavailable=true` and shows a caveat in the dashboard detail view.

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
| Postgres outage during trading | High | Low | Block live orders when persistence is unavailable | Risk engine implementation |
| Dashboard auth bypass | High | Low | GitHub OAuth, username allowlist, API-side authorization checks, Playwright auth tests | Dashboard implementation |
| Background loops slow API requests | Medium | Medium | Async worker scheduling, non-blocking request path, future ECS split plan | Worker implementation and monitoring |
| LLM cost overrun | Medium | Medium | Per-provider budgets, deterministic pre-filters, budget exhaustion behavior | Scoring service |
| Market orders exceed acceptable slippage | High | Medium | Estimated slippage guardrails, default 2 percent for Polymarket and 0.5 percent for Alpaca, risk cap | Execution engine |
| Alpaca live account misconfiguration | High | Medium | Separate credentials per model/environment, account mode config, dry-run default, account health checks | Alpaca adapter and risk engine |
| Stock orders outside market hours | Medium | Medium | Trading-hours checks, stale data refusal, order status reconciliation | Alpaca adapter and execution engine |
| Cross-market comparison uses incomplete data | Medium | Medium | Unavailable metric state, provider/venue grouping, audit trails | Comparison service |
| S3 ingestion costs or data growth | Medium | Medium | Retention policy, partitioned paths, normalized outputs | Ingestion implementation |
| Automatic production deploy ships broken code | High | Medium | CI tests before build/deploy, migration checks, image build gates | CI/CD setup |
| SES alerts create noise | Low | Medium | Alert thresholds and 30-minute cooldown per market/model | Notification service |
| One ECS service becomes overloaded | Medium | Medium | Keep service boundaries clean and document split into worker services | HLD and future plan |

## 8. Requirements Coverage Summary

| Requirement IDs | Covered By HLD Sections |
|-----------------|-------------------------|
| REQ-VEN-001, REQ-VEN-002, REQ-VEN-003, REQ-VEN-004, REQ-VEN-005, REQ-VEN-006 | Venue adapters, venue flags, risk refusals |
| REQ-ALP-001, REQ-ALP-002, REQ-ALP-003, REQ-ALP-004, REQ-ALP-005, REQ-ALP-006, REQ-ALP-007, REQ-ALP-008, REQ-ALP-009, REQ-ALP-010, REQ-ALP-011, REQ-ALP-012, REQ-ALP-013, REQ-ALP-014, REQ-ALP-015, REQ-ALP-016, REQ-ALP-017, REQ-ALP-018 | Alpaca adapter, stock/ETF scope, account isolation, global dry-run, Alpaca risk defaults, reconciliation |
| REQ-DAT-001, REQ-DAT-002, REQ-DAT-003, REQ-DAT-004, REQ-DAT-005, REQ-DAT-006, REQ-DAT-007, REQ-DAT-008 | Ingestion service, S3 adapter, retention policy |
| REQ-DB-001, REQ-DB-002, REQ-DB-003, REQ-DB-004, REQ-DB-005, REQ-DB-006, REQ-DB-007 | Postgres repositories, schemas, migrations |
| REQ-WAL-001, REQ-WAL-002, REQ-WAL-003, REQ-WAL-004, REQ-WAL-005, REQ-WAL-006, REQ-WAL-007 | Wallet service, wallet CLI, Secrets Manager |
| REQ-LLM-001, REQ-LLM-002, REQ-LLM-003, REQ-LLM-004, REQ-LLM-005, REQ-LLM-006, REQ-LLM-007 | LLM ports, provider adapters, scoring service |
| REQ-STR-001, REQ-STR-002, REQ-STR-003, REQ-STR-004, REQ-STR-005, REQ-STR-006, REQ-STR-007, REQ-STR-008, REQ-STR-009 | Strategy engine and strategy modules |
| REQ-EXE-001, REQ-EXE-002, REQ-EXE-003, REQ-EXE-004, REQ-EXE-005, REQ-EXE-006, REQ-EXE-007, REQ-EXE-008, REQ-EXE-009, REQ-EXE-010, REQ-EXE-011, REQ-EXE-012, REQ-EXE-013, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-EXE-017 | Risk engine, execution service, global dry-run, kill switch |
| REQ-EXT-001, REQ-EXT-002, REQ-EXT-003, REQ-EXT-004, REQ-EXT-005, REQ-EXT-006 | Exit monitor and execution integration |
| REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-009, REQ-UI-010, REQ-UI-011 | Next.js dashboard, GitHub OAuth, API routers, comparison views |
| REQ-CMP-001, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004 | Comparison service and dashboard model/venue analytics |
| REQ-NOT-001, REQ-NOT-002, REQ-NOT-003, REQ-NOT-004, REQ-NOT-005, REQ-NOT-006, REQ-NOT-007 | Notification service and SES adapter |
| REQ-DEP-001, REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-DEP-005, REQ-DEP-006, REQ-DEP-007, REQ-DEP-008, REQ-DEP-009, REQ-DEP-010 | CloudFormation, GitHub Actions, Docker, Codex setup |
| REQ-OBS-001, REQ-OBS-002, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006 | Structured logs, audit service, dashboard health |
