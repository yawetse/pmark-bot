import { NextRequest, NextResponse } from "next/server";

import { mintBackendToken } from "@/lib/server/backend-token";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-006, REQ-OBS-004

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyToBackend(request, context);
}

async function proxyToBackend(request: NextRequest, context: RouteContext): Promise<Response> {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    return NextResponse.json({ error: "authentication required" }, { status: 401 });
  }
  if (sessionCheck.status === "denied") {
    return NextResponse.json({ error: "access denied" }, { status: 403 });
  }

  const params = await context.params;
  const backendUrl = backendApiUrl(params.path, request.nextUrl.search);
  const headers = backendHeaders(request, sessionCheck.session.username);
  const body = request.method === "GET" ? undefined : await request.arrayBuffer();
  const response = await fetch(backendUrl, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders(response.headers),
  });
}

function backendApiUrl(pathParts: string[], search: string): string {
  const baseUrl = process.env.BACKEND_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_API_BASE_URL is required");
  }
  const apiPath = pathParts.map(encodeURIComponent).join("/");
  const url = new URL(`/api/${apiPath}`, baseUrl);
  url.search = search;
  return url.toString();
}

function backendHeaders(request: NextRequest, username: string): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  headers.set("Authorization", `Bearer ${mintBackendToken(username)}`);
  headers.set("X-Environment", process.env.NEXT_PUBLIC_APP_ENV ?? "local");
  if (request.method !== "GET") {
    headers.set("Origin", mutationOrigin(request));
    headers.set("X-CSRF-Token", process.env.DASHBOARD_CSRF_TOKEN ?? "");
  }
  return headers;
}

function mutationOrigin(request: NextRequest): string {
  return request.headers.get("origin") ?? process.env.NEXTAUTH_URL ?? request.nextUrl.origin;
}

function responseHeaders(source: Headers): Headers {
  const headers = new Headers();
  const contentType = source.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }
  return headers;
}
