import { NextRequest, NextResponse } from "next/server";
import { canonicalHostRedirect } from "@/lib/server/canonical-host-redirect";

export function proxy(request: NextRequest) {
  if (process.env.LEGACY_DOMAIN_REDIRECT_ENABLED !== "true") return NextResponse.next();
  // Next may normalize request.url to the internal listener address. The actual
  // Host header is used only to match the configured old host, never as a target.
  const publicRequestUrl = new URL(request.url);
  publicRequestUrl.host = request.headers.get("host") ?? publicRequestUrl.host;
  const destination = canonicalHostRedirect(
    publicRequestUrl.toString(),
    request.method,
    process.env.NEXTAUTH_URL,
    process.env.LEGACY_APPLICATION_DOMAIN_NAME,
  );
  if (!destination) return NextResponse.next();
  const response = NextResponse.redirect(destination, 302);
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export const config = {
  matcher: ["/", "/login", "/story", "/access-denied", "/dashboard/:path*", "/api/auth/github/:path*"],
};
