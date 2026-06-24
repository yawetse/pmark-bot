import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { ConfigControls } from "@/components/dashboard/config-controls";
import type { ConfigSnapshot } from "@/components/dashboard/config-controls";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
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
  const currentConfig = await serverDashboardApi<ConfigSnapshot>(
    "config/current",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <ConfigControls
            initialSnapshot={currentConfig.ok ? currentConfig.data : undefined}
            loadError={currentConfig.ok ? undefined : currentConfig.message}
          />
          <section className="panel">
            <p className="section-label">Change safety</p>
            <h2>How changes apply</h2>
            <ul className="status-list">
              <li>
                <span>Version check</span>
                <span>Each save uses the current version to avoid overwriting another change.</span>
              </li>
              <li>
                <span>Apply timing</span>
                <span>Saved values apply on the next trading loop, not midway through a decision.</span>
              </li>
              <li>
                <span>Live trading</span>
                <span>Changing live mode still requires venue, credential, risk, and data gates to pass.</span>
              </li>
              <li>
                <span>Risk settings</span>
                <span>Position size, daily loss, open positions, and slippage can block orders.</span>
              </li>
            </ul>
          </section>
        </div>
      </main>
    </>
  );
}
