import { NextResponse } from "next/server";

import { mintBackendToken } from "@/lib/server/backend-token";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-OBS-005

export const runtime = "nodejs";

export async function GET() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    return NextResponse.json({ error: "authentication required" }, { status: 401 });
  }
  if (sessionCheck.status === "denied") {
    return NextResponse.json({ error: "access denied" }, { status: 403 });
  }

  return NextResponse.json({
    token: mintBackendToken(sessionCheck.session.username),
    environment: process.env.NEXT_PUBLIC_APP_ENV ?? "local",
    websocketUrl: backendWebSocketUrl(),
  });
}

function backendWebSocketUrl(): string {
  const baseUrl =
    process.env.BACKEND_WS_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.BACKEND_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_API_BASE_URL is required");
  }
  const url = new URL("/api/dashboard/events", baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
