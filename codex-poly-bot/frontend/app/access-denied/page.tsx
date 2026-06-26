// REQ: REQ-UI-003

import Link from "next/link";

export default function AccessDeniedPage() {
  return (
    <main className="page-shell auth-shell">
      <section className="panel auth-panel">
        <p className="section-label">Operator access</p>
        <h1>Access Denied</h1>
        <p className="panel-note">Your GitHub account is not on the dashboard allowlist.</p>
        <Link className="button" href="/login">
          Return to sign in
        </Link>
      </section>
    </main>
  );
}
