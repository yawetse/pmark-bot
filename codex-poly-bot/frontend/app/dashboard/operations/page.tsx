import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { OperationsView } from "@/components/dashboard/operations-view";
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

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <OperationsView />
        </div>
      </main>
    </>
  );
}
