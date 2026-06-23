import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { StatusOverview } from "@/components/dashboard/status-overview";
import type { StatusItem } from "@/components/dashboard/status-overview";
import { WalletStatus } from "@/components/dashboard/wallet-status";
import type { WalletCredentialView } from "@/components/dashboard/wallet-status";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
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
  const summary = await serverDashboardApi<DashboardSummary>(
    "dashboard/summary",
    sessionCheck.session.username,
  );
  const statusItems = summary.ok ? summary.data.status.items : undefined;
  const credentials = summary.ok ? summary.data.wallet.credentials : undefined;

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <section className="panel">
            <h1>Dashboard</h1>
            <p>
              Signed in as {sessionCheck.session.username}. System access is active for
              dashboard views and control requests.
            </p>
          </section>
          <StatusOverview items={statusItems} />
          <WalletStatus credentials={credentials} />
        </div>
      </main>
    </>
  );
}

type DashboardSummary = {
  status: {
    items: StatusItem[];
  };
  wallet: {
    credentials: WalletCredentialView[];
  };
};
