// REQ: REQ-UI-002, REQ-UI-003

export const SESSION_COOKIE_NAME = "codex_poly_bot_session";
export const OAUTH_STATE_COOKIE_NAME = "codex_poly_bot_oauth_state";

export type DashboardSession = {
  username: string;
  issuedAt: number;
};

export type SessionCheck =
  | { status: "ok"; session: DashboardSession }
  | { status: "missing" }
  | { status: "denied"; username: string };
