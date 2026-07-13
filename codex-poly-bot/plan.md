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

## Parallelization Plan

| Track | Can Start After | Owns | Coordination Point |
|-------|-----------------|------|--------------------|
| Backend foundation | Phase 1 start | Domain, DB, migrations, config, audit, auth | Shared schema and Pydantic types |
| Adapter integrations | Domain and ports exist | Polymarket, Alpaca, AWS, LLM adapters, wallet CLI | Port contracts and credential model |
| Trading core | Foundation plus mocked ports | Ingestion, scoring, strategies, risk, execution, exits, comparison, scheduler | Order/position/reconciliation repositories |
| Dashboard/API | API schema contracts exist | FastAPI routers, Next.js auth, dashboard UI, API client | Field-level API contracts and auth token boundary |
| CI baseline | Phase 1 foundation exists | Local test workflow and non-deploy CI checks | Test commands and safe mock defaults |
| AWS deployment infrastructure | Phase 5 external integrations complete | CloudFormation, deploy workflow, ECR/ECS/RDS/S3/CloudWatch/SES | Environment names, secrets paths, migration safety |
| Docs/runbooks | Phase outputs stabilize | Local setup, deployment, live checklist, source references, operations | Must track current commands and deployment flow |

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
| Dashboard UI | Phase 4 |
| Frontend API client | Phase 4 |
| Infrastructure | Phase 6 |
| CI/CD | Phase 1 and Phase 6 |
| Local development | Phase 1 |
| Codex setup | Phase 1 |
| Documentation | Phase 7 |

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
