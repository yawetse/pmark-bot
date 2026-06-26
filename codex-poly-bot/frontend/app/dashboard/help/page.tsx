import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { HelpAboutView } from "@/components/dashboard/help-about-view";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-004, REQ-DEP-001, REQ-DEP-002, REQ-WAL-003

export default async function HelpPage() {
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
      <main className="page-shell" id="dashboard-main" tabIndex={-1}>
        <HelpAboutView />
      </main>
    </>
  );
}
