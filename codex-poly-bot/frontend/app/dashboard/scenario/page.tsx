import { redirect } from "next/navigation";

import { ScenarioView } from "@/components/dashboard/scenario-view";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-004, REQ-UI-008, REQ-DAT-008, REQ-OBS-005

export default async function ScenarioPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  return <ScenarioView />;
}
