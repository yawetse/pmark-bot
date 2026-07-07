"use client";

import { LogOut } from "lucide-react";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-005

export function LogoutControl({ username }: { username: string }) {
  return (
    <form action="/api/auth/logout" className="logout-control" method="post">
      <div>
        <span>Signed in as</span>
        <strong>{username}</strong>
      </div>
      <button className="button danger" type="submit">
        <LogOut aria-hidden="true" size={15} strokeWidth={2.3} />
        <span>Log out</span>
      </button>
    </form>
  );
}
