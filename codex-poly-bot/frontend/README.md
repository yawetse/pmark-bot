# Frontend

REQ: REQ-UI-001, REQ-UI-002, REQ-UI-003, REQ-UI-006, REQ-OBS-004

The dashboard is a Next.js App Router app. Browser code calls same-origin `/dashboard-api/*` routes. Those route handlers validate the web session, mint short-lived FastAPI bearer tokens on the server, and forward requests to the backend.

## Local Commands

1. Install dependencies with `npm install`.
2. Copy `.env.example` to `.env.local` and set local secrets.
3. Run `npm run dev`.
4. Run `npm run typecheck`, `npm run test:auth-boundary`, and `npm run test:dashboard-controls` before committing frontend changes.

`BACKEND_TOKEN_SIGNING_SECRET` and `DASHBOARD_SESSION_SECRET` must not use `NEXT_PUBLIC_*` names.
