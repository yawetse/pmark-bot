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
      message: await response.text(),
    };
  }
  return { ok: true, data: (await response.json()) as T };
}
