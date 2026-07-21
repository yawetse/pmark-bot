import { redirect } from "next/navigation";

import { OverviewDashboard } from "@/components/dashboard/overview-dashboard";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-002, REQ-UI-003, REQ-UI-004, REQ-UI-017, REQ-UI-019

export default async function DashboardPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  return <OverviewDashboard />;
}
