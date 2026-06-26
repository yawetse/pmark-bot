import { NextResponse } from "next/server";

import { frontendTelemetryConfig } from "@/lib/server/signoz";

// REQ: REQ-OBS-001, REQ-OBS-002

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(frontendTelemetryConfig(), {
    headers: {
      "Cache-Control": "no-store",
    },
  });
}
