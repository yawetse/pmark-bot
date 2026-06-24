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
            <h2>Versioning</h2>
            <p>Config saves use an expected version and apply on the next trading loop.</p>
          </section>
        </div>
      </main>
    </>
  );
}
