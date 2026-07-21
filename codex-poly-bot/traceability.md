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
| REQ-UI-020 | `frontend/lib/dashboard-activity-view-model.ts`; `activity-view.tsx` | `check-dashboard-redesign-behavior.ts` proves one-run metric mapping, unavailable handling, and realtime error clearing | Pass |
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
