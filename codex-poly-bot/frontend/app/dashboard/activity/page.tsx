import { redirect } from "next/navigation";

import { ActivityView } from "@/components/dashboard/activity-view";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-016, REQ-UI-020, REQ-UI-025

export default async function ActivityPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") redirect("/login");
  if (sessionCheck.status === "denied") redirect("/access-denied");

  const operations = await serverDashboardApi<OperationsSummaryView>(
    "operations/summary",
    sessionCheck.session.username,
  );
  return (
    <ActivityView
      initialErrors={operations.ok ? [] : [operations.message]}
      summary={operations.ok ? operations.data : undefined}
    />
  );
}
