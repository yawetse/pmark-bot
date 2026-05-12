import { notFound, redirect } from "next/navigation";

import { DashboardNav } from "@/components/dashboard/dashboard-nav";
import { ModelProviderName, ModelSummaryPanel } from "@/components/dashboard/model-summary";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-010

type ModelPageProps = {
  params: Promise<{ provider: string }>;
};

export default async function ModelPage({ params }: ModelPageProps) {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  const { provider } = await params;
  if (!isModelProvider(provider)) {
    notFound();
  }

  return (
    <>
      <DashboardNav />
      <main className="page-shell">
        <div className="content-grid">
          <ModelSummaryPanel provider={provider} />
        </div>
      </main>
    </>
  );
}

function isModelProvider(value: string): value is ModelProviderName {
  return value === "claude" || value === "openai";
}
