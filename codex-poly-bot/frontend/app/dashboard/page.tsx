import { redirect } from "next/navigation";

import { ConsumerDashboard } from "@/components/dashboard/consumer-dashboard";
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

  return <ConsumerDashboard />;
}
