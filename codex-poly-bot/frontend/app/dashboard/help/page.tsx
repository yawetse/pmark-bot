import { redirect } from "next/navigation";

import { HelpAboutView } from "@/components/dashboard/help-about-view";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-016, REQ-UI-023

export default async function HelpPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  return <HelpAboutView />;
}
