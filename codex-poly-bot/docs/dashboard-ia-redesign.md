# Dashboard Information Architecture Redesign

## Delivery Record

- GitHub issue: `#194`
- Design authority: `../TODO/design_handoff_dashboard_ia/`
- Branch: `codex/dashboard-ia-redesign`
- Requirements: `REQ-UI-016` through `REQ-UI-026`
- Tasks: `TASK-036`, `TASK-037`, `TASK-038`, `TASK-040`, and release task `TASK-039`

## Redesign Direction

The dashboard is organized around five operator questions.

| Destination | Question | Content owner |
|-------------|----------|---------------|
| Overview | Does anything need me now? | One derived state, runtime facts, latest result, contextual links |
| Activity | What did the system check? | Latest funnel and recent check log |
| Performance | What confirmed financial result exists? | Venue-confirmed Equity, Realized and Unrealized P&L, Open positions, Win rate, Trades, holdings, fills, and by-market summary |
| Settings | What can I change? | Common plain-language controls and advanced configuration |
| Help | How does the system work? | Five ordered steps and common questions |

Specialist operations, model, comparison, market, scenario, data, and system routes remain available through contextual links and direct URLs. The detailed Operations route retains manual runs and the emergency stop and is linked from Activity and Settings. These routes do not compete for primary navigation space.

## External Skill Selection

| Skill | Intended use | Decision | Package impact |
|-------|--------------|----------|----------------|
| UI/UX polish | Audit the existing hierarchy and maintain this delivery checklist | Use | None |
| Frontend design | Match the handoff's calm operational visual direction | Use | None |
| React best practices | Keep route data boundaries and client updates efficient | Use | None |
| React composition patterns | Split data orchestration from route-specific presentation | Use | None |
| Accessibility audit | Verify WCAG behavior after implementation | Use during verification | None |

No external UI package is added. The redesign uses the installed React, Next.js, Lucide, Recharts, Radix, and AG Grid dependencies where needed.

## Component Sanity Check

| Existing area | Decision | Reason |
|---------------|----------|--------|
| `DashboardNav` | Replace route model and remove overflow menu | The handoff requires five visible destinations |
| `ConsumerDashboard` | Keep data and mutation orchestration; replace presentation | Existing realtime, config, portfolio, and recommendation logic is valuable |
| Operations view | Reuse its typed operation data in a focused Activity view | Avoid a new backend contract |
| Venue portfolio view | Reuse confirmed portfolio data in a focused Performance view | Preserve financial source-of-truth rules |
| Config controls | Put common controls first and retain advanced controls | Preserve all existing validated configuration capabilities |
| Help view | Replace with a five-step static explanation and concise FAQ | Help should not depend on backend health |
| Charts | Use only for a meaningful performance trend | Funnel stages and current metrics are clearer as counts and tables |

## Visual System

- Page background: cool gray `#f4f6f8`
- Surface: white with low-contrast `#d7dee8` borders
- Primary text: `#17202a`
- Secondary text: `#5f6c7b`
- Status accents: green, amber, and blue with icons and text labels
- Content width: 1100 pixels maximum
- Desktop spacing: 32 to 36 pixels around the main content
- Typography: existing Inter-compatible system stack
- Motion: short opacity and transform feedback only; disabled for reduced motion

## Actionable Checklist

### Traceable design

- [x] Add permanent EARS requirements for navigation, state derivation, route ownership, accessibility, degraded behavior, and safe recommendations.
- [x] Add HLD decisions for the five-route IA, state precedence, responsive navigation, component reuse, and recommendation safety.
- [x] Add LLD route, data, component, edge-case, and mutation details.
- [x] Add implementation tasks and production release acceptance criteria.
- [x] Complete independent HLD and LLD reviews and address findings.

### Implementation

- [x] Render Overview, Activity, Performance, Settings, and Help as the five primary destinations.
- [x] Remove the More menu and preserve specialist routes through contextual links.
- [x] Derive one Overview state from real data with `live > attention > clear` precedence.
- [x] Remove prototype controls and duplicate detail sections from Overview.
- [x] Add focused Activity funnel and recent check log.
- [x] Make each Activity funnel count open the exact persisted market, score, strategy, or order records behind the latest run.
- [x] Add confirmed Performance metrics and by-market summary.
- [x] Put common Settings controls first and preserve advanced controls.
- [x] Replace Help with five ordered steps and concise FAQs.
- [x] Implement confirmation and undo for setting recommendations.
- [x] Match the handoff tokens, spacing, hierarchy, and responsive navigation.

### Verification and release

- [x] Pass frontend typecheck and dashboard test suites.
- [x] Pass code review and reconcile every finding.
- [x] Pass live DOM accessibility and keyboard-focus checks. The Accesslint runtime was not available, so the local sweep checked one H1, named interactive controls, duplicate IDs, focus outline, and page overflow on each primary route.
- [x] Verify 390-pixel mobile, 820-pixel tablet, and desktop layouts without page overflow.
- [x] Validate CloudFormation, deployment shell scripts, and required deployment tests. Shell validation and 40 deployment tests passed locally; development and production CloudFormation jobs passed in GitHub Actions.
- [x] Merge implementation to `develop` and verify the development deployment, ECS services, HTTPS health, TLS certificate, and OAuth boundary.
- [x] Merge `develop` to `main` and verify the production deployment, ECS services, HTTPS health, TLS certificate, and OAuth boundary.
- [x] Complete the requirement-to-code-to-test traceability matrix and attach the release evidence to issue #194.

## Local Verification Evidence

- `npm run typecheck`
- `npm run test:dashboard-redesign`
- `npm run test:auth-boundary`
- `npm run test:dashboard-controls`
- `npm run test:dashboard-operations`
- `npm run build`
- `bash -n scripts/deploy-stack.sh`
- `backend/.venv/bin/python -m pytest backend/tests/spec/test_deployment_ci.py` with 40 passing tests
- `backend/.venv/bin/python -m pytest backend/tests/spec` with 419 passing tests
- Browser review at desktop, 820 by 700, and 390 by 844 with labeled navigation and 390-pixel `scrollWidth === clientWidth`
- Automated live DOM sweep across all five routes with one H1, zero unnamed native interactive controls, and zero duplicate IDs

## Release Verification Evidence

- Implementation PR: [#195](https://github.com/yawetse/pmark-bot/pull/195)
- Development deployment: [GitHub Actions run 29836817504](https://github.com/yawetse/pmark-bot/actions/runs/29836817504)
  - CloudFormation stack `codex-poly-bot-development` was current.
  - ECS services `codex-poly-bot-development-backend` and `codex-poly-bot-development-frontend` deployed successfully.
  - `https://dev-codex-poly-bot.repetere.net/health` returned HTTP 200 with `{"status":"ok"}`.
  - `/dashboard` redirected to the GitHub OAuth sign-in boundary.
- Production promotion PR: [#196](https://github.com/yawetse/pmark-bot/pull/196)
- Production deployment: [GitHub Actions run 29837587362](https://github.com/yawetse/pmark-bot/actions/runs/29837587362)
  - CloudFormation stack `codex-poly-bot-production` was current.
  - ECS services `codex-poly-bot-production-backend` and `codex-poly-bot-production-frontend` deployed successfully and reached steady state.
  - `https://codex-poly-bot.repetere.net/health` returned HTTP 200 with `{"status":"ok"}`.
  - `/dashboard` redirected to the browser-rendered GitHub OAuth sign-in boundary.
- Both stacks reported the expected ACM certificate ARN. Public TLS checks reported `CN=*.repetere.net`, issued by Amazon RSA 2048 M04, valid through October 27, 2026.
- Both deployment jobs used the configured SES identity `asyncdoc.net` in `us-east-1`.
- The verification browser did not have a GitHub session. Authenticated dashboard content was verified locally against the same build; deployed checks covered HTTPS, health, TLS, page rendering, and the OAuth boundary.
