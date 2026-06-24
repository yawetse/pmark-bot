import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import {
  OperatorCommandCenter,
  type DashboardSummaryView,
} from "@/components/dashboard/operator-command-center";
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
  const summary = await serverDashboardApi<DashboardSummaryView>(
    "dashboard/summary",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        {summary.ok ? (
          <OperatorCommandCenter summary={summary.data} />
        ) : (
          <div className="content-grid">
            <section className="panel">
              <h1>Dashboard unavailable</h1>
              <p>{summary.message}</p>
            </section>
          </div>
        )}
      </main>
    </>
  );
}
