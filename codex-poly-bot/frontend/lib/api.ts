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
    return text;
  }
}
