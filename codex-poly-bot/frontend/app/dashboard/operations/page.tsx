import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import type { EconomicsSummaryView } from "@/components/dashboard/economics-panel";
import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import { OperationsView } from "@/components/dashboard/operations-view";
import type { OperationsSummaryView } from "@/components/dashboard/operations-view";
import type { UserPreferencesView } from "@/components/dashboard/preferences-panel";
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
  const marketData = await serverDashboardApi<MarketDataPullView>(
    "market-data/latest",
    sessionCheck.session.username,
  );
  const economics = await serverDashboardApi<EconomicsSummaryView>(
    "economics/summary",
    sessionCheck.session.username,
  );
  const preferences = await serverDashboardApi<UserPreferencesView>(
    "preferences",
    sessionCheck.session.username,
  );

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <OperationsView
          summary={operations.ok ? operations.data : undefined}
          marketData={marketData.ok ? marketData.data : undefined}
          economics={economics.ok ? economics.data : undefined}
          loadError={operations.ok ? undefined : operations.message}
          timeZone={preferences.ok ? preferences.data.settings.timeZone : "system"}
        />
      </main>
    </>
  );
}
