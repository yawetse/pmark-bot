import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import type { DashboardSummaryView } from "@/components/dashboard/operator-command-center";
import { StatusOverview } from "@/components/dashboard/status-overview";
import { WalletStatus } from "@/components/dashboard/wallet-status";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-004, REQ-UI-009, REQ-OBS-005

export default async function SystemPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }
  const summary = await serverDashboardApi<DashboardSummaryView>(
    "dashboard/summary",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <StatusOverview items={summary.ok ? summary.data.status.items : undefined} />
          <WalletStatus credentials={summary.ok ? summary.data.wallet.credentials : undefined} />
          {summary.ok ? null : (
            <section className="panel">
              <h2>System API</h2>
              <p>{summary.message}</p>
            </section>
          )}
        </div>
      </main>
    </>
  );
}
