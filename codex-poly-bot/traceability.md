# Dashboard IA Redesign Traceability

## Scope

- GitHub issue: `#194`
- Design authority: `../TODO/design_handoff_dashboard_ia/`
- Requirements: `REQ-UI-016` through `REQ-UI-026`
- Release requirements: `REQ-DEP-002` through `REQ-DEP-006`
- Date: 2026-07-21

## Requirement Matrix

| Requirement | Implementation | Verification | Status |
|-------------|----------------|--------------|--------|
| REQ-UI-016 | `frontend/components/dashboard/dashboard-nav.tsx`; Activity and Performance route pages | `check-dashboard-redesign.mjs`; desktop, tablet, and mobile browser review | Pass |
| REQ-UI-017 | `frontend/lib/dashboard-overview-state.ts`; `frontend/components/dashboard/overview-dashboard.tsx` | `check-dashboard-overview-state.ts` tests matched completed runs and excludes in-progress runs | Pass |
| REQ-UI-018 | `overviewBlockers` and the Overview attention card | Overview state behavior tests; local browser attention-state review | Pass |
| REQ-UI-019 | Overview fact grid, recent result, and contextual link grid | Static route-owner checks; desktop and mobile browser review | Pass |
| REQ-UI-020 | `frontend/lib/dashboard-activity-view-model.ts`; `frontend/lib/dashboard-activity-detail.ts`; `activity-view.tsx` | `check-dashboard-redesign-behavior.ts` proves one-run metric mapping, clickable persisted-record drill-downs, model score fields, execution refusal reasons, unavailable handling, and realtime error clearing | Pass |
| REQ-UI-021 | `frontend/lib/dashboard-performance-view-model.ts`; `performance-view.tsx` | Behavior tests prove portfolio `filledTrades` ownership and unavailable win rate; realtime recovery reviewed locally | Pass |
| REQ-UI-022 | Common Settings section in `config-controls.tsx`; advanced disclosures | Dashboard control tests; Settings browser review | Pass |
| REQ-UI-023 | `help-about-view.tsx` five-step flow and FAQs | Static step-order checks; mobile Help browser review | Pass |
| REQ-UI-024 | Responsive header rules in `globals.css` | 390-pixel and 820-pixel browser review; 390-pixel page width equals scroll width | Pass |
| REQ-UI-025 | Explicit unavailable states, consolidated errors, and realtime recovery in Overview, Activity, and Performance | Overview and redesign behavior tests; backend restart recovery review | Pass |
| REQ-UI-026 | Exact-path recommendation planning, versioned writes, confirmation, local snapshot reconciliation, and undo | Static checks, Overview behavior tests, typecheck, and independent code review | Pass |
| REQ-DEP-002 | Existing `develop` deployment workflow | [Run 29836817504](https://github.com/yawetse/pmark-bot/actions/runs/29836817504) passed all jobs and deployed development | Pass |
| REQ-DEP-003 | Existing `main` production workflow | [Run 29837587362](https://github.com/yawetse/pmark-bot/actions/runs/29837587362) passed all jobs and deployed production | Pass |
| REQ-DEP-004 | CloudFormation and deployment script contract | Shell validation and 40 deployment tests passed locally; both CloudFormation jobs passed and reported current stacks | Pass |
| REQ-DEP-005 | Development ECS and HTTPS runtime | Development backend and frontend ECS services deployed; health returned HTTP 200; TLS and OAuth boundary passed | Pass |
| REQ-DEP-006 | Production ECS and HTTPS runtime | Production backend and frontend ECS services reached steady state; health returned HTTP 200; TLS and OAuth boundary passed | Pass |

## Local Gate Results

| Gate | Result |
|------|--------|
| Frontend typecheck | Pass |
| Dashboard redesign behavior and static tests | Pass |
| Auth boundary tests | Pass |
| Dashboard control tests | Pass |
| Dashboard operations tests | Pass |
| Next.js production build | Pass |
| Deployment shell syntax | Pass |
| Deployment CI specification tests | 40 passed |
| Full backend specification suite | 419 passed |
| CloudFormation validation | Pass in development and production GitHub Actions jobs; local AWS CLI session was expired |
| Responsive browser review | Pass at desktop, 820 by 700, and 390 by 844 |
| Live DOM accessibility sweep | Pass for headings, interactive names, duplicate IDs, keyboard focus outline, and overflow; Accesslint runtime unavailable |

## Release Audit

| Evidence | Development | Production |
|----------|-------------|------------|
| Pull request | [#195](https://github.com/yawetse/pmark-bot/pull/195) | [#196](https://github.com/yawetse/pmark-bot/pull/196) |
| GitHub Actions | [Run 29836817504](https://github.com/yawetse/pmark-bot/actions/runs/29836817504) passed | [Run 29837587362](https://github.com/yawetse/pmark-bot/actions/runs/29837587362) passed |
| CloudFormation | `codex-poly-bot-development` current | `codex-poly-bot-production` current |
| ECS | Backend and frontend deployment passed | Backend and frontend deployment passed and reached steady state |
| HTTPS health | `https://dev-codex-poly-bot.repetere.net/health` returned HTTP 200 and `{"status":"ok"}` | `https://codex-poly-bot.repetere.net/health` returned HTTP 200 and `{"status":"ok"}` |
| Browser | Dashboard rendered the GitHub OAuth boundary | Dashboard rendered the GitHub OAuth boundary |
| Certificate | Expected ACM ARN; Amazon certificate for `*.repetere.net` valid through 2026-10-27 | Expected ACM ARN; Amazon certificate for `*.repetere.net` valid through 2026-10-27 |
| SES | Deployment input used `asyncdoc.net` | Deployment input used `asyncdoc.net` |

The verification browser did not have an authenticated GitHub session. Authenticated dashboard routes were verified locally against the release build. The deployed checks verified health, TLS, page rendering, and the OAuth boundary. All mapped UI and deployment requirements pass.

---

# Recurring Funding Traceability

## Scope

- Requirements: `REQ-FND-001` through `REQ-FND-020`
- HLD decisions: `DD-048` through `DD-056`
- LLD authority: `design-lld.md` section 28
- Plan: Phase 9, steps 9.1 through 9.11
- Tasks: `TASK-041` through `TASK-049`
- Date: 2026-07-31

## Requirement Matrix

| Requirement | Design | Task | Test IDs | Implementation Evidence | Status |
|-------------|--------|------|----------|------------------------|--------|
| REQ-FND-001 | DD-048; LLD 28.3, 28.6 | TASK-043, TASK-049 | TST-REQ-FND-001-01, TST-REQ-FND-001-02, TST-REQ-FND-001-03, TST-REQ-FND-001-04, TST-REQ-FND-001-05 | `venue_portfolio_service.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-002 | DD-048, DD-054; LLD 28.1, 28.2, 28.3, 28.5 | TASK-042, TASK-043, TASK-048, TASK-049 | TST-REQ-FND-002-01, TST-REQ-FND-002-02, TST-REQ-FND-002-03 | `domain/funding.py`; `funding_service.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-003 | DD-048; LLD 28.2, 28.4 | TASK-042, TASK-043, TASK-049 | TST-REQ-FND-003-01, TST-REQ-FND-003-02, TST-REQ-FND-003-03 | `funding_service.py`; `schema.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-004 | DD-048; LLD 28.2, 28.3, 28.5 | TASK-042, TASK-043, TASK-046, TASK-049 | TST-REQ-FND-004-01, TST-REQ-FND-004-02, TST-REQ-FND-004-03, TST-REQ-FND-004-04 | `venue_portfolio_service.py`; `funding_service.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-005 | DD-049, DD-051, DD-056; LLD 28.1, 28.4, 28.6 | TASK-041, TASK-044, TASK-047, TASK-049 | TST-REQ-FND-005-01, TST-REQ-FND-005-02, TST-REQ-FND-005-03, TST-REQ-FND-005-04 | `domain/funding.py`; `funding_service.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-006 | DD-049, DD-055, DD-056; LLD 28.1, 28.4, 28.6 | TASK-041, TASK-044, TASK-045, TASK-047, TASK-049 | TST-REQ-FND-006-01, TST-REQ-FND-006-02, TST-REQ-FND-006-03, TST-REQ-FND-006-04 | `funding_service.py`; `direct_funding_service.py`; funding tests | Implemented; locally verified |
| REQ-FND-007 | DD-049, DD-050, DD-056; LLD 28.1, 28.2, 28.4, 28.6 | TASK-041, TASK-042, TASK-044, TASK-049 | TST-REQ-FND-007-01, TST-REQ-FND-007-02, TST-REQ-FND-007-03, TST-REQ-FND-007-04, TST-REQ-FND-007-05 | `main.py`; `repositories.py`; `funding_service.py`; funding tests | Implemented; locally verified |
| REQ-FND-008 | DD-052; LLD 28.2, 28.4 | TASK-042, TASK-043, TASK-044, TASK-049 | TST-REQ-FND-008-01, TST-REQ-FND-008-02, TST-REQ-FND-008-03, TST-REQ-FND-008-04 | `funding_service.py`; `schema.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-009 | DD-052; LLD 28.2, 28.4 | TASK-042, TASK-044, TASK-049 | TST-REQ-FND-009-01, TST-REQ-FND-009-02, TST-REQ-FND-009-03, TST-REQ-FND-009-04 | `funding_service.py`; `schema.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-010 | DD-048; LLD 28.5 | TASK-046, TASK-047, TASK-049 | TST-REQ-FND-010-01, TST-REQ-FND-010-02, TST-REQ-FND-010-03, TST-REQ-FND-010-04, TST-REQ-FND-010-05, TST-REQ-FND-010-06, TST-REQ-FND-010-08 | `api/dashboard.py`; `performance-view.tsx`; frontend checker | Implemented; locally verified |
| REQ-FND-011 | DD-053; LLD 28.4, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-011-01, TST-REQ-FND-011-02 | `funding_service.py`; `performance-view.tsx`; funding tests | Implemented; locally verified |
| REQ-FND-012 | DD-053; LLD 28.4, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-012-01, TST-REQ-FND-012-02, TST-REQ-FND-012-03 | `funding_service.py`; `test_recurring_funding.py` | Implemented; locally verified |
| REQ-FND-013 | DD-054; LLD 28.3, 28.7 | TASK-045, TASK-048, TASK-049 | TST-REQ-FND-013-01, TST-REQ-FND-013-02, TST-REQ-FND-013-03, TST-REQ-FND-013-04, TST-REQ-FND-013-05 | `alpaca_funding.py`; CloudFormation; direct and deployment tests | Implemented; locally verified |
| REQ-FND-014 | DD-054, DD-055; LLD 28.1, 28.2, 28.4 | TASK-042, TASK-045, TASK-048, TASK-049 | TST-REQ-FND-014-01, TST-REQ-FND-014-02, TST-REQ-FND-014-03, TST-REQ-FND-014-04, TST-REQ-FND-014-05, TST-REQ-FND-014-06, TST-REQ-FND-014-07, TST-REQ-FND-014-08 | defaults; direct service; infrastructure tests; [development gate](https://github.com/yawetse/pmark-bot/actions/runs/30680452086); [production gate](https://github.com/yawetse/pmark-bot/actions/runs/30680683629) | Implemented; development and production verified |
| REQ-FND-015 | DD-050, DD-055; LLD 28.2, 28.4 | TASK-042, TASK-045, TASK-049 | TST-REQ-FND-015-01, TST-REQ-FND-015-02, TST-REQ-FND-015-03, TST-REQ-FND-015-04 | `funding_service.py`; `schema.py`; `test_direct_funding.py` | Implemented; locally verified |
| REQ-FND-016 | DD-050, DD-055; LLD 28.2, 28.3, 28.4 | TASK-042, TASK-044, TASK-045, TASK-049 | TST-REQ-FND-016-01, TST-REQ-FND-016-02, TST-REQ-FND-016-03, TST-REQ-FND-016-04 | `direct_funding_service.py`; `alpaca_funding.py`; direct tests | Implemented; locally verified |
| REQ-FND-017 | DD-055; LLD 28.2, 28.4 | TASK-042, TASK-044, TASK-045, TASK-049 | TST-REQ-FND-017-01, TST-REQ-FND-017-02 | `direct_funding_service.py`; `funding_service.py`; direct tests | Implemented; locally verified |
| REQ-FND-018 | DD-055; LLD 28.1, 28.4, 28.6 | TASK-044, TASK-045, TASK-048, TASK-049 | TST-REQ-FND-018-01, TST-REQ-FND-018-02 | control/config services; funding services; funding tests | Implemented; locally verified |
| REQ-FND-019 | DD-049; LLD 28.1, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-019-01, TST-REQ-FND-019-02, TST-REQ-FND-019-03, TST-REQ-FND-019-04, TST-REQ-FND-019-05 | config service/API; funding controls; runbook; tests | Implemented; locally verified |
| REQ-FND-020 | DD-048, DD-054; LLD 28.1, 28.3, 28.7 | TASK-041, TASK-043, TASK-045, TASK-047, TASK-048, TASK-049 | TST-REQ-FND-020-01, TST-REQ-FND-020-02, TST-REQ-FND-020-03, TST-REQ-FND-020-04 | domain validation; read adapter; CloudFormation scan; UI checker | Implemented; locally verified |

## Release Evidence Checklist

| Evidence | Development | Production |
|----------|-------------|------------|
| Tracking issue and pull requests | [Issue #236](https://github.com/yawetse/pmark-bot/issues/236); implementation [#237](https://github.com/yawetse/pmark-bot/pull/237); release gates [#238](https://github.com/yawetse/pmark-bot/pull/238), [#239](https://github.com/yawetse/pmark-bot/pull/239), [#241](https://github.com/yawetse/pmark-bot/pull/241), [#242](https://github.com/yawetse/pmark-bot/pull/242) | Promotion [#240](https://github.com/yawetse/pmark-bot/pull/240) merged to `main` |
| GitHub Actions run URL and final status | [30680452086](https://github.com/yawetse/pmark-bot/actions/runs/30680452086): success | [30680683629](https://github.com/yawetse/pmark-bot/actions/runs/30680683629): success |
| Database migration | Migration safety and backend startup passed | Migration safety and backend startup passed |
| CloudFormation stack status | `codex-poly-bot-development`: `UPDATE_COMPLETE`; certificate output matched | `codex-poly-bot-production`: `UPDATE_COMPLETE`; certificate output matched |
| ECS backend and frontend health | Both services stabilized | Both services stabilized |
| HTTPS `/health` | `https://dev-codex-poly-bot.repetere.net/health`: `ok` | `https://codex-poly-bot.repetere.net/health`: `ok`; independent curl also passed |
| Authenticated sanitized `/api/funding` | Release gate passed sanitized readback using a signed runtime identity | Release gate passed sanitized readback using a signed runtime identity |
| Dashboard browser evidence | Landing page rendered; `/dashboard` redirected to `/login`; no console warning or error | Landing page rendered; `/dashboard` redirected to `/login`; no console warning or error |
| Direct transfers disabled and both limits `0.00` | Verified by deployed readback | Verified by deployed readback |
| CloudWatch Broker POST events in release window | `0` | `0` |
| SES identity and ACM certificate | SES verified; stack certificate binding matched; live TLS valid | SES verified; stack certificate binding matched; live TLS valid |

No real bank transfer is used for release verification.

---

# Alpaca Short Selling Traceability

## Scope

- GitHub issue: `#245`
- Requirements: `REQ-ALP-019` through `REQ-ALP-026`
- HLD decisions: `DD-034`, `DD-047`, `DD-057`
- LLD authority: sections 1, 2, 3, 8, 15, 16, 17, 20, 23, and 24
- Plan: Phase 10, steps 10.1 through 10.6
- Task: `TASK-050`
- Date: 2026-08-01

## Requirement Matrix

| Requirement | Design | Task | Test IDs | Implementation Evidence | Status |
|-------------|--------|------|----------|------------------------|--------|
| REQ-ALP-019 | DD-034, DD-047; LLD 3, 15 | TASK-050 | TST-REQ-ALP-019-01, TST-REQ-ALP-019-02 | `config_service.py`; `config-controls.tsx`; `test_alpaca_short_selling.py` | Implemented; locally verified |
| REQ-ALP-020 | DD-047; LLD 8, 15 | TASK-050 | TST-REQ-ALP-020-01, TST-REQ-ALP-020-02 | `venues/alpaca.py`; `test_alpaca_short_selling.py` | Implemented; locally verified |
| REQ-ALP-021 | DD-047; LLD 8, 15 | TASK-050 | TST-REQ-ALP-021-01, TST-REQ-ALP-021-02 | `venues/alpaca.py`; `test_alpaca_short_selling.py` | Implemented; locally verified |
| REQ-ALP-022 | DD-047; LLD 8, 15, 17 | TASK-050 | TST-REQ-ALP-022-01, TST-REQ-ALP-022-02 | `execution_service.py`; `lifecycle_service.py`; `venues/alpaca.py`; short-selling tests | Implemented; locally verified |
| REQ-ALP-023 | DD-034, DD-047; LLD 1, 2, 8, 15, 17, 20, 23, 24 | TASK-050 | TST-REQ-ALP-023-01, TST-REQ-ALP-023-02 | lifecycle, stock-history, portfolio, and dashboard position changes; lifecycle and history tests | Implemented; locally verified |
| REQ-ALP-024 | DD-047; LLD 8, 15 | TASK-050 | TST-REQ-ALP-024-01, TST-REQ-ALP-024-02 | `lifecycle_service.py`; lifecycle short-entry tests | Implemented; locally verified |
| REQ-ALP-025 | DD-057; LLD 8, 15, 17 | TASK-050 | TST-REQ-ALP-025-01, TST-REQ-ALP-025-02, TST-REQ-ALP-025-03 | exact quantity cover in adapter and lifecycle; short-selling and lifecycle tests | Implemented; locally verified |
| REQ-ALP-026 | DD-057; LLD 1, 2, 8, 16, 17, 20, 23, 24 | TASK-050 | TST-REQ-ALP-026-01, TST-REQ-ALP-026-02 | account registration lookup, provider-routed exits, account-match gate, sanitized audit payload; lifecycle tests | Implemented; locally verified |

## Release Evidence Checklist

Production release evidence is tracked on [GitHub issue #245](https://github.com/yawetse/pmark-bot/issues/245). No live short order is part of the deployment smoke test.

| Evidence | Development | Production |
|----------|-------------|------------|
| Pull request and GitHub Actions | Implementation [#246](https://github.com/yawetse/pmark-bot/pull/246); CI [30716105017](https://github.com/yawetse/pmark-bot/actions/runs/30716105017); release guardrail [#248](https://github.com/yawetse/pmark-bot/pull/248) | Promotion [#247](https://github.com/yawetse/pmark-bot/pull/247); final guardrail run is recorded on issue #245 |
| CloudFormation and ECS | [Development deployment 30716198265](https://github.com/yawetse/pmark-bot/actions/runs/30716198265) passed and both services stabilized | [Production deployment 30716537599](https://github.com/yawetse/pmark-bot/actions/runs/30716537599) passed on attempt 2 and both services stabilized |
| HTTPS health and OAuth boundary | `/health` returned HTTP 200 with `{"status":"ok"}`; GitHub OAuth start returned HTTP 307 | `/health` returned HTTP 200 with `{"status":"ok"}`; GitHub OAuth start returned HTTP 307 |
| Authenticated short-setting readback | Release guardrail #248 fails unless `alpaca.allow_shorting` is exactly `false` | Release guardrail #248 fails unless `alpaca.allow_shorting` is exactly `false` |
| Read-only Alpaca account and asset eligibility | Missing or rejected broker credentials fail closed before order POST; adapter eligibility checks are covered by the Alpaca integration suites | Missing or rejected broker credentials fail closed before order POST; no eligibility exception is used for production |
| Order safety | No paper or live short order was placed | No live short order was placed; production release evidence reported zero broker POST events |

---

# Kalshi Venue Traceability

## Scope

- GitHub issue: `#252`
- Requirements: `REQ-KAL-001` through `REQ-KAL-014`
- HLD decisions: `DD-058` through `DD-066`
- LLD authority: section 29
- Plan: Phase 11, steps 11.1 through 11.7
- Tasks: `TASK-051` through `TASK-055`
- Date: 2026-08-02

## Requirement Matrix

| Requirement | Design | Task | Test IDs | Implementation Evidence | Status |
|-------------|--------|------|----------|-------------------------|--------|
| REQ-KAL-001 | DD-059; LLD 29.1, 29.3, 29.4, 29.6 | TASK-051, TASK-052 | TST-REQ-KAL-001-01, TST-REQ-KAL-001-02 | domain models; config service; scanner service; dashboard controls; specification tests | Implemented; locally verified |
| REQ-KAL-002 | DD-059, DD-060; LLD 29.3 | TASK-052 | TST-REQ-KAL-002-01, TST-REQ-KAL-002-02, TST-REQ-KAL-002-03 | `market_data_provider.py`; `scanner_service.py`; specification tests | Implemented; locally verified |
| REQ-KAL-003 | DD-058, DD-060; LLD 29.2, 29.3 | TASK-051, TASK-052 | TST-REQ-KAL-003-01, TST-REQ-KAL-003-02, TST-REQ-KAL-003-03 | bounded reads in `kalshi.py`; freshness gates; specification tests | Implemented; locally verified |
| REQ-KAL-004 | DD-058, DD-061; LLD 29.1, 29.2, 29.7 | TASK-051, TASK-055 | TST-REQ-KAL-004-01, TST-REQ-KAL-004-02, TST-REQ-KAL-004-03, TST-REQ-KAL-004-04 | RSA signer and host factory in `kalshi.py`; environment examples; sanitized-auth tests | Implemented; locally verified |
| REQ-KAL-005 | DD-060, DD-062; LLD 29.2, 29.4 | TASK-053 | TST-REQ-KAL-005-01, TST-REQ-KAL-005-02, TST-REQ-KAL-005-03 | V2 order adapter; execution service; lifecycle translation; specification tests | Implemented; locally verified |
| REQ-KAL-006 | DD-058, DD-062; LLD 29.2, 29.4 | TASK-053 | TST-REQ-KAL-006-01, TST-REQ-KAL-006-02, TST-REQ-KAL-006-03 | durable lifecycle intents; client-ID reconciliation; specification tests | Implemented; locally verified |
| REQ-KAL-007 | DD-061, DD-062; LLD 29.1 through 29.4 | TASK-051, TASK-052, TASK-053 | TST-REQ-KAL-007-01, TST-REQ-KAL-007-02, TST-REQ-KAL-007-03 | runtime status stage-boundary rereads; scanner kill-switch filter; risk engine; execution and lifecycle services; specification tests | Implemented; locally verified |
| REQ-KAL-008 | DD-060, DD-063; LLD 29.2, 29.5 | TASK-054 | TST-REQ-KAL-008-01, TST-REQ-KAL-008-02 | authenticated account reads and normalization in `venue_portfolio_service.py`; specification tests | Implemented; locally verified |
| REQ-KAL-009 | DD-063; LLD 29.1, 29.5, 29.6 | TASK-054 | TST-REQ-KAL-009-01, TST-REQ-KAL-009-02 | dashboard config, overview, portfolio, and API authorization tests | Implemented; locally verified |
| REQ-KAL-010 | DD-061, DD-064; LLD 29.7, 29.8 | TASK-055 | TST-REQ-KAL-010-01, TST-REQ-KAL-010-02, TST-REQ-KAL-010-03 | CloudFormation; CI workflows; deploy and sync scripts; deployment tests | Implemented; local gates passed; release pending |
| REQ-KAL-011 | DD-062, DD-066; LLD 29.2, 29.4 | TASK-053 | TST-REQ-KAL-011-01, TST-REQ-KAL-011-02 | reconcile-before-cancel adapter and lifecycle path; specification tests | Implemented; locally verified |
| REQ-KAL-012 | DD-065; LLD 29.1, 29.4, 29.5 | TASK-051, TASK-053 | TST-REQ-KAL-012-01, TST-REQ-KAL-012-02 | provider credential routing; scope and account-identity gates; advisory locking; specification tests | Implemented; locally verified |
| REQ-KAL-013 | DD-060; LLD 29.5 | TASK-054 | TST-REQ-KAL-013-01, TST-REQ-KAL-013-02 | fixed-point portfolio normalization and outcome-side UI; specification tests | Implemented; locally verified |
| REQ-KAL-014 | DD-063; LLD 29.2, 29.5 | TASK-054 | TST-REQ-KAL-014-01, TST-REQ-KAL-014-02 | historical cutoff, fills, orders, checkpoints, and deduplication; specification tests | Implemented; locally verified |

## Release Evidence Checklist

| Evidence | Development | Production |
|----------|-------------|------------|
| Tracking issue and pull requests | [Issue #252](https://github.com/yawetse/pmark-bot/issues/252); pending implementation PR | Pending promotion PR |
| GitHub Actions | Pending | Pending |
| Commit, workflow URL, and conclusion | Pending | Pending |
| CloudFormation stack ID/status, ECS task definition/image digest | Pending | Pending |
| HTTPS health and OAuth boundary | Pending | Pending |
| Public exchange status and market summary GET | Pending | Pending |
| Credential mode: authenticated when all six secrets exist, or explicitly not configured and blocked when none exist | Pending | Pending |
| Authenticated Kalshi batch-order-book result, including requested and returned ticker counts, when configured | Pending | Pending |
| OpenAI Kalshi balance normalized from integer cents to USD, when configured | Pending | Pending |
| Claude Kalshi balance normalized from integer cents to USD, when configured | Pending | Pending |
| Sanitized host, effective secret refs, and deployed runtime credential readiness | Pending | Pending |
| Runtime missing-secret live refusal | Pending | Pending |
| Rollback command or workflow, result, and recovered health | Pending | Pending |
| Dashboard browser evidence | Pending | Pending |
| SES identity and ACM certificate | Pending | Pending |
| Time-bounded audit or CloudWatch query for Kalshi POST/DELETE | Required: zero, with query and UTC window | Required: zero, with query and UTC window |
| Kalshi order and fill counts across release window | Required unchanged when authenticated; otherwise not applicable | Required unchanged when authenticated; otherwise not applicable |
