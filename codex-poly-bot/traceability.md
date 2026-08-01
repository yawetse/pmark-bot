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

| Requirement | Design | Task | Test IDs | Planned Implementation | Status |
|-------------|--------|------|----------|------------------------|--------|
| REQ-FND-001 | DD-048; LLD 28.3, 28.6 | TASK-043, TASK-049 | TST-REQ-FND-001-01, TST-REQ-FND-001-02, TST-REQ-FND-001-03, TST-REQ-FND-001-04, TST-REQ-FND-001-05 | Venue portfolio funding activity reads and runtime refresh | Planned |
| REQ-FND-002 | DD-048, DD-054; LLD 28.1, 28.2, 28.3, 28.5 | TASK-042, TASK-043, TASK-048, TASK-049 | TST-REQ-FND-002-01, TST-REQ-FND-002-02, TST-REQ-FND-002-03 | Normalized cash-flow allowlist, safe logs, sanitized API schemas | Planned |
| REQ-FND-003 | DD-048; LLD 28.2, 28.4 | TASK-042, TASK-043, TASK-049 | TST-REQ-FND-003-01, TST-REQ-FND-003-02, TST-REQ-FND-003-03 | Cash-flow upsert uniqueness, provider merge, stale update guard | Planned |
| REQ-FND-004 | DD-048; LLD 28.2, 28.3, 28.5 | TASK-042, TASK-043, TASK-046, TASK-049 | TST-REQ-FND-004-01, TST-REQ-FND-004-02, TST-REQ-FND-004-03, TST-REQ-FND-004-04 | Indefinite tables, bounded sync backfill, cursor history API | Planned |
| REQ-FND-005 | DD-049, DD-051, DD-056; LLD 28.1, 28.4, 28.6 | TASK-041, TASK-044, TASK-047, TASK-049 | TST-REQ-FND-005-01, TST-REQ-FND-005-02, TST-REQ-FND-005-03, TST-REQ-FND-005-04 | Schedule validation, business-day calendar, materialization | Planned |
| REQ-FND-006 | DD-049, DD-055, DD-056; LLD 28.1, 28.4, 28.6 | TASK-041, TASK-044, TASK-045, TASK-047, TASK-049 | TST-REQ-FND-006-01, TST-REQ-FND-006-02, TST-REQ-FND-006-03, TST-REQ-FND-006-04 | Low-balance episodes, gap and capped submission calculation | Planned |
| REQ-FND-007 | DD-049, DD-050, DD-056; LLD 28.1, 28.2, 28.4, 28.6 | TASK-041, TASK-042, TASK-044, TASK-049 | TST-REQ-FND-007-01, TST-REQ-FND-007-02, TST-REQ-FND-007-03, TST-REQ-FND-007-04, TST-REQ-FND-007-05 | Deterministic occurrence keys, unique insert, run lock | Planned |
| REQ-FND-008 | DD-052; LLD 28.2, 28.4 | TASK-042, TASK-043, TASK-044, TASK-049 | TST-REQ-FND-008-01, TST-REQ-FND-008-02, TST-REQ-FND-008-03, TST-REQ-FND-008-04 | One-to-one amount/direction/window match and coverage deadline | Planned |
| REQ-FND-009 | DD-052; LLD 28.2, 28.4 | TASK-042, TASK-044, TASK-049 | TST-REQ-FND-009-01, TST-REQ-FND-009-02, TST-REQ-FND-009-03, TST-REQ-FND-009-04 | Unique failure and recovery outbox transitions plus SES delivery | Planned |
| REQ-FND-010 | DD-048; LLD 28.5 | TASK-046, TASK-047, TASK-049 | TST-REQ-FND-010-01, TST-REQ-FND-010-02, TST-REQ-FND-010-03, TST-REQ-FND-010-04, TST-REQ-FND-010-05, TST-REQ-FND-010-06, TST-REQ-FND-010-08 | Sanitized funding API and Performance history | Planned |
| REQ-FND-011 | DD-053; LLD 28.4, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-011-01, TST-REQ-FND-011-02 | Completed-flow adjusted P&L service and dashboard fields | Planned |
| REQ-FND-012 | DD-053; LLD 28.4, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-012-01, TST-REQ-FND-012-02, TST-REQ-FND-012-03 | Boundary-fresh Modified Dietz and unavailable states | Planned |
| REQ-FND-013 | DD-054; LLD 28.3, 28.7 | TASK-045, TASK-048, TASK-049 | TST-REQ-FND-013-01, TST-REQ-FND-013-02, TST-REQ-FND-013-03, TST-REQ-FND-013-04, TST-REQ-FND-013-05 | Alpaca Broker incoming ACH adapter and secret-source boundary | Planned |
| REQ-FND-014 | DD-054, DD-055; LLD 28.1, 28.2, 28.4 | TASK-042, TASK-045, TASK-048, TASK-049 | TST-REQ-FND-014-01, TST-REQ-FND-014-02, TST-REQ-FND-014-03, TST-REQ-FND-014-04, TST-REQ-FND-014-05, TST-REQ-FND-014-06, TST-REQ-FND-014-07, TST-REQ-FND-014-08 | Disabled/zero defaults and pre-adapter refusal matrix | Planned |
| REQ-FND-015 | DD-050, DD-055; LLD 28.2, 28.4 | TASK-042, TASK-045, TASK-049 | TST-REQ-FND-015-01, TST-REQ-FND-015-02, TST-REQ-FND-015-03, TST-REQ-FND-015-04 | Account lock, positive amount, caps, month accounting, pending slot | Planned |
| REQ-FND-016 | DD-050, DD-055; LLD 28.2, 28.3, 28.4 | TASK-042, TASK-044, TASK-045, TASK-049 | TST-REQ-FND-016-01, TST-REQ-FND-016-02, TST-REQ-FND-016-03, TST-REQ-FND-016-04 | Durable pre-network claim, one POST, unknown reconciliation | Planned |
| REQ-FND-017 | DD-055; LLD 28.2, 28.4 | TASK-042, TASK-044, TASK-045, TASK-049 | TST-REQ-FND-017-01, TST-REQ-FND-017-02 | Terminal transfer states, reservation release, no retry, alert | Planned |
| REQ-FND-018 | DD-055; LLD 28.1, 28.4, 28.6 | TASK-044, TASK-045, TASK-048, TASK-049 | TST-REQ-FND-018-01, TST-REQ-FND-018-02 | Current kill/emergency-stop checks with read reconciliation active | Planned |
| REQ-FND-019 | DD-049; LLD 28.1, 28.5 | TASK-041, TASK-046, TASK-047, TASK-049 | TST-REQ-FND-019-01, TST-REQ-FND-019-02, TST-REQ-FND-019-03, TST-REQ-FND-019-04, TST-REQ-FND-019-05 | Complete-object versioned config, full audit, Settings controls | Planned |
| REQ-FND-020 | DD-048, DD-054; LLD 28.1, 28.3, 28.7 | TASK-041, TASK-043, TASK-045, TASK-047, TASK-048, TASK-049 | TST-REQ-FND-020-01, TST-REQ-FND-020-02, TST-REQ-FND-020-03, TST-REQ-FND-020-04 | Polymarket observe-only validation and no write resource | Planned |

## Release Evidence Checklist

| Evidence | Development | Production |
|----------|-------------|------------|
| Tracking issue and pull requests | Pending | Pending |
| GitHub Actions run URL and final status | Pending | Pending |
| Database migration | Pending | Pending |
| CloudFormation stack status | Pending | Pending |
| ECS backend and frontend health | Pending | Pending |
| HTTPS `/health` | Pending | Pending |
| Authenticated sanitized `/api/funding` | Pending | Pending |
| Dashboard browser evidence | Pending | Pending |
| Direct transfers disabled and both limits `0.00` | Pending | Pending |
| CloudWatch Broker POST events in release window | Must equal zero | Must equal zero |
| SES identity and ACM certificate | Pending | Pending |

No real bank transfer is used for release verification.
