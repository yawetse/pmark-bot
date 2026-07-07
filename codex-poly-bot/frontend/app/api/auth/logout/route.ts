import { NextResponse } from "next/server";

import { clearDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-UI-003

export async function GET() {
  return logout();
}

export async function POST() {
  return logout();
}

async function logout(): Promise<NextResponse> {
  await clearDashboardSession();
  return NextResponse.redirect(new URL("/login?status=signed_out", appUrl()), 303);
}

function appUrl(): string {
  return process.env.NEXTAUTH_URL ?? "http://127.0.0.1:3100";
}
