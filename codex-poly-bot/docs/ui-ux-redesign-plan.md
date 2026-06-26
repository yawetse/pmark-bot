# Poly Bot UI/UX Redesign Plan

Date: 2026-06-26

This plan covers the full `codex-poly-bot` web experience in `frontend/app/*` and `frontend/components/dashboard/*`, including login, access-denied, overview, operations, config, model, comparison, system, help, and model-detail routes. The app is a data-heavy internal trading operations dashboard built with Next.js, React, custom CSS tokens, AG Grid, Recharts, Radix primitives, and Lucide icons. The redesign should keep the dry-run and live-trading safety posture visible at all times, while moving exact records and advanced controls into clear detail regions.

The 2026-06-26 second pass uses the installed external Claude skills and the already-approved third-party UI libraries available in this repo: Vercel web design guidelines, Vercel React best practices, Vercel composition patterns, Bencium controlled UX designer, UI/UX Pro Max, AccessLint scan/audit guidance, AG Grid, Recharts, Radix Accordion/Dialog, and Lucide icons.

## External Skills To Use

| Snyk article skill | Use for this app | Why it applies | Use mode | Consent needed before install/use |
| --- | --- | --- | --- | --- |
| Vercel web design guidelines | All app routes, nav, forms, status indicators, responsive behavior, focus states, and route structure | The app has many operator controls, links, tables, and state labels that need consistent layout, labels, focus, and touch behavior | Use installed external skill | No |
| Bencium UX designer | Dashboard workflows, config editing, manual run triggers, operations review, kill switch, and error recovery | The app is an internal operations workflow with high-risk controls, progressive disclosure needs, and state recovery paths | Use installed external skill | No |
| AccessLint plugin | Color contrast, keyboard navigation, focus visibility, form labels, status colors, and color-only indicators | The app relies on status chips, dots, tables, form fields, and dangerous actions where accessibility failures can hide risk | Use installed external scan/audit guidance | No |
| UI/UX Pro Max | Visual system, density, palette, typography, spacing, elevation, and multi-page dashboard consistency | The app needs a product-appropriate operations aesthetic that is restrained, readable, and consistent across dashboard pages | Use installed external skill | No |
| Vercel React best practices | React and Next.js components in `components/dashboard/*`, data grids, dynamic model pages, and client-side state updates | The redesign touches client components, grid rendering, form state, local preferences, and table views | Use installed external skill | No |
| Vercel composition patterns | Shared panel, metric, status, form, table, and page layout components | Several views repeat similar panel and metric patterns through local markup instead of a small component system | Use installed external skill | No |
| Anthropic frontend-design | Optional later visual concept pass for a public product page | This is not a marketing page, so the controlled operations pattern is a better fit for this pass | Skip | No |
| Vercel React Native Skills | Not applicable | This is a web app, not React Native or Expo | Skip | No |

## Current UI Findings

- `frontend/app/login/page.tsx` and `frontend/app/access-denied/page.tsx`: the auth pages use the old bare panel style and should share the same shell quality, focus behavior, and operator-specific copy as the dashboard.
- `frontend/app/dashboard/page.tsx` and `components/dashboard/operator-command-center.tsx`: the main route correctly puts dry-run state first, but it mixes state summary, loop telemetry, preferences, manual run, runtime status, next actions, market data, economics, and control links on one long page. The operator needs a clearer split between "act now", "monitor", and "inspect details".
- `/tmp/polybot-dashboard-after-desktop.png`: the current first viewport is readable after the recent polish pass, but the loop monitor still dominates the screen before the operator sees next actions, manual run, and risk controls.
- `/tmp/polybot-dashboard-after-mobile.png`: the mobile layout stacks cleanly, but the top navigation becomes a horizontal strip with limited visible context. This is acceptable for a first pass, but a compact mobile nav pattern would be better before adding more screens.
- `components/dashboard/loop-monitor.tsx`: the loop monitor shows useful detail, but stages, data inputs, prompts, logic, calculations, gates, and records compete for attention. Long data such as stock universe symbols needs summary-first display with expandable detail.
- `components/dashboard/config-controls.tsx`: config editing exposes powerful controls through text areas and a generic path/value editor. It needs safer grouped settings, preview of impact, stronger validation, and clearer conflict recovery.
- `components/dashboard/dashboard-nav.tsx`: Claude and OpenAI are top-level nav items even though they are peer detail views under one model workflow. The top-level IA should be task-based: Status, Operations, Config, Models, Performance, System, Help.
- `components/dashboard/operations-view.tsx`: operations contains pipeline runs, scanner, reasoning, strategy, execution, exit, historical import, broker history, market data, economics, order tables, and kill switch control. This should become a workflow-oriented operations console, not a single stacked report. Exact rows should start in "View details" disclosures.
- `components/dashboard/data-grid.tsx`: AG Grid is already a reasonable base for high-density tables. The custom wrapper should standardize search, empty states, table titles, column presets, row density, and horizontal scroll behavior.
- `components/dashboard/economics-panel.tsx` and `components/dashboard/comparison-view.tsx`: economics and comparison currently lean on metrics and tables. They need trend and comparison views before tables, because the operator needs to know whether costs, P&L, usage, and provider performance are moving in the wrong direction.
- `components/dashboard/model-summary.tsx`: model pages normalize arbitrary row objects into grids. This is flexible, but the IA should expose a single Models top-level route with Claude/OpenAI as detail targets, not separate global nav items.
- `frontend/app/globals.css`: the current CSS token layer is simple and workable. A deeper redesign should formalize tokens, component variants, responsive rules, and status semantics instead of adding one-off styles.

## Component Library Sanity Check

| Custom component | Current risk | Candidate library | Recommendation | Consent needed |
| --- | --- | --- | --- | --- |
| `DashboardDataGrid` wrapper around AG Grid | The wrapper is thin, so every table must solve title, search, density, empty state, and horizontal scroll behavior separately | AG Grid, already installed | Keep AG Grid and improve the local wrapper. Do not replace it unless licensing or bundle size becomes a blocker | No |
| Dynamic model and operations tables | Arbitrary object normalization can create unstable column order and weak labels | AG Grid column state plus local column presets | Keep AG Grid, add typed column presets for decisions, orders, positions, and run records | No |
| Config path/value editor | Generic textarea editing is flexible but risky for live-trading settings | React Hook Form with Zod, or keep custom with typed field groups | Recommend a library only if config editing expands. Ask before installing `react-hook-form` and `zod` | Yes |
| Status chips, metric cards, panels, and control links | Repeated custom markup can drift across pages | shadcn/ui, Radix UI primitives, or local components | Prefer local primitives first because the app already has a small CSS system. Consider Radix only for dialogs, tabs, menus, and disclosure controls | Yes |
| Operations workflow accordions or tabs | A long stacked page hides task boundaries | Radix UI Tabs, Accordion, Dialog | Recommend Radix primitives if implementing tabbed or disclosure-heavy workflows. Ask before installing | Yes |
| Charts and trend panels | The app has no charting layer, so trend questions fall back to tables | Recharts, Apache ECharts, Vega-Lite | Recommend Recharts for basic React charts first. Ask before installing. Use ECharts only if the app needs richer dashboard interactions | Yes |

## Visual Redesign Plan

- Direction: Treat Poly Bot as an operator console, not a marketing dashboard. The tone should be calm, dense, and explicit. The UI should make safe mode, blockers, live gates, risk, orders, costs, and next loop state easy to scan.
- Layout: Move toward a three-level hierarchy. Level one is global state and action needed. Level two is core workflows: Monitor, Configure, Operate, Analyze. Level three is exact records and audit trails. Avoid putting every dataset into the first screen.
- Navigation: Keep a predictable top route nav for desktop, but make it task-based: Status, Operations, Config, Models, Performance, System, Help. Provider pages remain deep links under Models. For mobile, keep the scroll strip but add icons, better active state, and skip-to-content.
- Typography: Use a tighter operations scale. Page titles should identify state or task. Panel headings should stay compact. Table cells and form labels should use deliberate sizes, not inherited defaults.
- Color: Keep a neutral light/dark system with teal for safe/monitor state, red for blocked/danger, blue for waiting/informational state, and gray for idle/unknown state. Status should never rely on color alone.
- Spacing: Use 8px radius or less, consistent 12/16/20px spacing, and stable card heights for metric and status summaries. Avoid nested card stacks unless the content is a repeated item.
- Iconography: Add a small icon system only where it improves scan speed: status, risk gates, run stages, save, trigger, stop, refresh, filter, expand, collapse. Use an installed icon library only after approval.
- Motion: Use subtle motion only for state changes, save feedback, loading skeletons, and disclosure transitions. Respect `prefers-reduced-motion`.
- Imagery: Do not add decorative imagery. This is an operations app. Visual effort should go into data views, hierarchy, and feedback.

## UX Redesign Plan

- Primary dashboard flow: Start with "Current mode", "Action needed", "Next scheduled loop", and "Manual run" above the fold. Move lower-detail loop internals, market records, and cost tables into expandable sections.
- Operations flow: Split `/dashboard/operations` into workflow sections: Run Pipeline, Candidate Review, Model Reasoning, Strategy Decision, Execution, Exit, Imports, Orders, Kill Switch. Each section should show summary metrics first and place exact AG Grid records behind disclosure.
- Model flow: Add `/dashboard/models` as the top-level model workspace. Keep `/dashboard/models/claude` and `/dashboard/models/openai` as provider detail routes. Detailed positions, decisions, and orders start collapsed.
- Help flow: Keep architecture and run flow visible. Move component, storage, infrastructure, environment, and release reference tables into expandable sections.
- Config flow: Replace the generic path-first experience with grouped controls for venue, live mode, risk, notifications, Alpaca universe, model budgets, and loop cadence. Keep an advanced JSON/path editor behind disclosure for rare edits.
- Manual run behavior: Make each run mode show risk level, expected stages, whether live orders are possible, and audit impact before the operator triggers it.
- Feedback: Standardize saved, conflict, failed, accepted, queued, and blocked messages. Each message should say what happened, whether the next loop is affected, and what the operator can do next.
- Loading states: Add skeletons or compact loading panels for dashboard summary, config, operations, economics, and grids. Avoid blank panels.
- Empty states: Keep empty states brief and task-oriented. Example: "No scanner candidates yet" should offer "Run scanner only" or explain which gate is needed.
- Error states: API unavailable states should show route-specific recovery: retry, check backend health, or open system readiness.
- Success states: Config saves, preference saves, imports, and manual runs should show a consistent success surface with version/run ID, timestamp, and next step.
- Progressive disclosure: Long symbol lists, prompt text, run metadata, model checks, and calculation details should start summarized and expand on demand.
- High-risk actions: Kill switch and live mode changes need dedicated confirmation flows with typed confirmation or explicit checkbox plus clear scope.

## Data Visualization Plan

| Data question | Recommended view | Why it fits | Table fallback |
| --- | --- | --- | --- |
| Is the bot safe to run now? | Status band plus gate checklist | The operator needs a fast go/no-go read before details | System readiness table and audit rows |
| What will happen on the next loop? | Timeline or stage stepper with current phase and blockers | Loop state is sequential and easier to scan as a process | Full loop records and audit trail |
| Which stage blocks trading? | Gate matrix grouped by venue, credentials, risk, data, notifications, and kill switch | Blockers are categorical, not just row records | System status rows |
| Are costs and P&L moving in the wrong direction? | Line chart for net after costs and stacked bars for AI/AWS cost | The decision is trend and composition, not row lookup | Economics snapshots grid |
| Which model provider performs better? | Small multiples for P&L, win rate, drawdown, token cost, and return-to-risk | Comparison needs side-by-side provider trend and variance | Comparison metrics grid |
| Which candidates deserve review? | Ranked candidate list with liquidity, spread, confidence, and risk badges | Operators need prioritization before exact row detail | Scanner candidate AG Grid |
| What changed in the latest run? | Run summary cards plus stage detail table | A run is a workflow event with counts and exceptions | Pipeline and step grids |
| Which orders require action? | Exception list for pending, failed, refused, and manual-review states | Action-needed rows should be separated from history | Full order event grid |

Recommended first visualization library: Recharts, subject to approval before install. It fits React dashboards with common charts and lighter implementation cost. Keep AG Grid for exact records, audit trails, reconciliation, filtering, and export-like lookup workflows.

## Accessibility And Responsive Plan

- Keyboard: Confirm tab order for top nav, theme control, config forms, manual run buttons, AG Grid filters, and kill switch controls. Add skip-to-content if top nav grows.
- Focus: Use visible focus states for links, segmented controls, form inputs, table controls, and high-risk buttons. Do not remove browser focus outlines without replacing them.
- Labels: Every form input, select, textarea, grid filter, and dangerous action must have a visible label and programmatic association.
- Contrast: Check light and dark mode for text, status chips, dots, borders, and disabled states. Status chips should pass contrast without relying on background color alone.
- Color-only status: Pair color with text, icon, or shape for ok, blocked, idle, waiting, and live states.
- Touch targets: Keep mobile nav, buttons, segmented controls, and form controls at least 40px high where practical.
- Responsive: Use desktop, tablet, and 390px mobile checks. The mobile dashboard should show current mode, next action, and primary controls before detailed records.
- Reduced motion: Keep state transitions subtle and disable non-essential animation under `prefers-reduced-motion`.

## Engineering Plan

- `frontend/app/globals.css`: convert current CSS into a documented token and component layer: shell, nav, panel, metric, status, form, table, disclosure, empty state, toast/message, and danger controls.
- `components/dashboard/dashboard-nav.tsx`: keep active route state and add grouped mobile navigation when route count grows.
- `components/dashboard/operator-command-center.tsx`: restructure the main dashboard into "current state", "action needed", "manual run", "loop summary", and lower-detail sections.
- `components/dashboard/loop-monitor.tsx`: add summary-first loop display, expandable detail groups, and a shorter treatment for long data.
- `components/dashboard/config-controls.tsx`: replace generic path-first editing with grouped, typed field sections and an advanced editor.
- `components/dashboard/operations-view.tsx`: split the large page into reusable operation section components and add a workflow navigation pattern.
- `components/dashboard/data-grid.tsx`: improve the wrapper with title support, density variants, empty state action slots, consistent filter placement, optional column presets, and responsive horizontal scroll treatment.
- `components/dashboard/economics-panel.tsx`: add chart-ready data shaping for trend and cost composition before introducing any chart library.
- `components/dashboard/comparison-view.tsx` and `components/dashboard/model-summary.tsx`: define stable metrics and columns before adding visual comparison views.
- Verification: run `npm run typecheck`, `npm run build`, `npm run test:auth-boundary`, `npm run test:dashboard-controls`, and `npm run test:dashboard-operations`. Use rendered screenshots at desktop and mobile widths for every redesigned route.

## UI/UX Polish Checklist

- [ ] [Vercel web design guidelines] Capture baseline screenshots for `/login`, `/access-denied`, `/dashboard`, `/dashboard/config`, `/dashboard/operations`, `/dashboard/models`, `/dashboard/models/claude`, `/dashboard/models/openai`, `/dashboard/comparison`, `/dashboard/system`, and `/dashboard/help`. Acceptance: screenshots show desktop and mobile layout, empty states, blocked states, and primary controls. Verify with browser or Playwright screenshots.
- [ ] [UI/UX Pro Max] Document the Poly Bot visual system. Acceptance: tokens for color, type, spacing, radius, elevation, status, forms, tables, and messages are written before code changes. Verify by reviewing `frontend/app/globals.css`.
- [ ] [Bencium UX designer] Redesign the main dashboard around current state, action needed, manual run, next loop, and detail inspection. Acceptance: the first viewport answers "is the bot safe, what needs action, and what can I do now?" Verify with desktop and mobile screenshots.
- [ ] [Bencium UX designer] Redesign `/dashboard/operations` into workflow sections for pipeline, scanner, reasoning, strategy, execution, exit, imports, orders, and kill switch. Acceptance: each section has summary, detail, and recovery action. Verify with interaction review and route screenshots.
- [ ] [Bencium UX designer] Add `/dashboard/models` and demote provider routes from global navigation to model-workspace details. Acceptance: top-level nav is task-based and providers remain deep-linkable. Verify with route screenshots.
- [ ] [Bencium UX designer] Add expandable details to model, operations, config, and help/reference surfaces. Acceptance: first view shows summary and action, exact records are available through disclosure. Verify with interaction review.
- [ ] [Bencium UX designer] Redesign `/dashboard/config` into grouped setting sections with an advanced editor. Acceptance: common edits no longer require choosing raw config paths first. Verify with form interaction tests and conflict/error-state checks.
- [ ] [AccessLint plugin] Check contrast, keyboard order, labels, focus states, ARIA, status indicators, and color-only cues across the touched routes. Acceptance: no obvious WCAG A/AA failures remain in the changed UI. Verify with keyboard pass and contrast checks.
- [ ] [Vercel composition patterns] Extract shared primitives for panel, metric, status chip, message, form section, disclosure, and empty state. Acceptance: repeated route markup uses shared components without changing the data contracts. Verify with code review and typecheck.
- [ ] [Vercel React best practices] Review touched client components for avoidable re-renders, unstable object creation, heavy imports, and table/list costs. Acceptance: no new obvious render or bundle regression is introduced. Verify with `npm run build` and targeted code review.
- [ ] [Vercel web design guidelines] Extend `DashboardDataGrid` with consistent title, search, density, empty action, and responsive behavior. Acceptance: all grid-heavy routes use one consistent grid shell. Verify with grid screenshots and keyboard checks.
- [ ] [UI/UX Pro Max] Add a data visualization specification for economics and comparison before installing chart packages. Acceptance: chart data questions, chart types, empty states, and table fallbacks are documented. Verify with design review.
- [ ] [AccessLint plugin] Design high-risk action confirmations for live mode and kill switch. Acceptance: irreversible or live-trading-affecting actions require clear scope and confirmation. Verify with interaction tests.
- [ ] [Vercel web design guidelines] Run final responsive and interaction QA. Acceptance: desktop and mobile screenshots match the redesign plan, text fits containers, controls remain usable, and no framework overlay or console errors appear. Verify with Browser or Playwright plus `npm run typecheck`.

## Implementation Scope For Second Pass

- Use installed external Claude skills and already-present third-party libraries.
- Do not add a new package unless a later task needs a specific missing primitive.
- Keep AG Grid for exact records and audit tables.
- Use Radix Accordion/Dialog for disclosure and high-risk confirmation.
- Use Recharts only where charting already exists.
- Keep the visual tone restrained and operational.
