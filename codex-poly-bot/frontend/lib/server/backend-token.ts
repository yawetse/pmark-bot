import "server-only";

import { createHmac } from "node:crypto";

// REQ: REQ-UI-002, REQ-UI-006, REQ-OBS-004

export type BackendTokenClaims = {
  username: string;
  exp: number;
};

export function mintBackendToken(username: string, now: Date = new Date()): string {
  const ttlSeconds = Number(process.env.BACKEND_TOKEN_TTL_SECONDS ?? "300");
  const claims: BackendTokenClaims = {
    exp: Math.floor(now.getTime() / 1000) + ttlSeconds,
    username,
  };
  const body = base64url(JSON.stringify(claims));
  const signature = sign(body);
  return `${body}.${signature}`;
}

function sign(body: string): string {
  return createHmac("sha256", backendTokenSecret()).update(body).digest("base64url");
}

function backendTokenSecret(): string {
  const secret = process.env.BACKEND_TOKEN_SIGNING_SECRET;
  if (!secret) {
    throw new Error("BACKEND_TOKEN_SIGNING_SECRET is required");
  }
  return secret;
}

function base64url(value: string): string {
  return Buffer.from(value).toString("base64url");
}
