import "server-only";

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

import {
  DashboardSession,
  OAUTH_STATE_COOKIE_NAME,
  SESSION_COOKIE_NAME,
  SessionCheck,
} from "@/lib/session";

// REQ: REQ-UI-002, REQ-UI-003

const SESSION_TTL_SECONDS = 60 * 60 * 8;
const OAUTH_STATE_TTL_SECONDS = 10 * 60;

export async function getDashboardSession(): Promise<SessionCheck> {
  const cookieStore = await cookies();
  const raw = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  const session = raw ? verifySessionCookie(raw) : null;
  if (!session) {
    return { status: "missing" };
  }
  if (!allowedUsers().has(session.username.toLowerCase())) {
    return { status: "denied", username: session.username };
  }
  return { status: "ok", session };
}

export async function createOAuthState(): Promise<string> {
  const state = randomBytes(24).toString("base64url");
  const cookieStore = await cookies();
  cookieStore.set(OAUTH_STATE_COOKIE_NAME, state, {
    httpOnly: true,
    maxAge: OAUTH_STATE_TTL_SECONDS,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
  return state;
}

export async function validateOAuthState(value: string | null): Promise<boolean> {
  const cookieStore = await cookies();
  const expected = cookieStore.get(OAUTH_STATE_COOKIE_NAME)?.value;
  cookieStore.delete(OAUTH_STATE_COOKIE_NAME);
  if (!expected || !value) {
    return false;
  }
  return safeEqual(expected, value);
}

export async function setDashboardSession(username: string): Promise<void> {
  const session: DashboardSession = {
    username,
    issuedAt: Math.floor(Date.now() / 1000),
  };
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE_NAME, signSession(session), {
    httpOnly: true,
    maxAge: SESSION_TTL_SECONDS,
    path: "/",
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
  });
}

export function allowedUsers(): Set<string> {
  return new Set(
    (process.env.DASHBOARD_ALLOWED_USERS ?? "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  );
}

function signSession(session: DashboardSession): string {
  const body = Buffer.from(JSON.stringify(session)).toString("base64url");
  return `${body}.${sign(body)}`;
}

function verifySessionCookie(raw: string): DashboardSession | null {
  const [body, signature] = raw.split(".");
  if (!body || !signature || !safeEqual(signature, sign(body))) {
    return null;
  }
  try {
    const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as DashboardSession;
    if (!parsed.username || !parsed.issuedAt) {
      return null;
    }
    const ageSeconds = Math.floor(Date.now() / 1000) - parsed.issuedAt;
    return ageSeconds > SESSION_TTL_SECONDS ? null : parsed;
  } catch {
    return null;
  }
}

function sign(body: string): string {
  return createHmac("sha256", sessionSecret()).update(body).digest("base64url");
}

function sessionSecret(): string {
  const secret = process.env.DASHBOARD_SESSION_SECRET ?? process.env.BACKEND_TOKEN_SIGNING_SECRET;
  if (!secret) {
    throw new Error("DASHBOARD_SESSION_SECRET or BACKEND_TOKEN_SIGNING_SECRET is required");
  }
  return secret;
}

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}
