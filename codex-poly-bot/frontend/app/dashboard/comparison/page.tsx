import { redirect } from "next/navigation";

import {
  ComparisonView,
  type ComparisonSummaryView,
} from "@/components/dashboard/comparison-view";
import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

export default async function ComparisonPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }
  const comparison = await serverDashboardApi<ComparisonSummaryView>(
    "comparison",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <ComparisonView
          summary={comparison.ok ? comparison.data : undefined}
          loadError={comparison.ok ? undefined : comparison.message}
        />
      </main>
    </>
  );
}
