# Handoff: Dashboard IA & Usability Redesign

## Overview
Restructures the Poly Bot dashboard around one question — **"does anything need me right now?"** — for a mixed audience that includes non-technical stakeholders. Replaces the single dense Overview (10+ stacked panels) and an overflowing top nav with a flat 5-page IA and a priority-ordered Overview.

## About the Design Files
The files in this bundle are **design references created in HTML** (Design Components) — prototypes showing intended look and behavior, **not production code to copy directly**. The task is to **recreate these designs in the target codebase** (`codex-poly-bot/frontend`, a Next.js App Router + React + TypeScript app using `lucide-react` icons and a global `globals.css`) using its established patterns. TSX/CSS under `reference-tsx/` is a close starting point already written in the repo's conventions, but must be wired to real data.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, and interactions are specified below and in the prototype. Recreate pixel-accurately using the codebase's existing components (`ThemePreferenceControl`, `VenuePortfolioPanel`, config form, etc.) and CSS.

## Screens / Views

### 1. Top navigation
- **Purpose**: Move between the 5 areas; always fully visible.
- **Layout**: Sticky `.topbar`, flex row — brand left, nav + theme control right. No "More" overflow menu.
- **Items**: Overview (`/dashboard`), Activity (`/dashboard/activity`), Performance (`/dashboard/performance`), Settings (`/dashboard/config`), Help (`/dashboard/help`).
- **States**: active item bg `#e0f1ed`, text `#0b4f49`, weight 700; inactive transparent, text `#17202a`, weight 600. Min-height 40px, padding `0 16px`, radius 6px, gap 6px. Icons 15px, strokeWidth 2.3.

### 2. Overview
Three mutually-exclusive states drive the top of the page:
- **Needs attention** — warm card (`#fffaf7` bg, `#efb0a9` border, radius 12px, padding 26px). Circle icon 36px `#fae4e1`/`#a33a3a`. H2 20px. Each item: white card, `#e8d6d2` border, radius 10px, title 15px + muted body 13px, right-aligned primary button. Followed by the **recommended-settings** module: 3 cards (Tighten / Keep current [in use, disabled] / Loosen), current card `#f2f9f6`/`#9ed9c7`.
- **All clear** — green card `#f2f9f6`/`#9ed9c7`, check icon `#dff3ec`/`#0d5f52`. No action items, no recommendations.
- **Live trade** — blue card `#eef6ff`/`#a9c8ee`, `$` icon `#dbeafe`/`#1d4ed8`; trade detail row + link to Activity.

Below the state card (always shown):
- **"How things are running"** — 4-card grid (mode, active markets, last check, next check), each white card `#d7dee8` border radius 10px, label 12px muted / value 17px / sub 12px muted.
- **Recent result strip** — single white row, headline + muted sub, right link "See full activity →".
- **Explore more** — 3 link cards to Performance / Settings / Help.

### 3. Activity
Header (title + "Updated Xs ago" chip). "Last check, step by step" — 4-col funnel (Markets scanned → Looked promising → Passed confidence rule → Passed risk checks) with green/blue/red borders. "Recent checks" — log rows: time (110px) / summary / status pill.

### 4. Performance
Header + "Win rate trending up" chip. 6-col metric strip (Equity, Realized P&L green, Unrealized red, Open positions, Win rate, Trades). "By market" table: Market / Trades / Win rate / P&L.

### 5. Settings
Plain-language controls: Risk & trading rules (confidence slider 0–1 step .01, spread slider 0–.2, real-money toggle), Notifications (toggle + email field), Markets to watch (checkboxes).

### 6. Help
"One check, five steps" (Collect prices → Find candidates → Score → Simulate/submit → Monitor exits), numbered circles `#e0f1ed`/`#0b4f49`. FAQ list + back-to-Overview link.

## Interactions & Behavior
- Nav switches route; active state by pathname prefix.
- Overview state selector in prototype is a **demo aid only — remove in production**; compute state server-side from last cycle result.
- "Use this" on a recommendation should open a confirm step showing exact before/after config values before applying (with rollback) — not built in prototype.
- Sliders/toggles/email need persistence + validation.

## State Management
Derive in `consumer-dashboard.tsx` from existing hooks:
- `state`: `"live"` if last tick placed a non-simulation order; `"attention"` if any funnel stage blocked or a config/notification gap exists; else `"clear"`.
- Reuse existing types: `TickSummaryView`, `LastTickFunnelStage`, `RecommendationPlan`, `VenuePortfolioView`, `NotificationSettingsView`.
- Data via `dashboardApi` + `useDashboardRealtime` (already in the file).

## Design Tokens
- Background `#f4f6f8`; surface `#ffffff`; text `#17202a`; muted `#5f6c7b`; border `#d7dee8`.
- Brand green `#126b62` / hover `#0b4f49` / tint `#e0f1ed` / deep `#0b4f49`.
- Success `#0d5f52` / `#dff3ec` / `#9ed9c7`; info `#24558f` / `#e3eefc` / `#a9c8ee`; danger `#a33a3a` / `#fae4e1` / `#efb0a9`.
- Radius: 6px (controls), 10px (cards), 12px (state cards). Font: Inter. Sizes: h1 26, h2 16–20, body 13–14, label 11–12. Max content width 1100px; page padding 36px 32px 56px; grid gap 12–28px.

## Assets
Icons from `lucide-react` (Activity, GitBranch, BarChart3, SlidersHorizontal, CircleHelp, Bell, CheckCircle2). No image assets.

## Files
- `Poly Bot - Redesign.dc.html` — the redesign prototype (all 5 pages + 3 overview states; open in a browser).
- `Poly Bot - Current Dashboard.dc.html` — recreation of the current UI, for before/after reference.
- `reference-tsx/dashboard-nav.tsx` — drop-in replacement for `frontend/components/dashboard/dashboard-nav.tsx`.
- `reference-tsx/overview-page.tsx` — presentational Overview component with typed props; wire to real data in `consumer-dashboard.tsx`.
- `reference-tsx/overview-redesign.css` — append to `frontend/app/globals.css` (namespaced; coexists with existing `.consumer-*` classes during rollout).
