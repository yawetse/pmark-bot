import "server-only";

import { mintBackendToken } from "@/lib/server/backend-token";

// REQ: REQ-UI-002, REQ-UI-004, REQ-OBS-005

const BACKEND_READ_TIMEOUT_MS = 25_000;

export type ServerDashboardApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

export async function serverDashboardApi<T>(
  path: string,
  username: string,
): Promise<ServerDashboardApiResult<T>> {
  const timeout = createTimeout(BACKEND_READ_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(backendApiUrl(path), {
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${mintBackendToken(username)}`,
        "X-Environment": process.env.NEXT_PUBLIC_APP_ENV ?? "local",
      },
      signal: timeout.signal,
    });
  } catch (error) {
    const timedOut = isAbortError(error);
    return {
      ok: false,
      status: timedOut ? 504 : 502,
      message: timedOut
        ? "The backend gateway timed out, so the request did not complete."
        : "The backend gateway returned 502, so the request did not complete.",
    };
  } finally {
    timeout.cancel();
  }
  if (!response.ok) {
    return { ok: false, status: response.status, message: await response.text() };
  }
  return { ok: true, data: (await response.json()) as T };
}

function createTimeout(timeoutMs: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => clearTimeout(timeoutId),
  };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function backendApiUrl(path: string): string {
  const baseUrl = process.env.BACKEND_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_API_BASE_URL is required");
  }
  return new URL(`/api/${path.replace(/^\/+/, "")}`, baseUrl).toString();
}
