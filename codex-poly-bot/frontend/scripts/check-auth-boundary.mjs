import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-006, REQ-OBS-004

const files = {
  backendToken: "lib/server/backend-token.ts",
  serverSession: "lib/server/session.ts",
  proxy: "app/dashboard-api/[...path]/route.ts",
  apiClient: "lib/api.ts",
  dashboard: "app/dashboard/page.tsx",
  settings: "app/dashboard/config/page.tsx",
  login: "app/login/page.tsx",
  logout: "app/api/auth/logout/route.ts",
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
assert.match(serverSession, /secureCookiesEnabled/);
assert.match(serverSession, /NEXTAUTH_URL/);
assert.match(serverSession, /clearDashboardSession/);
assert.match(serverSession, /SESSION_COOKIE_NAME/);
assert.match(serverSession, /OAUTH_STATE_COOKIE_NAME/);

const proxy = read(files.proxy);
assert.match(proxy, /mintBackendToken/);
assert.match(proxy, /Authorization", `Bearer/);
assert.match(proxy, /X-CSRF-Token/);
assert.match(proxy, /mutationOrigin/);
assert.match(proxy, /request\.headers\.get\("origin"\)/);
assert.match(proxy, /NEXTAUTH_URL/);
assert.doesNotMatch(proxy, /GITHUB_CLIENT_SECRET/);

const apiClient = read(files.apiClient);
assert.match(apiClient, /\/dashboard-api\//);
assert.doesNotMatch(apiClient, /BACKEND_TOKEN_SIGNING_SECRET/);

const dashboard = read(files.dashboard);
assert.match(dashboard, /redirect\("\/login"\)/);
assert.match(dashboard, /redirect\("\/access-denied"\)/);

const settings = read(files.settings);
assert.match(settings, /LogoutControl/);
assert.match(settings, /sessionCheck\.session\.username/);

const login = read(files.login);
assert.match(login, /\/api\/auth\/github\/start/);

const logout = read(files.logout);
assert.match(logout, /clearDashboardSession/);
assert.match(logout, /\/login\?status=signed_out/);
assert.match(logout, /NextResponse\.redirect/);

const startRoute = read("app/api/auth/github/start/route.ts");
assert.match(startRoute, /ALLOW_LOCAL_AUTH_BYPASS/);
assert.match(startRoute, /setDashboardSession/);
assert.match(startRoute, /process\.env\.NODE_ENV !== "production"/);
