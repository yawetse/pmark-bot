import { NextRequest, NextResponse } from "next/server";

import {
  isTrustedTelemetryOrigin,
  signozHeaders,
  signozSignalEndpoint,
  signozTelemetryEnabled,
  type SignozSignal,
} from "@/lib/server/signoz";

// REQ: REQ-OBS-001, REQ-OBS-002

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = {
  params: Promise<{ signal: string }>;
};

export async function POST(request: NextRequest, context: RouteContext) {
  if (!signozTelemetryEnabled()) {
    return NextResponse.json({ error: "telemetry disabled" }, { status: 404 });
  }
  if (!isTrustedTelemetryOrigin(request)) {
    return NextResponse.json({ error: "origin not trusted" }, { status: 403 });
  }

  const { signal } = await context.params;
  if (!isSignozSignal(signal)) {
    return NextResponse.json({ error: "unsupported telemetry signal" }, { status: 404 });
  }

  const upstreamUrl = signozSignalEndpoint(signal);
  if (!upstreamUrl) {
    return NextResponse.json({ error: "telemetry endpoint missing" }, { status: 503 });
  }

  const upstreamResponse = await fetch(upstreamUrl, {
    method: "POST",
    headers: {
      "Content-Type": request.headers.get("content-type") ?? "application/x-protobuf",
      ...signozHeaders(),
    },
    body: await request.arrayBuffer(),
    cache: "no-store",
  });

  const responseBody = await upstreamResponse.arrayBuffer();
  return new Response(responseBody, {
    status: upstreamResponse.status,
    headers: responseHeaders(upstreamResponse.headers),
  });
}

function isSignozSignal(value: string): value is SignozSignal {
  return value === "traces" || value === "logs";
}

function responseHeaders(source: Headers): Headers {
  const headers = new Headers();
  const contentType = source.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  return headers;
}
