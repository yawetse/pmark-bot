import { redirect } from "next/navigation";

import { ConfigControls } from "@/components/dashboard/config-controls";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007

export default async function ConfigPage() {
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
          <ConfigControls />
          <section className="panel">
            <h2>Versioning</h2>
            <p>Config saves use an expected version and apply on the next trading loop.</p>
          </section>
        </div>
      </main>
    </>
  );
}
