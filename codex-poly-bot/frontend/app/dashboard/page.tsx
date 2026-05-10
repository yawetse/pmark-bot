import { redirect } from "next/navigation";

import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-004

export default async function DashboardPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">codex-poly-bot</div>
        <nav className="nav" aria-label="Dashboard">
          <a href="/dashboard">Status</a>
          <a href="/dashboard/config">Config</a>
          <a href="/dashboard/system">System</a>
        </nav>
      </header>
      <main className="page-shell">
        <div className="content-grid">
          <section className="panel">
            <h1>Dashboard</h1>
            <p>
              Signed in as {sessionCheck.session.username}. System access is active for
              dashboard views and control requests.
            </p>
            <ul className="status-list">
              <li>
                GitHub session <span className="status ok">valid</span>
              </li>
              <li>
                Backend token <span className="status ok">server only</span>
              </li>
              <li>
                Browser secret access <span className="status blocked">blocked</span>
              </li>
            </ul>
          </section>
          <section className="panel">
            <h2>Access</h2>
            <p>
              Session and control-plane checks are active for this dashboard session.
            </p>
          </section>
        </div>
      </main>
    </>
  );
}
