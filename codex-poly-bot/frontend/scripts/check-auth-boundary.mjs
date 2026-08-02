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
  home: "app/page.tsx",
  login: "app/login/page.tsx",
  productLanding: "components/product-story/product-landing.tsx",
  productStoryPage: "app/story/page.tsx",
  productStoryArticle: "components/product-story/product-story-article.tsx",
  methodExplorer: "components/product-story/method-explorer.tsx",
  help: "components/dashboard/help-about-view.tsx",
  logout: "app/api/auth/logout/route.ts",
  realtimeToken: "app/dashboard-realtime-token/route.ts",
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
assert.match(login, /LoginProductLanding/);

const home = read(files.home);
assert.match(home, /PublicProductLanding/);
assert.doesNotMatch(home, /redirect\("\/dashboard"\)/);

const productLanding = read(files.productLanding);
assert.match(productLanding, /\/api\/auth\/github\/start/);
assert.match(productLanding, /MethodExplorer/);
assert.match(productLanding, /PublicProductLanding/);
assert.match(productLanding, /LoginProductLanding/);
assert.match(productLanding, /href="\/story"/);
assert.match(productLanding, /Polymarket, Kalshi, and Alpaca/);
assert.match(productLanding, /Kalshi supports standard binary markets on the primary subaccount/);
assert.doesNotMatch(productLanding, /original post|source post|source method/i);

const productStoryPage = read(files.productStoryPage);
assert.match(productStoryPage, /ProductStoryArticle/);
assert.match(productStoryPage, /canonical: "https:\/\/codex-poly-bot\.repetere\.net\/story"/);

const productStoryArticle = read(files.productStoryArticle);
assert.match(productStoryArticle, /Why a trading bot should be allowed to do nothing/);
assert.match(productStoryArticle, /Product note · July 2026/);
assert.match(productStoryArticle, /A prediction describes what may happen/);
assert.match(productStoryArticle, /What the product does not claim/);
assert.match(productStoryArticle, /Explore the technical methods/);
assert.match(productStoryArticle, /\/api\/auth\/github\/start/);
assert.doesNotMatch(productStoryArticle, /MethodExplorer/);
assert.doesNotMatch(productStoryArticle, /Yaw Etse|Poly Bot is my|I wanted|I recommend/);
assert.doesNotMatch(productStoryArticle, /guaranteed returns|original post|source post/i);

const methodExplorer = read(files.methodExplorer);
assert.match(methodExplorer, /@radix-ui\/react-dialog/);
assert.match(methodExplorer, /Remove weak candidates/);
assert.match(methodExplorer, /Strategies and algorithms/);
assert.match(methodExplorer, /Whale copy/);
assert.match(methodExplorer, /Fractional Kelly/);

const help = read(files.help);
assert.match(help, /MethodExplorer/);

const logout = read(files.logout);
assert.match(logout, /clearDashboardSession/);
assert.match(logout, /\/login\?status=signed_out/);
assert.match(logout, /NextResponse\.redirect/);

const realtimeToken = read(files.realtimeToken);
assert.match(realtimeToken, /getDashboardSession/);
assert.match(realtimeToken, /mintBackendToken/);
assert.doesNotMatch(files.realtimeToken, /^app\/api\//);

const startRoute = read("app/api/auth/github/start/route.ts");
assert.match(startRoute, /ALLOW_LOCAL_AUTH_BYPASS/);
assert.match(startRoute, /setDashboardSession/);
assert.match(startRoute, /process\.env\.NODE_ENV !== "production"/);
