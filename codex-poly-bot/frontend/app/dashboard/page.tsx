import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { StatusOverview } from "@/components/dashboard/status-overview";
import { WalletStatus } from "@/components/dashboard/wallet-status";
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
          <StatusOverview />
          <WalletStatus />
        </div>
      </main>
    </>
  );
}
