import "server-only";

import { mintBackendToken } from "@/lib/server/backend-token";

// REQ: REQ-UI-002, REQ-UI-004, REQ-OBS-005

export type ServerDashboardApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

export async function serverDashboardApi<T>(
  path: string,
  username: string,
): Promise<ServerDashboardApiResult<T>> {
  const response = await fetch(backendApiUrl(path), {
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${mintBackendToken(username)}`,
      "X-Environment": process.env.NEXT_PUBLIC_APP_ENV ?? "local",
    },
  });
  if (!response.ok) {
    return { ok: false, status: response.status, message: await response.text() };
  }
  return { ok: true, data: (await response.json()) as T };
}

function backendApiUrl(path: string): string {
  const baseUrl = process.env.BACKEND_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_API_BASE_URL is required");
  }
  return new URL(`/api/${path.replace(/^\/+/, "")}`, baseUrl).toString();
}
