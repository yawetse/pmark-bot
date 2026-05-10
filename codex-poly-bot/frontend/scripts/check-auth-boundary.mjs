import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-006, REQ-OBS-004

const files = {
  backendToken: "lib/server/backend-token.ts",
  serverSession: "lib/server/session.ts",
  proxy: "app/dashboard-api/[...path]/route.ts",
  apiClient: "lib/api.ts",
  dashboard: "app/dashboard/page.tsx",
  login: "app/login/page.tsx",
};

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const backendToken = read(files.backendToken);
assert.match(backendToken, /import "server-only"/);
assert.doesNotMatch(backendToken, /NEXT_PUBLIC_[A-Z_]*SECRET/);
assert.match(backendToken, /BACKEND_TOKEN_SIGNING_SECRET/);

const serverSession = read(files.serverSession);
assert.match(serverSession, /import "server-only"/);
assert.match(serverSession, /DASHBOARD_ALLOWED_USERS/);
assert.match(serverSession, /httpOnly: true/);

const proxy = read(files.proxy);
assert.match(proxy, /mintBackendToken/);
assert.match(proxy, /Authorization", `Bearer/);
assert.match(proxy, /X-CSRF-Token/);
assert.doesNotMatch(proxy, /GITHUB_CLIENT_SECRET/);

const apiClient = read(files.apiClient);
assert.match(apiClient, /\/dashboard-api\//);
assert.doesNotMatch(apiClient, /BACKEND_TOKEN_SIGNING_SECRET/);

const dashboard = read(files.dashboard);
assert.match(dashboard, /redirect\("\/login"\)/);
assert.match(dashboard, /redirect\("\/access-denied"\)/);

const login = read(files.login);
assert.match(login, /\/api\/auth\/github\/start/);
