import { redirect } from "next/navigation";

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
          <StatusOverview />
          <WalletStatus />
        </div>
      </main>
    </>
  );
}
