"use client";

// REQ: REQ-UI-004, REQ-DEP-001, REQ-DEP-002, REQ-DEP-003, REQ-DEP-004, REQ-WAL-003

import {
  DashboardDataGrid,
  type DashboardGridColumn,
} from "@/components/dashboard/data-grid";
import { Disclosure } from "@/components/dashboard/dashboard-primitives";

const COMPONENTS = [
  {
    name: "Next.js dashboard",
    role: "Operator UI for status, config, model views, comparison, operations, system readiness, and this help page.",
    runs: "Local port 3100 or the frontend ECS workload.",
  },
  {
    name: "FastAPI backend",
    role: "API, authorization boundary, config validation, audit recording, status summaries, and service orchestration.",
    runs: "Local port 8000 or the backend ECS workload.",
  },
  {
    name: "Domain services",
    role: "Trading decisions, strategy signals, risk checks, execution gates, exits, notifications, wallets, and comparison metrics.",
    runs: "Inside the backend process.",
  },
  {
    name: "External adapters",
    role: "Approved boundaries for Polymarket, Alpaca, OpenAI, Claude, AWS storage, AWS secrets, SES, and CloudWatch.",
    runs: "Called by backend services when config and safety gates allow it.",
  },
] as const;

const USER_ACTIONS = [
  "Review runtime status, blockers, pending orders, trade history, and performance.",
  "Change venue flags, live mode, loop interval, model budgets, symbols, notification settings, and risk limits.",
  "Inspect Claude and OpenAI views separately to compare decisions, orders, positions, budget, and P&L.",
  "Use Operations to review open orders, terminal order history, degraded venue state, manual review state, and the kill switch.",
  "Use System to check credentials, account status, worker heartbeat, notification readiness, audit, and API health.",
] as const;

const STORAGE = [
  {
    area: "Shared Postgres schema",
    stores: "Runtime config versions, audit events, system health, job runs, venue settings, account registry, and shared operational state.",
  },
  {
    area: "Model schemas",
    stores: "Claude and OpenAI trade decisions, positions, order events, scoring records, budgets, and performance inputs.",
  },
  {
    area: "S3 snapshot buckets",
    stores: "Raw full snapshots, raw incremental snapshots, and normalized market data outputs partitioned by environment, venue, snapshot type, and UTC date.",
  },
  {
    area: "AWS Secrets Manager",
    stores: "Production wallet keys, broker credentials, LLM API keys, OAuth secrets, and other runtime secrets under environment-specific paths.",
  },
] as const;

const CLOUD_INFRA = [
  ["Compute", "ECS Fargate workloads for frontend and backend containers."],
  ["Images", "ECR repositories for backend and frontend images."],
  ["Database", "RDS Postgres for shared, Claude, and OpenAI schemas."],
  ["Storage", "S3 buckets for market-data snapshots with lifecycle retention."],
  ["Secrets", "AWS Secrets Manager paths under /codex-poly-bot/{environment}/..."],
  ["Observability", "CloudWatch log groups and dashboard health indicators."],
  ["Notifications", "Amazon SES identity for digests and alerts."],
  ["Network and HTTPS", "ALB, ACM certificate support, public and private subnets, and HTTP-to-HTTPS redirects."],
] as const;

const ENVIRONMENTS = [
  {
    name: "local",
    purpose: "Workstation and Docker testing",
    runtime: "Postgres, backend on 8000, dashboard on 3100",
    trading: "Dry run, venues disabled, local auth bypass allowed outside production",
  },
  {
    name: "development",
    purpose: "AWS development environment",
    runtime: "Development CloudFormation stack in us-east-1",
    trading: "Alpaca paper profile, live flag off, Polymarket disabled",
  },
  {
    name: "production",
    purpose: "AWS production environment",
    runtime: "Production CloudFormation stack in us-east-1",
    trading: "Live profile only after account approval, secrets, dry-run evidence, risk review, and operator signoff",
  },
] as const;

export function HelpAboutView() {
  const componentColumns: DashboardGridColumn<(typeof COMPONENTS)[number]>[] = [
    { field: "name", headerName: "Component", minWidth: 180 },
    { field: "role", headerName: "What it does", minWidth: 320 },
    { field: "runs", headerName: "How it runs", minWidth: 240 },
  ];
  const storageColumns: DashboardGridColumn<(typeof STORAGE)[number]>[] = [
    { field: "area", headerName: "Storage area", minWidth: 220 },
    { field: "stores", headerName: "Information stored", minWidth: 420 },
  ];
  const environmentColumns: DashboardGridColumn<(typeof ENVIRONMENTS)[number]>[] = [
    { field: "name", headerName: "Environment", minWidth: 150 },
    { field: "purpose", headerName: "Purpose", minWidth: 220 },
    { field: "runtime", headerName: "Runtime", minWidth: 260 },
    { field: "trading", headerName: "Trading posture", minWidth: 320 },
  ];

  return (
    <div className="page-stack">
      <section className="panel wide-panel">
        <p className="section-label">Help and About</p>
        <h1>How codex-poly-bot Works</h1>
        <p>
          The system is a live-capable trading bot with a Next.js dashboard and a
          FastAPI backend. The safe default is dry run. Live trading requires venue
          enablement, credentials, fresh market data, model scoring, risk approval,
          and operator signoff.
        </p>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">System shape</p>
        <h2>High-Level Architecture</h2>
        <div className="architecture-flow" aria-label="Architecture flow">
          <div>
            <strong>GitHub OAuth</strong>
            <span>Authenticates allowlisted operators</span>
          </div>
          <div>
            <strong>Next.js dashboard</strong>
            <span>Shows state and sends control requests</span>
          </div>
          <div>
            <strong>FastAPI backend</strong>
            <span>Validates, audits, and runs service logic</span>
          </div>
          <div>
            <strong>Postgres, AWS, external APIs</strong>
            <span>Store records, hold secrets, and connect to venues and model providers</span>
          </div>
        </div>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Components</p>
        <h2>Main Components</h2>
        <Disclosure title={`View ${COMPONENTS.length} component rows`}>
          <DashboardDataGrid
            rows={[...COMPONENTS]}
            columns={componentColumns}
            emptyTitle="No components"
            emptyBody="No component reference rows are available."
            getRowId={(component) => component.name}
            searchPlaceholder="Filter components"
          />
        </Disclosure>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Runtime</p>
        <h2>How Work Moves Through the System</h2>
        <ol className="timeline-list">
          <li>
            <strong>Configuration is loaded.</strong>
            <span>The backend reads the active config version for the environment.</span>
          </li>
          <li>
            <strong>Enabled venues are scanned.</strong>
            <span>Disabled venues are skipped before scanning, scoring, or trading.</span>
          </li>
          <li>
            <strong>Candidates are filtered and scored.</strong>
            <span>Strategy filters reduce the set, then Claude and OpenAI score eligible candidates within budget.</span>
          </li>
          <li>
            <strong>Signals and risk checks decide whether an order is allowed.</strong>
            <span>Risk gates check live mode, venue flags, credentials, data freshness, position limits, daily loss, slippage, account mode, and the kill switch.</span>
          </li>
          <li>
            <strong>Execution records the outcome.</strong>
            <span>Dry run records simulated orders. Live mode can submit only after every gate passes.</span>
          </li>
          <li>
            <strong>The dashboard reads the result.</strong>
            <span>Status, orders, positions, audits, notifications, and comparison metrics come back through the backend API.</span>
          </li>
        </ol>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Operator actions</p>
        <h2>What Users Can Do</h2>
        <ul className="explain-list">
          {USER_ACTIONS.map((action) => (
            <li key={action}>{action}</li>
          ))}
        </ul>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Storage</p>
        <h2>How Information Is Stored</h2>
        <Disclosure title={`View ${STORAGE.length} storage rows`}>
          <DashboardDataGrid
            rows={[...STORAGE]}
            columns={storageColumns}
            emptyTitle="No storage rows"
            emptyBody="No storage reference rows are available."
            getRowId={(item) => item.area}
            searchPlaceholder="Filter storage"
          />
        </Disclosure>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Cloud setup</p>
        <h2>AWS Infrastructure</h2>
        <p>
          Deployment is defined by CloudFormation and targets AWS us-east-1. Development
          and production use separate stacks, parameter files, resources, secret
          prefixes, and runtime profiles.
        </p>
        <Disclosure title={`View ${CLOUD_INFRA.length} infrastructure areas`}>
          <div className="infra-grid">
            {CLOUD_INFRA.map(([name, detail]) => (
              <div className="infra-item" key={name}>
                <strong>{name}</strong>
                <span>{detail}</span>
              </div>
            ))}
          </div>
        </Disclosure>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Environments</p>
        <h2>Where It Runs</h2>
        <Disclosure title={`View ${ENVIRONMENTS.length} environments`}>
          <DashboardDataGrid
            rows={[...ENVIRONMENTS]}
            columns={environmentColumns}
            emptyTitle="No environments"
            emptyBody="No environment reference rows are available."
            getRowId={(environment) => environment.name}
            searchPlaceholder="Filter environments"
          />
        </Disclosure>
      </section>

      <section className="panel wide-panel">
        <p className="section-label">Release path</p>
        <h2>How Code Gets Deployed</h2>
        <Disclosure title="View release workflow">
          <ol className="timeline-list compact-timeline">
            <li>
              <strong>Pull request and CI</strong>
              <span>GitHub Actions run backend tests, frontend checks, and migration safety checks before deployment work.</span>
            </li>
            <li>
              <strong>Develop branch</strong>
              <span>Merging to develop selects the development stack.</span>
            </li>
            <li>
              <strong>Main branch</strong>
              <span>Merging to main selects the production stack.</span>
            </li>
            <li>
              <strong>Container rollout</strong>
              <span>The workflow builds images, publishes them to ECR, updates ECS, and waits for services to stabilize.</span>
            </li>
          </ol>
        </Disclosure>
      </section>
    </div>
  );
}
