import { NextResponse } from "next/server";

import { createOAuthState } from "@/lib/server/session";

// REQ: REQ-UI-002

export async function GET() {
  const clientId = process.env.GITHUB_CLIENT_ID;
  if (!clientId) {
    return NextResponse.redirect(new URL("/login?error=github_client_id_missing", appUrl()));
  }

  const state = await createOAuthState();
  const url = new URL("https://github.com/login/oauth/authorize");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", `${appUrl()}/api/auth/github/callback`);
  url.searchParams.set("scope", "read:user");
  url.searchParams.set("state", state);
  return NextResponse.redirect(url);
}

function appUrl(): string {
  return process.env.NEXTAUTH_URL ?? "http://localhost:3000";
}
