# claude-poly-bot — Implementation Plan

**Methodology:** Vertical-slice builds with discrete demoable milestones.
**Sequencing principles:**
1. **Risk-first** — de-risk venue integration and risk-halt logic early (per Phase 3C elicitation).
2. **Always demoable** — every milestone produces a runnable artifact.
3. **DRY before LIVE** — every code path is exercised in DRY_RUN mode before any real money flows.
4. **One LLM before two** — single-bot end-to-end before adding the second bot.
5. **One venue before two** — Polymarket-only vertical slice before Alpaca.

**Status legend:** ◯ pending · ▣ in-progress · ▢ blocked · ✔ done.

---

## Execution Order

| # | Milestone | Components | Dependencies | Demo / "Done" Definition |
|---|---|---|---|---|
| M0 | **Foundation** | Repo skeleton, `pyproject.toml`, devcontainer, alembic init, base Pydantic models, lint/type/test scaffolding, `pr.yml` GitHub Action, docker-compose with Postgres | none | `git clone && docker compose up && pytest` runs the empty test suite green. CI passes on PR. |
| M1 | **Polymarket Scanner skeleton** | `domain/{models, scoring, clock, protocols}`, `storage/{db, orm, repos/queue, repos/scans}`, `venues/polymarket/venue.py` (read-only ops), `bot/loops/scanner.py`, `cli` doctor command | M0 | `claude-poly-bot scanner` runs once, fetches Polymarket markets, scores them, writes candidates + scan-runs to local Postgres. Operator inspects via `psql`. |
| M2 | **Claude brain in DRY** | `domain/{consensus, thesis}`, `llm/{prompts, anthropic_impl, mocks}`, `bot/loops/thesis.py`, `storage/repos/{decisions, theses, target_wallets}`, `data_refresh` minimal (synthetic target wallets okay for now) | M1 | Run scanner + Claude thesis loops against live Polymarket; theses are produced and persisted; `psql` shows `decisions` and `theses` rows. Cost capped via env. |
| M3 | **Risk + Executor (simulated)** | `domain/{kelly, risk}`, `storage/repos/{positions, orders, trades, risk_halts, bankroll}`, `bot/loops/executor.py`, `wallet/evm.py` (loaded but no real signing yet) | M2 | Theses → simulated orders/positions. Risk halt verified by forcing a daily loss in tests. Kelly math property-tested. No real money. |
| M4 | **Real Polymarket execution path** | `wallet/evm.py` real signing, `venues/polymarket/place_order` real flow (still gated by `LIVE_ENABLED=false`), reconciliation logic | M3 | With `LIVE_ENABLED=true` set as a one-off manual flag in dev: place a real \$1 order on Polymarket; verify fill; reconcile after restart. Then revert to DRY. |
| M5 | **Polymarket exit engine** | `bot/loops/exit.py`, `venues/polymarket/stream.py`, all 4 exit triggers (TARGET_HIT, VOLUME_EXIT, STALE_THESIS, MARKET_RESOLVED) | M4 | A scripted DRY position is opened; exit triggers fire correctly under simulated price/volume changes. WebSocket reconnect verified. |
| M6 | **OpenAI bot in parallel** | `llm/openai_impl.py`, scanner publishes to shared queue, both bots independently consume per DD-017 candidate_claims | M5 | Two bot processes run concurrently in docker-compose; both produce theses for the same scanned markets; comparison decision-correlation IDs match per DD-019. |
| M7 | **Alpaca venue** | `venues/alpaca/{venue, stream, calendar}`, `domain/scoring` Alpaca branch, `bot/loops/exit` STOP_LOSS + HORIZON_EXIT + EOD_FLATTEN, ALPC `setup-alpaca` CLI | M6 | Both bots scan Alpaca and Polymarket; theses generated for both venues; bracket stop submitted on Alpaca paper account; EOD flatten verified by FakeClock test. |
| M8 | **Dashboard MVP (read-only)** | `api/{main, deps, routes/{bots, markets, health, auth}, websocket, middleware}`, `auth/{oauth, session}`, frontend `app/{layout, page, bots/[name], decisions, markets, health}`, `lib/`, OAuth setup CLI | M7 | Operator logs in via GitHub OAuth, sees 4 P&L streams + decision logs + market queue + health. Read-only — no config editing yet. |
| M9 | **Dashboard config editor** | `config/{schema, service, defaults}`, `api/routes/config.py`, frontend `app/config/page.tsx`, `LIVE_ENABLED` toggle UX with checksum confirmation, audit log | M8 | Operator changes a Tier 1 field via dashboard; change visible in audit; bot picks up the change on next loop iteration. |
| M10 | **AWS deploy + CI/CD** | `infra/cloudformation/*`, `infra/params/{dev,prod}.json`, `docker/Dockerfile.{bot,api,ui}`, `.github/workflows/{deploy-dev, deploy-prod, rollback}.yml`, OIDC trust policy | M9 | Push to `develop` → dev environment auto-deploys; smoke tests pass; dashboard reachable at dev URL. Same for `main` → prod. |
| M11 | **Observability + SES alerts** | `observability/{logging, metrics, alerts}` real implementations, daily summary scheduled task, all 11 alert types from REQ-OBS-004 wired | M10 | Force a fake risk halt in dev → operator gets SES email. Daily summary email arrives at 08:00 UTC. CloudWatch dashboard shows metrics. |
| M12 | **Production hardening** | Hourly reconciliation, full integration test coverage, production runbook, final risk review, cost budget verification | M11 | All P0 REQs traced to passing tests. Coverage verified per Phase 7. Runbook documents incident response. |

---

## Per-Milestone "Done" Criteria (test-level)

| # | Tests Required at "Done" |
|---|---|
| M0 | Empty `pytest` runs; lint+typecheck pass; docker-compose up succeeds. |
| M1 | Unit tests for `domain/scoring`, `domain/clock`. Integration test: scanner publishes to queue against testcontainers Postgres. |
| M2 | Unit tests for `domain/consensus`, `domain/thesis`. Integration test with `FakeStrategist`: 4 BUY checks → thesis produced with correct confidence. |
| M3 | Property tests for `domain/kelly`, `domain/risk`. Integration: forced 50% drawdown halt prevents new entries; existing positions still get exit-evaluated. |
| M4 | Integration test using `FakeVenue`: `place_order` → reconcile after simulated container restart finds the order. Real Polymarket integration test gated by `INTEGRATION_LIVE=1` env flag. |
| M5 | Integration tests for each exit trigger using `FakeVenue` + `FakeClock` — TARGET_HIT, VOLUME_EXIT, STALE_THESIS each independently fires. |
| M6 | E2E test: shared scanner publishes 1 candidate; both bots independently produce theses; both decision rows have matching `scan_correlation_id`. |
| M7 | All M5 tests pass for Alpaca venue. STOP_LOSS, HORIZON_EXIT, EOD_FLATTEN each fire correctly with `FakeClock`. PDT predicate property-tested. |
| M8 | API integration tests for every route. WebSocket auth tests (cookie + Origin + allowlist). Frontend Playwright E2E: log in, navigate, see chart with mocked WS data. |
| M9 | Config PATCH integration test: change persists, audit row written, alert fires for live-toggle. Validation rejects invalid values. |
| M10 | CI: `pr.yml` green; `deploy-dev.yml` succeeds against a real dev AWS account (manual one-time setup); smoke tests pass post-deploy. |
| M11 | SES alert integration tests using `moto`. Daily-summary script test with `FakeClock`. CloudWatch metric emission test (assert EMF JSON shape). |
| M12 | Phase 7 traceability matrix: 100% of P0 REQs → tests → annotated code. |

---

## Dependency Graph

Plain-text:

```
M0 (Foundation)
  ↓
M1 (Polymarket Scanner)
  ↓
M2 (Claude Brain DRY) ──────┐
  ↓                         │
M3 (Risk + Executor sim)    │
  ↓                         │
M4 (Real Polymarket exec)   │
  ↓                         │
M5 (Polymarket Exit)        │
  ↓                         │
M6 (OpenAI Bot)  ←──────────┘  (uses LLM abstraction from M2)
  ↓
M7 (Alpaca Venue)
  ↓
M8 (Dashboard MVP)
  ↓
M9 (Config Editor)
  ↓
M10 (AWS Deploy + CI/CD)
  ↓
M11 (Observability + Alerts)
  ↓
M12 (Production Hardening)
```

**Critical path** (longest chain): M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9 → M10 → M11 → M12 (linear).

**Parallel opportunities** (single dev — context switches, not concurrent execution):
- During M5 (exit engine), the API skeleton (M8 prep) can be drafted with stubs.
- During M7 (Alpaca), frontend pages (M8) can be scaffolded against mocked API responses.
- CloudFormation drafts (M10) can be drafted alongside any milestone after M3.

---

## Risk Register (Implementation-Phase Specific)

This complements the HLD risk register (R1–R20). Risks here are about *implementation execution*, not architectural risks.

| ID | Risk | Impact | Likelihood | Mitigation | Milestone |
|---|---|---|---|---|---|
| IR1 | Polymarket SDK quirks (signing edge cases, undocumented behavior) | H | M | Real \$1 test on dev wallet at M4; don't proceed until verified end-to-end | M4 |
| IR2 | Alpaca SIP/IEX feed access tier mismatch | M | M | Pick IEX as the fallback default; SIP only if subscription supports | M7 |
| IR3 | OpenAI structured-output schema dialect issues | M | M | Test at M6 with a small prompt before integrating fully | M6 |
| IR4 | Anthropic prompt-cache behavior changes | L | M | Pin model ID; monitor cache-hit metric; fallback path is non-cached calls | M2 |
| IR5 | Risk halt edge case — drawdown computed wrong at UTC boundary | H | M | Property tests for `domain/risk` covering boundaries; integration test with `FakeClock` advancing across midnight | M3 |
| IR6 | Reconciliation logic incorrect on first deployment with real money | H | L | Test with `FakeVenue`; manual test sequence at M4: place real order, kill container mid-flight, restart, verify reconcile | M4, M12 |
| IR7 | CloudFormation stack interdependencies cause deploy failures | M | H | Use nested stacks per HLD §8.1; rehearse deploys in dev before prod; rollback plan | M10 |
| IR8 | OAuth callback URL mismatch on first deploy | L | H | `setup-oauth` CLI prints exact URL; manual GitHub configuration step documented | M10 |
| IR9 | Frontend WS reconnect storms in production | L | L | Exponential backoff + max-attempts cap baked into `lib/ws.ts` | M8 |
| IR10 | Cost estimate exceeds expectations once running | M | M | LLM spend cap prevents runaway; AWS budget alarm for $200/mo prod | M10 |
| IR11 | RDS migration on prod fails mid-deploy | H | L | Reversible migrations only; CI runs migration in a copy-of-prod sandbox before deploy-prod; rollback redeploys old image (which uses old schema) | M10 |
| IR12 | Wallet-key generation accidentally overwrites a funded wallet | Critical | L | `setup-wallets` requires typing `yes` (per Batch 6 finding); checks for existing balance and aborts if non-zero | M4 |

---

## Effort Tier (rough — solo dev, evenings/weekends)

Not committing to dates, but rough effort in tiered weeks of focused work:

| # | Tier | Notes |
|---|---|---|
| M0 | 1 week | Mostly mechanical setup |
| M1 | 1 week | Polymarket SDK familiarization included |
| M2 | 1.5 weeks | Prompt design + testing iteration |
| M3 | 1 week | Pure logic, well-defined |
| M4 | 1 week | Real-money test is sensitive |
| M5 | 1 week | WebSocket reconnect testing |
| M6 | 1 week | Mostly parallel — small delta from M2 |
| M7 | 1.5 weeks | Alpaca integration is largest single new external system |
| M8 | 2 weeks | Frontend + backend + auth |
| M9 | 1 week | Form work |
| M10 | 2 weeks | CFN debugging + OIDC setup |
| M11 | 1 week | Wiring + alert verification |
| M12 | 1 week | Polish + reconciliation + runbook |

**Total: ~16 weeks** of focused effort. Calendar time depends on availability.

---

## Self-Review Findings (Plan)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | MED | M4 "real-money test" requires Polymarket account funded with USDC + MATIC for gas before milestone is gated complete | Document as a prerequisite; operator funds the dev wallet before starting M4. CLI prints addresses at M3. |
| 2 | MED | Dashboard depends on auth + DB + LLM data; M8 timeline includes integrating with OAuth which has external dependencies (GitHub OAuth app) | M8 includes manual step: register OAuth app first; documented in Phase 8 setup notes. |
| 3 | MED | M10 (deploy) must precede M11 (observability) but M11's alerts are valuable from M2 onward — operator may want SES set up earlier for local dev visibility | Local dev uses MailHog (per Batch 8 docker-compose); real SES not needed until M10. Acceptable. |
| 4 | LOW | M6 "OpenAI in parallel" assumes both bots in same docker-compose locally. Resource use ~doubles | Acceptable for local dev; prod is 2 separate Fargate services so no overlap |
| 5 | LOW | Effort estimates are rough — could compress with paid focus or expand significantly | Acknowledged; treat as relative ordering, not absolute deadlines |

---

## Open Items (Plan)

- Decide on first-real-money budget for M4 (e.g., \$5? \$20?). Lean low — \$5–10 USDC for the smoke test.
- Identify which Polymarket markets to use for M4 real-test — pick a high-resolution-time low-stakes market.
- Confirm whether dashboard on dev environment should be password-protected (HTTP basic auth in front of OAuth) before M10 to prevent any pre-launch leak.
