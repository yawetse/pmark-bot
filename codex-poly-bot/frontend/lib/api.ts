// REQ: REQ-UI-001, REQ-UI-002, REQ-UI-006

export type ApiClientResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; message: string };

export async function dashboardApi<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiClientResult<T>> {
  const response = await fetch(`/dashboard-api/${path.replace(/^\/+/, "")}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      message: await errorMessage(response),
    };
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
    if ("error_code" in parsed && parsed.error_code === "config_version_conflict") {
      return text;
    }
    return parsed.message ?? parsed.error ?? text;
  } catch {
    return text.length > 260 ? gatewayErrorMessage(response.status) : text;
  }
}

function looksLikeHtml(value: string): boolean {
  return /<html[\s>]/i.test(value) || /<h1>\s*\d{3}\s+/i.test(value);
}

function gatewayErrorMessage(status: number): string {
  if (status === 502) {
    return "The backend gateway returned 502, so the settings were not saved. Check backend health and try Apply again.";
  }
  if (status === 503 || status === 504) {
    return `The backend gateway returned ${status}, so the request did not complete. Check backend health and try again.`;
  }
  return `Request failed with status ${status}.`;
}
