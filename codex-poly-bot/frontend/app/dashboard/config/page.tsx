import { redirect } from "next/navigation";

import { ConfigControls } from "@/components/dashboard/config-controls";
import type { ConfigSnapshot } from "@/components/dashboard/config-controls";
import { PageHeader } from "@/components/dashboard/dashboard-primitives";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007

export default async function ConfigPage() {
  const sessionCheck = await getDashboardSession();
  if (sessionCheck.status === "missing") {
    redirect("/login");
  }
  if (sessionCheck.status === "denied") {
    redirect("/access-denied");
  }
  const currentConfig = await serverDashboardApi<ConfigSnapshot>(
    "config/current",
    sessionCheck.session.username,
  );

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Settings"
        title="Trading preferences"
        body="Change how the app scans markets, asks models, applies risk limits, and sends alerts. Saved values apply on the next trading loop."
      />
      <div className="content-grid config-content-grid">
        <ConfigControls
          initialSnapshot={currentConfig.ok ? currentConfig.data : undefined}
          loadError={currentConfig.ok ? undefined : currentConfig.message}
        />
        <section className="panel">
          <p className="section-label">Change safety</p>
          <h2>What happens after save</h2>
          <ul className="status-list safety-status-list">
            <li>
              <span>Saved scope</span>
              <span>Trading settings are saved in the database for your dashboard user and environment.</span>
            </li>
            <li>
              <span>Version check</span>
              <span>The app checks the active config version so one save does not overwrite another.</span>
            </li>
            <li>
              <span>Apply timing</span>
              <span>Saved values apply on the next loop. The app does not change a decision midway through a run.</span>
            </li>
            <li>
              <span>Live trading</span>
              <span>Live mode only permits orders. Venue, credential, risk, and emergency-stop checks still decide whether an order can go out.</span>
            </li>
            <li>
              <span>Risk settings</span>
              <span>Position size, daily loss, open positions, allocation, and slippage can still block a trade.</span>
            </li>
            <li>
              <span>Advanced editor</span>
              <span>Use the path editor only when a setting is not shown in the main preference list.</span>
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
