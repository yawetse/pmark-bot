import { redirect } from "next/navigation";

import { ConsumerDashboard } from "@/components/dashboard/consumer-dashboard";
import type { DashboardSummaryView } from "@/components/dashboard/operator-command-center";
import type { TickSummaryView } from "@/components/dashboard/tick-summary-panel";
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
  const [summary, dailySummary] = await Promise.all([
    serverDashboardApi<DashboardSummaryView>(
      "dashboard/summary",
      sessionCheck.session.username,
    ),
    serverDashboardApi<TickSummaryView>(
      "operations/tick-summary?window_minutes=1440",
      sessionCheck.session.username,
    ),
  ]);

  return (
    summary.ok ? (
      <ConsumerDashboard
        summary={summary.data}
        dailySummary={dailySummary.ok ? dailySummary.data : undefined}
        dailySummaryError={dailySummary.ok ? undefined : dailySummary.message}
      />
    ) : (
      <div className="content-grid">
        <section className="panel">
          <h1>Dashboard unavailable</h1>
          <p>{summary.message}</p>
        </section>
      </div>
    )
  );
}
