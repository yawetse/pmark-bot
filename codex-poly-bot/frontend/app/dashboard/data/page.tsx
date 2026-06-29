import { redirect } from "next/navigation";

import { DataExplorerView } from "@/components/dashboard/data-explorer-view";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-004, REQ-DAT-008, REQ-OBS-005

export default async function DataPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  return <DataExplorerView />;
}
