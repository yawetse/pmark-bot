import { notFound, redirect } from "next/navigation";

import {
  ModelProviderName,
  ModelSummaryPanel,
  type ModelSummary,
} from "@/components/dashboard/model-summary";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
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
  const summary = await serverDashboardApi<ModelSummary>(
    `models/${provider}/summary`,
    sessionCheck.session.username,
  );

  return (
    <ModelSummaryPanel
      provider={provider}
      summary={summary.ok ? summary.data : undefined}
      loadError={summary.ok ? undefined : summary.message}
    />
  );
}

function isModelProvider(value: string): value is ModelProviderName {
  return value === "claude" || value === "openai";
}
