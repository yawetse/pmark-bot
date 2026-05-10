import { NextRequest, NextResponse } from "next/server";

import { allowedUsers, setDashboardSession, validateOAuthState } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-UI-003, REQ-OBS-004

export async function GET(request: NextRequest) {
  const stateValid = await validateOAuthState(request.nextUrl.searchParams.get("state"));
  if (!stateValid) {
    return NextResponse.redirect(new URL("/login?error=invalid_oauth_state", appUrl()));
  }

  const username = await resolveGitHubUsername(request);
  if (!username) {
    return NextResponse.redirect(new URL("/login?error=github_oauth_failed", appUrl()));
  }
  if (!allowedUsers().has(username.toLowerCase())) {
    return NextResponse.redirect(new URL("/access-denied", appUrl()));
  }

  await setDashboardSession(username);
  return NextResponse.redirect(new URL("/dashboard", appUrl()));
}

async function resolveGitHubUsername(request: NextRequest): Promise<string | null> {
  const localLogin = request.nextUrl.searchParams.get("login");
  if (localLogin && process.env.ALLOW_LOCAL_AUTH_BYPASS === "true" && process.env.NODE_ENV !== "production") {
    return localLogin;
  }

  const code = request.nextUrl.searchParams.get("code");
  const clientId = process.env.GITHUB_CLIENT_ID;
  const clientSecret = process.env.GITHUB_CLIENT_SECRET;
  if (!code || !clientId || !clientSecret) {
    return null;
  }

  const tokenResponse = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      client_id: clientId,
      client_secret: clientSecret,
      code,
    }),
  });
  if (!tokenResponse.ok) {
    return null;
  }
  const tokenPayload = (await tokenResponse.json()) as { access_token?: string };
  if (!tokenPayload.access_token) {
    return null;
  }

  const userResponse = await fetch("https://api.github.com/user", {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${tokenPayload.access_token}`,
    },
  });
  if (!userResponse.ok) {
    return null;
  }
  const userPayload = (await userResponse.json()) as { login?: string };
  return userPayload.login ?? null;
}

function appUrl(): string {
  return process.env.NEXTAUTH_URL ?? "http://localhost:3000";
}
