import { redirect } from "next/navigation";
import Link from "next/link";
import { ArrowRight, ShieldAlert, Workflow } from "lucide-react";

import type { ConfigSnapshot } from "@/components/dashboard/config-controls";
import { ConfigWorkspace } from "@/components/dashboard/config-workspace";
import { PageHeader } from "@/components/dashboard/dashboard-primitives";
import { LogoutControl } from "@/components/dashboard/logout-control";
import { serverDashboardApi } from "@/lib/server/dashboard-api";
import { getDashboardSession } from "@/lib/server/session";

// REQ: REQ-UI-005, REQ-UI-006, REQ-UI-007, REQ-UI-008, REQ-UI-016, REQ-UI-022

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
    <div className="page-stack settings-page">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        body="Change the rules used most. Advanced controls remain available when you need them, and every saved value is versioned and audited."
      />
      <div className="content-grid config-content-grid">
        <ConfigWorkspace
          initialSnapshot={currentConfig.ok ? currentConfig.data : undefined}
          loadError={currentConfig.ok ? undefined : currentConfig.message}
        />
        <div className="settings-side-stack">
          <section className="panel account-settings-panel">
            <p className="section-label">Account</p>
            <h2>Session</h2>
            <p>End this dashboard session on the current browser.</p>
            <LogoutControl username={sessionCheck.session.username} />
          </section>
          <section className="panel settings-safety-card">
            <ShieldAlert aria-hidden="true" size={22} />
            <p className="section-label">Safety control</p>
            <h2>Emergency stop</h2>
            <p>Stop or review live order handling from the detailed Operations page.</p>
            <Link className="button danger-button" href="/dashboard/operations">Open emergency stop <ArrowRight aria-hidden="true" size={15} /></Link>
          </section>
          <section className="panel settings-context-card">
            <Workflow aria-hidden="true" size={22} />
            <p className="section-label">Before saving</p>
            <h2>Test a change</h2>
            <p>Use What-if to review a proposed setting without changing the active version.</p>
            <Link className="button subtle" href="/dashboard/scenario">Test settings with What-if <ArrowRight aria-hidden="true" size={15} /></Link>
          </section>
        </div>
      </div>
    </div>
  );
}
