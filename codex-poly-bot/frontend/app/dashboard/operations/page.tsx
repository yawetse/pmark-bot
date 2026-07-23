import { redirect } from "next/navigation";

import type { EconomicsSummaryView } from "@/components/dashboard/economics-panel";
import type { MarketDataPullView } from "@/components/dashboard/market-data-panel";
import { OperationsView } from "@/components/dashboard/operations-view";
import type {
  OperationsSummaryView,
  OrderHistoryView,
} from "@/components/dashboard/operations-view";
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
  const [operations, orderHistory, marketData, economics, preferences] = await Promise.all([
    serverDashboardApi<OperationsSummaryView>(
      "operations/summary?include_details=true&include_history=true",
      sessionCheck.session.username,
    ),
    serverDashboardApi<OrderHistoryView>(
      "orders",
      sessionCheck.session.username,
    ),
    serverDashboardApi<MarketDataPullView>(
      "market-data/latest",
      sessionCheck.session.username,
    ),
    serverDashboardApi<EconomicsSummaryView>(
      "economics/summary",
      sessionCheck.session.username,
    ),
    serverDashboardApi<UserPreferencesView>(
      "preferences",
      sessionCheck.session.username,
    ),
  ]);

  return (
    <OperationsView
      summary={operations.ok ? operations.data : undefined}
      orderHistory={orderHistory.ok ? orderHistory.data : undefined}
      orderHistoryError={orderHistory.ok ? undefined : orderHistory.message}
      marketData={marketData.ok ? marketData.data : undefined}
      economics={economics.ok ? economics.data : undefined}
      loadError={operations.ok ? undefined : operations.message}
      timeZone={preferences.ok ? preferences.data.settings.timeZone : "system"}
    />
  );
}
