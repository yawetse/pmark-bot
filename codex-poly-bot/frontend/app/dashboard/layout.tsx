import type { ReactNode } from "react";
import { redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-010, REQ-UI-011

export default async function DashboardLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
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
        {children}
      </main>
    </>
  );
}
