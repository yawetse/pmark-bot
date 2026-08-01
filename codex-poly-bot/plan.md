# Implementation Plan

## Planning Guidance

| Decision | Approved Direction |
|----------|--------------------|
| Build order | Bottom-up foundation first |
| Milestones | Each major phase produces something runnable or demoable |
| Parallelism | Tasks should be parallelizable across multiple engineers or agents |
| First demo target | Local backend API, Postgres, dry-run trading loop, and dashboard shell |
| Early risk focus | Live-trading safety, auth, and CI/CD |

## Execution Order

| # | Phase | Components | Dependencies | Milestone |
|---|-------|------------|--------------|-----------|
| 1 | Foundation and safety kernel | Local development, Codex setup, Domain models, Database, Migrations, Audit service, Config service, Auth service, Observability skeleton, CI baseline | Approved requirements, HLD, LLD | Local app dependencies install, Postgres migrates, safe default config seeds `default_selected_venue=polymarket_us`, `LIVE_ENABLED=false`, all venues disabled, Polymarket slippage `0.02`, and Alpaca slippage `0.005` |
| 2 | Adapter contracts and credential boundaries | Venue ports, LLM ports, AWS adapters, Secrets adapter, S3 adapter, SES adapter, Polymarket adapters, Alpaca adapter, Wallet service, Wallet CLI | Phase 1 | Mocked adapter contract tests pass; wallet/account status works without exposing secrets |
| 3 | Core dry-run trading engine | Ingestion service, Scoring service, Strategy engine, Arbitrage strategy, Convergence strategy, Whale-copy strategy, Alpaca stock strategy, Risk engine, Execution service, Exit monitor, Notification service skeleton, Comparison service, Worker scheduler | Phases 1-2 | One local dry-run trading loop runs with mocked venues/models and persists decisions, refusals, simulated orders, positions, metrics, worker heartbeats, and no-op notification job status |
| 4 | Backend API and dashboard | Backend app, API routers, Frontend app, Auth UI, Dashboard UI, Frontend API client, venue portfolio read model | Phases 1-3 | Local dashboard signs in, shows status and venue-confirmed portfolio performance, loads user-scoped database preferences, edits config, triggers kill switch, and displays Claude/OpenAI dry-run comparison |
| 5 | External integration and notification logic | Official Polymarket integration, Alpaca paper/live account validation, venue balance/position/fill reconciliation, OpenAI adapter, Claude adapter, notification flows, local/file-backed S3 storage, mocked or existing SES sandbox delivery | Phases 2-4 | Development mode can read confirmed portfolio data and run full dry-run against configured external APIs without live venue submission; AWS-managed S3/SES is still provisioned in Phase 6 |
| 6 | AWS deployment and CI/CD | Infrastructure, CloudFormation templates, GitHub Actions, ECR image build, ECS service, RDS, S3, Secrets Manager, CloudWatch, SES, migration safety | Phases 1-5 | Merge to `develop` deploys the development stack in dry-run mode with health checks passing |
| 7 | Production readiness and runbooks | Documentation, source references, live-trading checklist, operations runbook, rollback runbook, final traceability checks | Phases 1-6 | Merge to `main` deploys production automatically in dry-run mode; live enablement is controlled by checklist and dashboard config |
| 8 | Dashboard information architecture redesign | Five-route shell, data-derived Overview, Activity, Performance, simplified Settings, Help, responsive and accessibility validation | Phases 4 and 7; issue #194; dashboard design handoff | Development and production show the redesigned dashboard with real data, no prototype controls, and all release health checks passing |
| 9 | Recurring funding and direct-transfer controls | Funding domain and config, cash-flow and occurrence persistence, bounded venue activity reads, schedule materialization, reconciliation, alerts, adjusted returns, disabled Alpaca Broker transfer adapter, funding API, Performance history, Settings controls, infrastructure secret references | Phases 4 through 8; REQ-FND-001 through REQ-FND-020; DD-048 through DD-056 | Development and production reconcile venue funding and show adjusted performance; direct transfers remain disabled with zero limits and no real transfer is sent during release verification |

## Dependency Graph

```text
Local development + Codex setup
  -> Domain models
  -> Database + Migrations
  -> Config service + Audit service + Auth service
  -> Observability skeleton + CI baseline

Domain models
  -> Venue ports
  -> LLM ports
  -> Core service contracts

Database + Config + Audit
  -> Ingestion service
  -> Scoring service
  -> Risk engine
  -> Execution service
  -> Worker scheduler
  -> API routers

Venue adapters + Database
  -> Venue portfolio reconciliation
  -> Portfolio API
  -> Main dashboard actual portfolio

Phase 1 explicit suborder:
  Domain models -> Database + Migrations -> Audit service -> Config service -> Auth service -> Observability skeleton -> CI baseline

Venue ports + Secrets adapter
  -> Polymarket adapters
  -> Alpaca adapter
  -> Wallet service + Wallet CLI

LLM ports
  -> OpenAI adapter
  -> Claude adapter
  -> Scoring service

AWS adapters
  -> Ingestion service
  -> Wallet service
  -> Notification service
  -> Infrastructure

Scoring service + Strategy engine
  -> Risk engine
  -> Execution service
  -> Exit monitor
  -> Comparison service
  -> Worker scheduler

Notification service skeleton
  -> Worker scheduler

CloudFormation Infrastructure
  -> AWS-managed S3 snapshot storage
  -> SES delivery in deployed environments
  -> GitHub Actions CI/CD deployment

Backend app + API routers
  -> Frontend API client
  -> Auth UI
  -> Dashboard UI

Existing dashboard contracts + design handoff
  -> Five-route dashboard shell
  -> Data-derived Overview
  -> Activity + Performance
  -> Settings + Help
  -> Accessibility + browser verification

Venue portfolio reconciliation + funding domain
  -> Cash-flow and occurrence persistence
  -> Bounded venue funding-activity sync + coverage watermarks
  -> Weekly/monthly and low-balance materialization
  -> One-to-one reconciliation + missing/recovery alert outbox
  -> Cash-flow-adjusted P&L + Modified Dietz
  -> Funding API + Performance history + Settings controls

Funding persistence + current config + kill switch + secret boundary
  -> Durable one-POST claim
  -> Disabled Alpaca Broker transfer adapter
  -> Development verification with mocked transfer only
  -> Production verification with direct transfers disabled and zero caps

Core services + API + Frontend
  -> GitHub Actions CI/CD
  -> CloudFormation Infrastructure
  -> Documentation and runbooks
```

## Milestones

| Milestone | Demo / Verification | Exit Criteria |
|-----------|---------------------|---------------|
| M1: Safe local foundation | Run local tests and migrations | DB schemas exist, config seeds `default_selected_venue=polymarket_us`, `LIVE_ENABLED=false`, all venues disabled, Polymarket slippage `0.02`, Alpaca slippage `0.005`, auth/audit/config unit tests pass |
| M2: Adapter contract harness | Run mocked adapter contract tests | Polymarket, Alpaca, AWS, OpenAI, and Claude boundaries have stable interfaces and expected failure modes |
| M3: Dry-run trading loop | Run one local loop from CLI or worker | Decisions, risk refusals, simulated orders, and comparison metrics are persisted |
| M4: Local dashboard | Open dashboard locally | GitHub auth gate, per-user database preferences, config editing, kill switch, wallet status, worker health, and comparison views work against local API |
| M5: External dry-run dev | Run dev mode with configured external APIs | Real venue/model API reads work, local/file-backed snapshots write, SES delivery is mocked or uses an existing sandbox identity, no live orders are submitted |
| M6: Development deployment | Merge to `develop` | GitHub Actions deploys dev AWS stack, ECS health passes, CloudWatch logs receive structured events |
| M7: Production dry-run | Merge to `main` | Production stack deploys automatically, remains dry-run by default, live checklist is ready |
| M8: Dashboard IA production release | Verify issue #194 in development and production | Five routes match the handoff hierarchy, real data selects one Overview state, focused pages avoid duplicate information, and desktop/mobile evidence passes |
| M9: Recurring funding production release | Reconcile mocked and venue-confirmed cash flows locally and in development, verify sanitized funding views and adjusted returns, then promote | Funding tables migrate, schedules are audited, missed deposits alert once and recover once, deposits do not inflate trading P&L, production defaults show direct transfers disabled with zero limits, and deployment evidence confirms no Broker POST |

## Parallelization Plan

| Track | Can Start After | Owns | Coordination Point |
|-------|-----------------|------|--------------------|
| Backend foundation | Phase 1 start | Domain, DB, migrations, config, audit, auth | Shared schema and Pydantic types |
| Adapter integrations | Domain and ports exist | Polymarket, Alpaca, AWS, LLM adapters, wallet CLI | Port contracts and credential model |
| Trading core | Foundation plus mocked ports | Ingestion, scoring, strategies, risk, execution, exits, comparison, scheduler | Order/position/reconciliation repositories |
| Dashboard/API | API schema contracts exist | FastAPI routers, Next.js auth, dashboard UI, API client | Field-level API contracts and auth token boundary |
| Dashboard redesign | Existing dashboard APIs and handoff are stable | Navigation, Overview, Activity, Performance, Settings, Help, responsive CSS | Shared realtime data, route ownership, and visual tokens |
| CI baseline | Phase 1 foundation exists | Local test workflow and non-deploy CI checks | Test commands and safe mock defaults |
| AWS deployment infrastructure | Phase 5 external integrations complete | CloudFormation, deploy workflow, ECR/ECS/RDS/S3/CloudWatch/SES | Environment names, secrets paths, migration safety |
| Docs/runbooks | Phase outputs stabilize | Local setup, deployment, live checklist, source references, operations | Must track current commands and deployment flow |
| Funding foundation | Phase 9 start | Domain types, config schema, database tables and indexes, pure calendar and return math | LLD section 28 and migration contract |
| Funding integrations | Funding foundation tests pass | Polymarket and Alpaca activity normalization, Broker port and adapter, secret boundary | Normalized activity and one-POST contract |
| Funding product surface | Funding service and API contract pass | Reconciliation, alerts, API, Performance, Settings | Sanitized response types and versioned config |
| Funding release | All Phase 9 tests pass | CloudFormation refs, dev deploy, prod promotion, evidence | Direct path disabled and no real transfer smoke test |

## Risk Register

| Risk | Impact | Mitigation | When to Address |
|------|--------|------------|-----------------|
| Live trading with incorrect config | High | Seed dry-run and disabled venues, resolve runtime config from the database by explicit or allowlisted owner, implement refusal matrix and audit before any live adapter submit | Phase 1 and Phase 3 |
| Private key leakage | High | Secrets Manager in AWS, gitignored local `.env`, server-only auth token minting, no dashboard secret fields | Phase 1, Phase 2, Phase 4 |
| Polymarket or Alpaca API/SDK changes | High | Adapter ports, contract tests, source references, official SDK/API wrappers | Phase 2 and Phase 5 |
| Postgres outage or deployment driver mismatch during trading | High | Use the packaged `psycopg` SQLAlchemy driver, block live orders without persistence, and surface degraded health | Phase 1 and Phase 3 |
| Dashboard auth bypass | High | GitHub OAuth, username allowlist, FastAPI token validation, CSRF/origin checks, Playwright auth tests | Phase 1 and Phase 4 |
| Background loops slow API requests | Medium | Worker scheduler boundaries, job locks, bounded queues, dashboard read models, future ECS split path | Phase 3 and Phase 4 |
| LLM cost overrun | Medium | Deterministic filters, provider budgets, budget reservations, deferred states | Phase 3 and Phase 5 |
| Market orders exceed acceptable slippage | High | Slippage estimation contract, default thresholds, risk refusal tests | Phase 3 |
| Ambiguous live submit causes duplicate order | High | Persist order intent before submit, use idempotency keys, reconcile unknown state before retry, refuse conflicting orders while unknown | Phase 3 and Phase 5 |
| Alpaca live account misconfiguration | High | Separate account identifiers, reconciliation snapshot, duplicate account blocking, paper/live mode validation | Phase 2, Phase 3, Phase 5 |
| Stock orders outside market hours | Medium | Alpaca clock/calendar checks, stale data status, trading-hours refusal reasons | Phase 2, Phase 3, Phase 5 |
| Cross-market comparison uses incomplete data | Medium | Unavailable metric state, central comparison formulas, dashboard caveats | Phase 3 and Phase 4 |
| S3 ingestion costs or data growth | Medium | S3 lifecycle rules, partitioned keys, normalized/raw retention split | Phase 2 and Phase 6 |
| Automatic production deploy ships broken code | High | CI gates, migration safety policy, RDS restore point, ECS health wait, branch protection | Phase 1 and Phase 6 |
| SES alerts create noise | Low | Thresholds, cooldowns, dedup keys, dashboard settings | Phase 4 and Phase 5 |
| One ECS service becomes overloaded | Medium | Keep module boundaries clean, preserve worker split plan, record loop duration/heartbeat metrics | Phase 3 and Phase 6 |
| Duplicate or wrong-account bank transfer | High | Disabled zero defaults, account routing equality, durable one-POST claim committed before network, account lock, current schedule and kill-switch recheck | Phase 9 persistence, service, and adapter work |
| Late activity creates a false missing alert | High | Persist activity coverage watermark and require coverage past deadline before missing transition | Phase 9 venue sync and reconciliation |
| Deposit inflates strategy return | High | Completed cash-flow ledger, fixed-precision adjusted P&L, boundary-fresh Modified Dietz tests | Phase 9 performance work |
| Bank or relationship data leaks | High | Exact IDs remain secret-source-only, normalized persistence and API allowlists, log-boundary tests | Phase 9 adapter, API, and deployment work |

## Module Coverage

| HLD Module | Plan Phase |
|------------|------------|
| Backend app | Phase 4 |
| API routers | Phase 4 |
| Domain models | Phase 1 |
| Config service | Phase 1 |
| Auth service | Phase 1 |
| Venue ports | Phase 2 |
| Polymarket adapters | Phase 2 and Phase 5 |
| Alpaca adapter | Phase 2 and Phase 5 |
| Ingestion service | Phase 3 |
| S3 adapter | Phase 2 |
| Secrets adapter | Phase 2 |
| SES adapter | Phase 2 and Phase 5 |
| Database | Phase 1 |
| Migrations | Phase 1 and Phase 6 |
| Wallet service | Phase 2 |
| Wallet CLI | Phase 2 |
| LLM ports | Phase 2 |
| OpenAI adapter | Phase 2 and Phase 5 |
| Claude adapter | Phase 2 and Phase 5 |
| Scoring service | Phase 3 |
| Strategy engine | Phase 3 |
| Arbitrage strategy | Phase 3 |
| Convergence strategy | Phase 3 |
| Whale-copy strategy | Phase 3 |
| Alpaca stock strategy | Phase 3 |
| Risk engine | Phase 3 |
| Execution service | Phase 3 |
| Exit monitor | Phase 3 |
| Notification service | Phase 3 and Phase 5 |
| Comparison service | Phase 3 |
| Worker scheduler | Phase 3 |
| Audit service | Phase 1 |
| Frontend app | Phase 4 |
| Auth UI | Phase 4 |
| Dashboard UI | Phase 4 and Phase 8 |
| Frontend API client | Phase 4 |
| Infrastructure | Phase 6 |
| CI/CD | Phase 1 and Phase 6 |
| Local development | Phase 1 |
| Codex setup | Phase 1 |
| Documentation | Phase 7 and Phase 8 |
| Funding service | Phase 9 |
| Funding transfer port | Phase 9 |
| Alpaca Broker funding adapter | Phase 9 |
| Funding persistence and migration | Phase 9 |
| Funding dashboard views | Phase 9 |

## Phase Gates

| Gate | Required Evidence |
|------|-------------------|
| Phase 1 complete | Pytest foundation tests pass, migrations run locally, safe defaults present |
| Phase 2 complete | Adapter contract tests pass with mocked external services, no secret values in API/log outputs |
| Phase 3 complete | Dry-run loop test passes and persists scoring, decisions, refusals, simulated orders, metrics, worker heartbeats, and no-op notification status |
| Phase 4 complete | Playwright dashboard flows pass for auth denial, config update, kill switch, comparison view |
| Phase 5 complete | External API read-only/dry-run integration tests pass with opt-in credentials; AWS-managed S3/SES waits for Phase 6 |
| Phase 6 complete | `develop` deployment succeeds, CloudWatch structured logs visible, ECS health checks pass |
| Phase 7 complete | Runbooks, live checklist, source references, and traceability checks are complete |
| Phase 8 complete | Frontend typecheck and tests pass; design review, code review, accessibility audit, 390-pixel and desktop browser checks pass; issue #194 is updated; development and production deploy and health evidence pass |
| Phase 9 complete | Funding requirement tests, database constraints, adapter contracts, full direct-transfer refusal matrix, scheduler integration, config audit, API and log privacy, explicit no-Polymarket-write/no-Plaid checks, frontend typecheck and behavior tests, CloudFormation validation, shell syntax, and full regression pass; development and production migration/readback show sanitized funding state with direct transfers disabled, both limits `0.00`, health green, and zero Broker POST log events |

## Phase 9 Execution Detail

| Step | Work | Depends On | Verification |
|------|------|------------|--------------|
| 9.1 | Add funding domain types, complete-object config validation, safe defaults, and pure business-day and Modified Dietz helpers | Approved funding LLD | Unit tests for validation, holidays, daylight saving, amount rules, and return denominators |
| 9.2 | Add cash-flow, occurrence, sync-state, and alert-outbox schema plus repository compare-and-set operations and indexes | 9.1 | Migration and repository tests, including concurrency and stale-regression cases |
| 9.3 | Extend Polymarket and Alpaca portfolio sources with normalized, bounded, watermark-backed funding activity | 9.1 and 9.2 | Mocked adapter pagination, activity mapping, deduplication, raw bank/relationship exclusion, no Plaid fields, and explicit no-Polymarket-funding-write tests |
| 9.4 | Implement materialization, low-balance episodes, matching, missing/recovery transitions, and outbox delivery | 9.2 and 9.3 | Deterministic occurrence, coverage, matching, alert, and restart tests |
| 9.5 | Wire `FundingService` into `_portfolio_refresh_loop` with a session-scoped environment job lock, per-account isolation, all-schedule cadence materialization, fresh-snapshot low-balance gating, startup reserved-to-unknown recovery, and funding heartbeat metadata | 9.3 and 9.4 | Integration tests prove lock skip/release, one failing account does not block others, fixed cadences run during refresh failure, low balance requires freshness, startup recovery is reconciliation-only, and heartbeat counts are safe |
| 9.6 | Implement Alpaca Broker port and adapter plus durable claim and conservative unknown reconciliation | 9.2 through 9.5 | Mocked HTTP contracts prove one POST and refusal before adapter call for disabled direct mode, emergency stop, global kill switch, missing credentials/account/relationship, persistence failure, non-positive amount, zero and exceeded per-transfer/monthly limits including reservations, another pending or unknown transfer, account mismatch, and changed/removed/disabled schedule; terminal failures do not retry and unknown retains its reservation |
| 9.7 | Add sanitized funding API, interval valuation selection, adjusted performance, and cursor pagination | 9.2 through 9.6 | API auth/privacy/pagination and Modified Dietz integration tests; persistence, API, and logs reject raw bank, relationship, credential, and Plaid material |
| 9.8 | Add funding history to Performance and complete-object controls to Settings | 9.7 | Typecheck, static behavior tests, responsive and accessibility browser checks |
| 9.9 | Add optional environment-scoped Broker secret references, runbooks, and deployment contract checks | 9.6 through 9.8 | CloudFormation validation, shell syntax, missing-secret safe default tests, and no Polymarket write resource |
| 9.10 | Rebase on current `develop`, run full local gates, open the feature PR, deploy development, and verify | 9.1 through 9.9 | CI run, migration success, dev stack/ECS/health, sanitized authenticated funding API/browser evidence, direct disabled and both limits `0.00`, and zero Broker POST log events for the release window |
| 9.11 | Promote `develop` to `main`, verify production, and attach release evidence | Successful 9.10 | Production CI and migration success; stack/ECS/health/TLS/browser/SES/ACM evidence; authenticated sanitized `GET /api/funding` shows `direct_transfers_enabled=false` and both limits `0.00`; CloudWatch funding adapter metrics/log query shows zero Broker POST events for the release window |
