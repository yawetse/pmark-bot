import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { OperationsView } from "@/components/dashboard/operations-view";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-008, REQ-EXE-014, REQ-EXE-015, REQ-EXE-016, REQ-OBS-005

export default async function OperationsPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }
  const operations = await serverDashboardApi<OperationsSummaryView>(
    "operations/summary",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <OperationsView
          summary={operations.ok ? operations.data : undefined}
          loadError={operations.ok ? undefined : operations.message}
        />
      </main>
    </>
  );
}
