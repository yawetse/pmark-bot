"use client";

// REQ: REQ-UI-010

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { Disclosure } from "@/components/dashboard/dashboard-primitives";
import Link from "next/link";

export type ModelProviderName = "claude" | "openai";

type ModelRow = Record<string, unknown>;

export type ModelSummary = {
  provider: ModelProviderName;
  budget?: {
    used_usd?: string;
    limit_usd?: string;
  };
  pnl?: string;
  positions?: ModelRow[];
  decisions?: ModelRow[];
  orders?: ModelRow[];
  degraded_sections?: string[];
};

export type ModelWorkspaceProvider = {
  provider: ModelProviderName;
  summary?: ModelSummary;
  loadError?: string;
};

const EMPTY_SUMMARY: Record<ModelProviderName, ModelSummary> = {
  claude: { provider: "claude", budget: { used_usd: "0.00", limit_usd: "0.00" }, pnl: "0.00" },
  openai: { provider: "openai", budget: { used_usd: "0.00", limit_usd: "0.00" }, pnl: "0.00" },
};

const MODEL_LABELS: Record<ModelProviderName, string> = {
  claude: "Claude",
  openai: "OpenAI",
};

export function ModelsWorkspace({ providers }: { providers: ModelWorkspaceProvider[] }) {
  return (
    <div className="page-stack">
      <section className="panel wide-panel">
        <div className="panel-heading">
          <div>
            <p className="section-label">Models</p>
            <h1>Provider Workspace</h1>
          </div>
          <span className="status idle">{providers.length} providers</span>
        </div>
        <p className="panel-note">
          Review provider budget, decisions, orders, and positions from one place. Use provider
          details when you need exact records.
        </p>
      </section>

      <section className="model-provider-grid" aria-label="Model providers">
        {providers.map((provider) => (
          <ModelProviderCard
            key={provider.provider}
            provider={provider.provider}
            summary={provider.summary ?? EMPTY_SUMMARY[provider.provider]}
            loadError={provider.loadError}
          />
        ))}
      </section>
    </div>
  );
}

function ModelProviderCard({
  provider,
  summary,
  loadError,
}: {
  provider: ModelProviderName;
  summary: ModelSummary;
  loadError?: string;
}) {
  const positions = summary.positions ?? [];
  const decisions = summary.decisions ?? [];
  const orders = summary.orders ?? [];
  const label = MODEL_LABELS[provider];

  return (
    <article className="operator-panel model-provider-card">
      <div className="panel-heading">
        <div>
          <p className="section-label">Provider</p>
          <h2>{label}</h2>
        </div>
        {loadError ? <span className="status blocked">api unavailable</span> : null}
      </div>
      {loadError ? <p className="status-message blocked">{loadError}</p> : null}
      <div className="metric-grid compact">
        <Metric
          label="Budget"
          value={`$${summary.budget?.used_usd ?? "0.00"} / $${summary.budget?.limit_usd ?? "0.00"}`}
        />
        <Metric label="P&L" value={`$${summary.pnl ?? "0.00"}`} />
        <Metric label="Decisions" value={String(decisions.length)} />
        <Metric label="Orders" value={String(orders.length)} />
      </div>
      <div className="model-workflow-strip compact">
        <div>
          <span>1</span>
          <strong>Decisions</strong>
          <small>{decisions.length} scored rows</small>
        </div>
        <div>
          <span>2</span>
          <strong>Orders</strong>
          <small>{orders.length} simulated or submitted rows</small>
        </div>
        <div>
          <span>3</span>
          <strong>Positions</strong>
          <small>{positions.length} open or closed rows</small>
        </div>
      </div>
      <Link className="button" href={`/dashboard/models/${provider}`}>
        View {label} Details
      </Link>
    </article>
  );
}

export function ModelSummaryPanel({
  provider,
  summary = EMPTY_SUMMARY[provider],
  loadError,
}: {
  provider: ModelProviderName;
  summary?: ModelSummary;
  loadError?: string;
}) {
  const positions = summary.positions ?? [];
  const decisions = summary.decisions ?? [];
  const orders = summary.orders ?? [];
  const providerLabel = MODEL_LABELS[provider];

  return (
    <section className="panel wide-panel">
      <div className="breadcrumb-row" aria-label="Breadcrumb">
        <Link href="/dashboard/models">Models</Link>
        <span aria-hidden="true">/</span>
        <span>{providerLabel}</span>
      </div>
      <div className="panel-heading">
        <div>
          <p className="section-label">Model provider</p>
          <h1>{providerLabel}</h1>
        </div>
        {loadError ? <span className="status blocked">api unavailable</span> : null}
      </div>
      {loadError ? <p className="status-message">{loadError}</p> : null}
      <div className="metric-grid">
        <Metric
          label="Budget used"
          value={`$${summary.budget?.used_usd ?? "0.00"} / $${summary.budget?.limit_usd ?? "0.00"}`}
        />
        <Metric label="P&L" value={`$${summary.pnl ?? "0.00"}`} />
        <Metric label="Positions" value={String(positions.length)} />
        <Metric label="Decisions" value={String(decisions.length)} />
      </div>
      <div className="model-workflow-strip" aria-label={`${provider} workflow summary`}>
        <div>
          <span>1</span>
          <strong>Decisions</strong>
          <small>{decisions.length} scored records</small>
        </div>
        <div>
          <span>2</span>
          <strong>Orders</strong>
          <small>{orders.length} submitted or simulated rows</small>
        </div>
        <div>
          <span>3</span>
          <strong>Positions</strong>
          <small>{positions.length} open or closed records</small>
        </div>
      </div>

      <Disclosure title={`Position Records (${positions.length})`}>
        <ModelRows
          emptyTitle="No positions"
          emptyBody="No open or closed positions have been recorded for this provider."
          rows={positions}
          title="Position records"
        />
      </Disclosure>

      <Disclosure title={`Decision Records (${decisions.length})`}>
        <ModelRows
          emptyTitle="No decisions"
          emptyBody="No scored decisions have been recorded for this provider."
          rows={decisions}
          title="Decision records"
        />
      </Disclosure>

      <Disclosure title={`Order Records (${orders.length})`}>
        <ModelRows
          emptyTitle="No orders"
          emptyBody="No simulated or live orders have been recorded for this provider."
          rows={orders}
          title="Order records"
        />
      </Disclosure>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ModelRows({
  rows,
  emptyTitle,
  emptyBody,
  title,
}: {
  rows: ModelRow[];
  emptyTitle: string;
  emptyBody: string;
  title: string;
}) {
  const normalizedRows = rows.map(normalizeRow);
  const columns = columnsForRows(normalizedRows);

  return (
    <DashboardDataGrid
      rows={normalizedRows}
      columns={columns}
      emptyTitle={emptyTitle}
      emptyBody={emptyBody}
      getRowId={(row) => row.id || row.positionId || JSON.stringify(row)}
      title={title}
      density="compact"
      searchPlaceholder="Filter rows"
    />
  );
}

function normalizeRow(row: ModelRow): Record<string, string> {
  return Object.fromEntries(
    Object.entries(row).map(([key, value]) => [key, formatCellValue(value)]),
  );
}

function columnsForRows(rows: Record<string, string>[]): DashboardGridColumn<Record<string, string>>[] {
  const keys = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).sort(compareModelColumnKeys);
  return keys.map((key) => ({
    field: key,
    headerName: titleFromKey(key),
    minWidth: key.toLowerCase().includes("message") ? 240 : 140,
  }));
}

const MODEL_COLUMN_PRIORITY = [
  "id",
  "positionId",
  "instrumentId",
  "venue",
  "modelProvider",
  "state",
  "status",
  "side",
  "direction",
  "confidence",
  "estimatedProbability",
  "notionalUsd",
  "pnl",
  "costUsd",
  "createdAt",
  "updatedAt",
  "message",
  "refusalReason",
];

function compareModelColumnKeys(left: string, right: string): number {
  const leftIndex = MODEL_COLUMN_PRIORITY.indexOf(left);
  const rightIndex = MODEL_COLUMN_PRIORITY.indexOf(right);
  if (leftIndex !== -1 || rightIndex !== -1) {
    return (leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex) -
      (rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex);
  }
  return left.localeCompare(right);
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function titleFromKey(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (value) => value.toUpperCase());
}
