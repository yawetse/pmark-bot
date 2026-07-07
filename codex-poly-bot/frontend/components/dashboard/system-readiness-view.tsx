"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  Clock3,
  KeyRound,
  ShieldCheck,
  WalletCards,
} from "lucide-react";

import {
  EmptyState,
  Message,
  MetricCard,
  MetricGrid,
  PageHeader,
  Panel,
  StatusChip,
} from "@/components/dashboard/dashboard-primitives";
import {
  DEFAULT_STATUS_ITEMS,
  type StatusItem,
} from "@/components/dashboard/status-overview";
import {
  DEFAULT_WALLET_CREDENTIALS,
  type WalletCredentialView,
} from "@/components/dashboard/wallet-status";
import type { DashboardSummaryView } from "@/components/dashboard/operator-command-center";

// REQ: REQ-UI-004, REQ-UI-009, REQ-OBS-005, REQ-WAL-005

type SystemAction = {
  title: string;
  body: string;
  href?: string;
  label?: string;
};

export function SystemReadinessView({
  summary,
  loadError,
}: {
  summary?: DashboardSummaryView;
  loadError?: string;
}) {
  const statusItems = summary?.status.items ?? DEFAULT_STATUS_ITEMS;
  const credentials = summary?.wallet.credentials ?? DEFAULT_WALLET_CREDENTIALS;
  const blockedItems = statusItems.filter((item) => item.state === "blocked");
  const missingRequiredCredentials = credentials.filter(
    (credential) => credential.requiredForLive !== false && !credential.present,
  );
  const liveEnabled = Boolean(summary?.config.settings.live_enabled);
  const killSwitchActive = Boolean(summary?.status.kill_switch_active);
  const notificationState = summary?.notifications?.state ?? "unknown";
  const workerState =
    summary?.status.worker?.state ??
    summary?.status.worker?.value ??
    "unknown";
  const modeTone = resolveSystemTone({
    blockedCount: blockedItems.length + missingRequiredCredentials.length,
    killSwitchActive,
    liveEnabled,
  });
  const modeLabel = resolveSystemLabel({
    blockedCount: blockedItems.length + missingRequiredCredentials.length,
    killSwitchActive,
    liveEnabled,
  });
  const actions = buildSystemActions({
    blockedItems,
    credentials: missingRequiredCredentials,
    killSwitchActive,
    notificationState,
  });

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="System"
        title="Readiness"
        body="Check whether the app, accounts, credentials, notifications, and worker state are ready before relying on the next trading loop."
      >
        <StatusChip tone={modeTone}>{modeLabel}</StatusChip>
      </PageHeader>

      {loadError ? (
        <Message tone="blocked">
          {formatLoadError(loadError)}
        </Message>
      ) : null}

      <MetricGrid compact>
        <MetricCard
          label="Environment"
          value={summary?.environment ?? "unknown"}
          detail={`Health: ${summary?.status.health ?? "unknown"}`}
        />
        <MetricCard
          label="Blockers"
          value={String(blockedItems.length)}
          detail={blockedItems[0]?.label ?? "No readiness blocker"}
        />
        <MetricCard
          label="Missing credentials"
          value={String(missingRequiredCredentials.length)}
          detail={
            missingRequiredCredentials[0]
              ? `${formatLabel(missingRequiredCredentials[0].provider)} for ${formatLabel(missingRequiredCredentials[0].venue)}`
              : "No required credential gap"
          }
        />
        <MetricCard
          label="Worker"
          value={workerState}
          detail={formatWorkerAge(summary?.status.worker?.ageSeconds)}
        />
      </MetricGrid>

      <div className="system-layout">
        <Panel
          eyebrow="Action needed"
          title="Next system step"
          status={actions.length ? `${actions.length} item${actions.length === 1 ? "" : "s"}` : "clear"}
          statusTone={actions.length ? "waiting" : "ok"}
        >
          {actions.length ? (
            <ol className="system-action-list">
              {actions.map((action) => (
                <li key={action.title}>
                  <div>
                    <strong>{action.title}</strong>
                    <span>{action.body}</span>
                  </div>
                  {action.href ? (
                    <Link className="button subtle" href={action.href}>
                      {action.label ?? "Open"}
                      <ArrowRight aria-hidden="true" size={15} />
                    </Link>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState
              title="No system action needed"
              body="The system has no readiness blockers. Keep monitoring the next loop and open orders."
            />
          )}
        </Panel>

        <Panel
          eyebrow="Safety gates"
          title="Readiness checklist"
          status={`${blockedItems.length} blocked`}
          statusTone={blockedItems.length ? "blocked" : "ok"}
          className="span-2"
        >
          <div className="system-readiness-list">
            {statusItems.map((item) => (
              <ReadinessItem item={item} key={item.label} />
            ))}
          </div>
        </Panel>
      </div>

      <div className="system-layout">
        <Panel
          eyebrow="Accounts"
          title="Wallets and broker credentials"
          status={`${credentials.filter((credential) => credential.present).length}/${credentials.length} present`}
          statusTone={missingRequiredCredentials.length ? "blocked" : "ok"}
          className="span-2"
        >
          <div className="system-account-grid">
            {credentials.map((credential) => (
              <CredentialCard credential={credential} key={credential.id ?? `${credential.venue}-${credential.provider}`} />
            ))}
          </div>
        </Panel>

        <Panel
          eyebrow="Runtime"
          title="Worker and notifications"
          status={notificationState}
          statusTone={notificationState === "ready" || notificationState === "configured" ? "ok" : "waiting"}
        >
          <div className="system-runtime-list">
            <RuntimeRow
              icon={<Clock3 aria-hidden="true" size={17} />}
              label="Worker heartbeat"
              value={summary?.status.worker?.value ?? workerState}
              detail={formatWorkerAge(summary?.status.worker?.ageSeconds)}
            />
            <RuntimeRow
              icon={<Bell aria-hidden="true" size={17} />}
              label="Notifications"
              value={summary?.notifications?.value ?? notificationState}
              detail={`${summary?.notifications?.recipientCount ?? 0} recipients`}
            />
            <RuntimeRow
              icon={<ShieldCheck aria-hidden="true" size={17} />}
              label="Emergency stop"
              value={killSwitchActive ? "active" : "clear"}
              detail={killSwitchActive ? "Trading actions are stopped." : "No emergency stop is active."}
            />
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ReadinessItem({ item }: { item: StatusItem }) {
  const Icon = item.state === "blocked" ? AlertTriangle : CheckCircle2;
  return (
    <article className="system-readiness-item" data-state={item.state}>
      <Icon aria-hidden="true" size={18} />
      <div>
        <strong>{item.label}</strong>
        <span>{item.value}</span>
      </div>
      <StatusChip tone={item.state}>{item.state}</StatusChip>
    </article>
  );
}

function CredentialCard({ credential }: { credential: WalletCredentialView }) {
  const title = credential.label ?? `${formatLabel(credential.venue)} / ${formatLabel(credential.provider)}`;
  const requiredForLive = credential.requiredForLive !== false;
  return (
    <article className="system-account-card" data-present={credential.present ? "true" : "false"}>
      <div className="system-account-icon">
        {credential.present ? (
          <WalletCards aria-hidden="true" size={19} />
        ) : (
          <KeyRound aria-hidden="true" size={19} />
        )}
      </div>
      <div>
        <strong>{title}</strong>
        <span>{credential.publicIdentifier}</span>
        {credential.message ? <small>{credential.message}</small> : null}
        {credential.reference ? <small>{credential.reference}</small> : null}
      </div>
      <div className="system-account-status">
        <StatusChip tone={credential.present ? "ok" : requiredForLive ? "blocked" : "waiting"}>
          {credential.status ?? (credential.present ? "present" : "missing")}
        </StatusChip>
        <small>{requiredForLive ? "Required for live" : "Optional"}</small>
      </div>
    </article>
  );
}

function RuntimeRow({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="system-runtime-row">
      <span className="system-runtime-icon">{icon}</span>
      <div>
        <strong>{label}</strong>
        <span>{value}</span>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function buildSystemActions({
  blockedItems,
  credentials,
  killSwitchActive,
  notificationState,
}: {
  blockedItems: StatusItem[];
  credentials: WalletCredentialView[];
  killSwitchActive: boolean;
  notificationState: string;
}): SystemAction[] {
  const actions: SystemAction[] = [];
  if (killSwitchActive) {
    actions.push({
      title: "Review the emergency stop",
      body: "The emergency stop is active. Open Run before changing run or live-mode settings.",
      href: "/dashboard/operations",
      label: "Open operations",
    });
  }
  for (const item of blockedItems.slice(0, 3)) {
    actions.push({
      title: `Fix ${item.label.toLowerCase()}`,
      body: item.value,
      href: actionHrefForStatus(item),
      label: actionLabelForStatus(item),
    });
  }
  for (const credential of credentials.slice(0, 2)) {
    actions.push({
      title: `Connect ${credential.label ?? formatLabel(credential.venue)}`,
      body:
        credential.message ??
        `${formatLabel(credential.provider)} credential is missing for ${formatLabel(credential.venue)}.`,
      href: "/dashboard/config",
      label: "Open config",
    });
  }
  if (notificationState !== "ready" && notificationState !== "configured") {
    actions.push({
      title: "Check notifications",
      body: "Alerts and digests are not fully ready. Configure recipients before live trading.",
      href: "/dashboard/config",
      label: "Open config",
    });
  }
  return dedupeActions(actions).slice(0, 5);
}

function actionHrefForStatus(item: StatusItem): string {
  const label = item.label.toLowerCase();
  if (label.includes("notification")) {
    return "/dashboard/config";
  }
  if (label.includes("wallet") || label.includes("venue") || label.includes("trading")) {
    return "/dashboard/config";
  }
  if (label.includes("ingestion") || label.includes("worker") || label.includes("audit") || label.includes("health")) {
    return "/dashboard/operations";
  }
  return "/dashboard/system";
}

function actionLabelForStatus(item: StatusItem): string {
  const href = actionHrefForStatus(item);
  if (href.endsWith("/config")) {
    return "Open config";
  }
  if (href.endsWith("/operations")) {
    return "Open operations";
  }
  return "Open system";
}

function dedupeActions(actions: SystemAction[]): SystemAction[] {
  const seen = new Set<string>();
  return actions.filter((action) => {
    const key = `${action.title}-${action.href ?? ""}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function resolveSystemTone({
  blockedCount,
  killSwitchActive,
  liveEnabled,
}: {
  blockedCount: number;
  killSwitchActive: boolean;
  liveEnabled: boolean;
}): "ok" | "blocked" | "waiting" {
  if (killSwitchActive || blockedCount > 0) {
    return "blocked";
  }
  return liveEnabled ? "waiting" : "ok";
}

function resolveSystemLabel({
  blockedCount,
  killSwitchActive,
  liveEnabled,
}: {
  blockedCount: number;
  killSwitchActive: boolean;
  liveEnabled: boolean;
}): string {
  if (killSwitchActive) {
    return "stopped";
  }
  if (blockedCount > 0) {
    return "needs attention";
  }
  return liveEnabled ? "live gate ready" : "simulation ready";
}

function formatWorkerAge(ageSeconds?: number | null): string {
  if (ageSeconds === null || ageSeconds === undefined) {
    return "No heartbeat age recorded";
  }
  if (ageSeconds < 60) {
    return `${Math.round(ageSeconds)} seconds ago`;
  }
  const minutes = Math.round(ageSeconds / 60);
  if (minutes < 60) {
    return `${minutes} minutes ago`;
  }
  return `${Math.round(minutes / 60)} hours ago`;
}

function formatLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function formatLoadError(message: string): string {
  try {
    const parsed = JSON.parse(message) as { detail?: { error_code?: string; message?: string } };
    if (parsed.detail?.error_code === "dashboard_access_denied") {
      return "Dashboard summary could not load because the backend rejected the local session. Check backend token and session settings before changing trading settings.";
    }
    if (parsed.detail?.message) {
      return `${parsed.detail.message}. Check backend health before changing trading settings.`;
    }
  } catch {
    // Fall back to the original message below.
  }
  return `${message}. Check backend health before changing trading settings.`;
}
