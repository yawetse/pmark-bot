"use client";

import * as Accordion from "@radix-ui/react-accordion";
import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

type StatusTone = "ok" | "blocked" | "idle" | "waiting" | "neutral";

export function PageHeader({
  eyebrow,
  title,
  body,
  children,
}: {
  eyebrow: string;
  title: string;
  body?: string;
  children?: ReactNode;
}) {
  return (
    <section className="page-header" aria-labelledby={slugId(title)}>
      <div>
        <p className="section-label">{eyebrow}</p>
        <h1 id={slugId(title)}>{title}</h1>
        {body ? <p>{body}</p> : null}
      </div>
      {children ? <div className="page-header-aside">{children}</div> : null}
    </section>
  );
}

export function Panel({
  eyebrow,
  title,
  status,
  statusTone = "idle",
  children,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  status?: string;
  statusTone?: StatusTone;
  children: ReactNode;
  className?: string;
}) {
  const titleId = slugId(title);
  return (
    <section className={`operator-panel ${className}`.trim()} aria-labelledby={titleId}>
      <div className="panel-heading">
        <div>
          {eyebrow ? <p className="section-label">{eyebrow}</p> : null}
          <h2 id={titleId}>{title}</h2>
        </div>
        {status ? <StatusChip tone={statusTone}>{status}</StatusChip> : null}
      </div>
      {children}
    </section>
  );
}

export function StatusChip({
  tone,
  children,
}: {
  tone: StatusTone;
  children: ReactNode;
}) {
  return <span className={`status ${tone === "neutral" ? "idle" : tone}`}>{children}</span>;
}

export function MetricGrid({ children, compact = false }: { children: ReactNode; compact?: boolean }) {
  return <div className={`metric-grid ${compact ? "compact" : ""}`.trim()}>{children}</div>;
}

export function MetricCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{body}</p>
      {children ? <div className="empty-state-actions">{children}</div> : null}
    </div>
  );
}

export function FormSection({
  id,
  icon,
  title,
  body,
  children,
}: {
  id?: string;
  icon?: ReactNode;
  title: string;
  body: string;
  children: ReactNode;
}) {
  const titleId = id ? `${id}-title` : slugId(title);
  return (
    <section className="preference-section" id={id} aria-labelledby={titleId}>
      <div className="preference-section-heading">
        <div className="preference-section-title">
          {icon}
          <div>
            <h3 id={titleId}>{title}</h3>
            <p>{body}</p>
          </div>
        </div>
      </div>
      {children}
    </section>
  );
}

export function Message({
  tone = "idle",
  children,
}: {
  tone?: StatusTone;
  children: ReactNode;
}) {
  return <p className={`status-message ${tone}`}>{children}</p>;
}

export function Disclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <Accordion.Root
      className="dashboard-disclosure"
      collapsible
      defaultValue={defaultOpen ? "content" : undefined}
      type="single"
    >
      <Accordion.Item className="dashboard-disclosure-item" value="content">
        <Accordion.Header className="dashboard-disclosure-header">
          <Accordion.Trigger className="dashboard-disclosure-trigger">
            <span>{title}</span>
            <ChevronDown aria-hidden="true" size={16} strokeWidth={2.4} />
          </Accordion.Trigger>
        </Accordion.Header>
        <Accordion.Content className="dashboard-disclosure-content">
          {children}
        </Accordion.Content>
      </Accordion.Item>
    </Accordion.Root>
  );
}

function slugId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
