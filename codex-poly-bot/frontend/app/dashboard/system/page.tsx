import { redirect } from "next/navigation";

import type { DashboardSummaryView } from "@/components/dashboard/operator-command-center";
import { SystemReadinessView } from "@/components/dashboard/system-readiness-view";
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
    "dashboard/readiness",
    sessionCheck.session.username,
  );

  return (
    <SystemReadinessView
      summary={summary.ok ? summary.data : undefined}
      loadError={summary.ok ? undefined : summary.message}
    />
  );
}
