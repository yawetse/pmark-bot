// Redirect navigation only. Never transfer OAuth state, codes, cookies, or API bodies.
export function canonicalHostRedirect(
  requestUrl: string,
  method: string,
  canonicalBase: string | undefined,
  legacyHostname: string | undefined,
): string | null {
  if (!canonicalBase || !legacyHostname || !["GET", "HEAD"].includes(method)) return null;
  let incoming: URL;
  let canonical: URL;
  try {
    incoming = new URL(requestUrl);
    canonical = new URL(canonicalBase);
  } catch {
    return null;
  }
  if (
    canonical.protocol !== "https:"
    || canonical.username || canonical.password
    || incoming.hostname !== legacyHostname
    || incoming.hostname === canonical.hostname
  ) return null;

  const authTransition = ["/api/auth/github/start", "/api/auth/github/callback"].includes(incoming.pathname);
  const navigation = ["/", "/login", "/story", "/access-denied", "/dashboard"].includes(incoming.pathname)
    || incoming.pathname.startsWith("/dashboard/");
  if (!authTransition && !navigation) return null;

  canonical.pathname = authTransition ? "/login" : incoming.pathname;
  canonical.search = authTransition ? "?status=domain_changed" : "";
  canonical.hash = "";
  return canonical.toString();
}
