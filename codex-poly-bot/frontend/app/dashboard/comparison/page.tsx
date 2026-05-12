import { redirect } from "next/navigation";

import { ComparisonView } from "@/components/dashboard/comparison-view";
import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-011, REQ-CMP-002, REQ-CMP-003, REQ-CMP-004

export default async function ComparisonPage() {
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
          <ComparisonView />
        </div>
      </main>
    </>
  );
}
