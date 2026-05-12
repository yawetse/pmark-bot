import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { StatusOverview } from "@/components/dashboard/status-overview";
import { WalletStatus } from "@/components/dashboard/wallet-status";
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

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <StatusOverview />
          <WalletStatus />
        </div>
      </main>
    </>
  );
}
