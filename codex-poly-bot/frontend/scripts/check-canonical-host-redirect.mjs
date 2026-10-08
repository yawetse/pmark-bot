import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../lib/server/canonical-host-redirect.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const helperUrl = `data:text/javascript;base64,${Buffer.from(compiled.outputText).toString("base64")}`;
const { canonicalHostRedirect } = await import(helperUrl);
const old = "codex-poly-bot.repetere.net";
const current = "https://nilesagent.com";
const redirect = (path, method = "GET") => canonicalHostRedirect(`https://${old}${path}`, method, current, old);

assert.equal(redirect("/"), `${current}/`);
assert.equal(redirect("/dashboard/performance?token=private&next=https://other.invalid"), `${current}/dashboard/performance`);
assert.equal(redirect("/story", "HEAD"), `${current}/story`);
assert.equal(redirect("/api/auth/github/start?next=https://other.invalid"), `${current}/login?status=domain_changed`);
assert.equal(redirect("/api/auth/github/callback?code=private&state=private"), `${current}/login?status=domain_changed`);
for (const path of ["/api/portfolio", "/dashboard-api/portfolio", "/api/auth/logout", "/_next/static/chunk.js"]) {
  assert.equal(redirect(path), null);
}
assert.equal(redirect("/dashboard", "POST"), null);
assert.equal(canonicalHostRedirect(`${current}/dashboard`, "GET", current, old), null);
assert.equal(canonicalHostRedirect(`https://${old}/`, "GET", `https://${old}`, old), null);
assert.equal(canonicalHostRedirect(`https://${old}.other.invalid/`, "GET", current, old), null);
assert.equal(canonicalHostRedirect(`https://${old}/`, "GET", "http://nilesagent.com", old), null);
assert.equal(canonicalHostRedirect(`https://${old}/`, "GET", "https://user:password@nilesagent.com", old), null);
assert.equal(canonicalHostRedirect(`https://${old}/`, "GET", undefined, old), null);
assert.equal(canonicalHostRedirect("invalid", "GET", current, old), null);

// Exercise the actual proxy with Next's request/response objects: request.url can
// contain the internal listener host even when the public Host header is correct.
const nextServerUrl = new URL("../node_modules/next/server.js", import.meta.url).href;
const proxySource = await readFile(new URL("../proxy.ts", import.meta.url), "utf8");
const proxyJs = ts.transpileModule(proxySource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
  .replace('"next/server"', JSON.stringify(nextServerUrl))
  .replace('"@/lib/server/canonical-host-redirect"', JSON.stringify(helperUrl));
const { proxy } = await import(`data:text/javascript;base64,${Buffer.from(proxyJs).toString("base64")}`);
const { NextRequest } = await import(nextServerUrl);
const keys = ["NEXTAUTH_URL", "LEGACY_APPLICATION_DOMAIN_NAME", "LEGACY_DOMAIN_REDIRECT_ENABLED"];
const original = Object.fromEntries(keys.map((key) => [key, process.env[key]]));
try {
  process.env.NEXTAUTH_URL = current;
  process.env.LEGACY_APPLICATION_DOMAIN_NAME = old;
  process.env.LEGACY_DOMAIN_REDIRECT_ENABLED = "true";
  const request = new NextRequest("http://127.0.0.1:3199/dashboard?code=private", { headers: { host: old } });
  const response = proxy(request);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), `${current}/dashboard`);
  assert.equal(response.headers.get("cache-control"), "no-store");
  process.env.LEGACY_DOMAIN_REDIRECT_ENABLED = "false";
  assert.equal(proxy(request).headers.get("x-middleware-next"), "1");
} finally {
  for (const key of keys) {
    if (original[key] === undefined) delete process.env[key];
    else process.env[key] = original[key];
  }
}
console.log("Canonical-host navigation, OAuth transition, and rollback boundaries passed.");
