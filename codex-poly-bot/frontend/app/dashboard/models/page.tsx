import { redirect } from "next/navigation";

import {
  ModelsWorkspace,
  type ModelProviderName,
  type ModelSummary,
  type ModelWorkspaceProvider,
} from "@/components/dashboard/model-summary";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-010

const MODEL_PROVIDERS: ModelProviderName[] = ["claude", "openai"];

export default async function ModelsPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }

  const providerResults = await Promise.all(
    MODEL_PROVIDERS.map(async (provider): Promise<ModelWorkspaceProvider> => {
      const summary = await serverDashboardApi<ModelSummary>(
        `models/${provider}/summary`,
        sessionCheck.session.username,
      );
      return {
        provider,
        summary: summary.ok ? summary.data : undefined,
        loadError: summary.ok ? undefined : summary.message,
      };
    }),
  );

  return (
    <ModelsWorkspace providers={providerResults} />
  );
}
