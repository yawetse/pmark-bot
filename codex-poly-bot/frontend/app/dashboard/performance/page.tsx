import { redirect } from "next/navigation";

import { PerformanceView } from "@/components/dashboard/performance-view";
import type { VenuePortfolioView } from "@/components/dashboard/venue-portfolio-panel";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-013, REQ-UI-016, REQ-UI-021, REQ-CMP-004, REQ-CMP-005

export default async function PerformancePage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") redirect("/login");
  if (sessionCheck.status === "denied") redirect("/access-denied");
  const portfolio = await serverDashboardApi<VenuePortfolioView>(
    "portfolio",
    sessionCheck.session.username,
  );
  return (
    <PerformanceView
      loadError={portfolio.ok ? undefined : portfolio.message}
      portfolio={portfolio.ok ? portfolio.data : undefined}
    />
  );
}
