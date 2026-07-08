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
    return { ok: false, status: response.status, message: await errorMessage(response) };
  }
  return { ok: true, data: (await response.json()) as T };
}

async function errorMessage(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `Request failed with status ${response.status}.`;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/html") || looksLikeHtml(text)) {
    return gatewayErrorMessage(response.status);
  }
  try {
    const parsed = JSON.parse(text) as {
      detail?: { message?: string } | string;
      message?: string;
      error?: string;
    };
    if (typeof parsed.detail === "object" && parsed.detail?.message) {
      return parsed.detail.message;
    }
    if (typeof parsed.detail === "string") {
      return parsed.detail;
    }
    return parsed.message ?? parsed.error ?? text;
  } catch {
    return text.length > 260 ? gatewayErrorMessage(response.status) : text;
  }
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

function looksLikeHtml(value: string): boolean {
  return /<html[\s>]/i.test(value) || /<h1>\s*\d{3}\s+/i.test(value);
}

function gatewayErrorMessage(status: number): string {
  if (status === 502 || status === 503 || status === 504) {
    return `The backend gateway returned ${status}, so the request did not complete. Check backend health and try again.`;
  }
  return `Request failed with status ${status}.`;
}

function backendApiUrl(path: string): string {
  const baseUrl = process.env.BACKEND_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) {
    throw new Error("BACKEND_API_BASE_URL is required");
  }
  return new URL(`/api/${path.replace(/^\/+/, "")}`, baseUrl).toString();
}
