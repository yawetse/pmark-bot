"use client";

// Redesigned Overview: leads with "needs attention" vs "all clear" vs "live trade",
// instead of stacking every panel. Replaces the top of components/dashboard/consumer-dashboard.tsx.
//
// This is a structural skeleton, not a full data-wired rewrite — consumer-dashboard.tsx
// (2600+ lines) already owns real fetches via dashboardApi / useDashboardRealtime and a lot
// of local state (config patches, save states, recommendation plans). Map those into the
// props below rather than re-deriving them; this file only changes LAYOUT/IA, not data logic.

import Link from "next/link";
import type { ReactNode } from "react";

export type OverviewState = "attention" | "clear" | "live";

export type AttentionItem = {
  title: string;
  body: string;
  actionLabel: string;
  actionHref: string;
};

export type RecommendationCard = {
  id: "conservative" | "balanced" | "aggressive";
  badge: string;
  title: string;
  body: string;
  buttonLabel: string;
  isCurrent: boolean;
  onApply: () => void;
};

export type OverviewPageProps = {
  state: OverviewState;
  updatedAgoLabel: string; // e.g. "42 seconds ago"
  attentionItems: AttentionItem[]; // only used when state === "attention"
  recommendations: RecommendationCard[]; // only used when state === "attention"
  clearMessage?: string; // only used when state === "clear"
  liveTrade?: { headline: string; detail: string; href: string }; // only used when state === "live"
  monitoring: { label: string; value: string; sub: string }[]; // 4 cards: mode, venues, last check, next check
  recentResult: { headline: string; sub: string; href: string };
};

export function OverviewPage(props: OverviewPageProps) {
  const {
    state,
    updatedAgoLabel,
    attentionItems,
    recommendations,
    clearMessage,
    liveTrade,
    monitoring,
    recentResult,
  } = props;

  return (
    <div className="overview-page">
      <div className="overview-header">
        <div>
          <h1>Overview</h1>
          <p className="muted">Updated {updatedAgoLabel} &middot; checks itself every 15 minutes</p>
        </div>
      </div>

      {state === "attention" && (
        <>
          <section className="attention-card">
            <div className="attention-card-head">
              <span className="attention-icon">!</span>
              <div>
                <h2>{attentionItems.length} thing{attentionItems.length === 1 ? "" : "s"} need your attention</h2>
                <p className="muted">Everything else is running fine. These are the only items worth a look right now.</p>
              </div>
            </div>
            <div className="attention-list">
              {attentionItems.map((item) => (
                <div className="attention-item" key={item.title}>
                  <div>
                    <strong>{item.title}</strong>
                    <span className="muted">{item.body}</span>
                  </div>
                  <Link className="btn-primary" href={item.actionHref}>
                    {item.actionLabel}
                  </Link>
                </div>
              ))}
            </div>
          </section>

          <section className="recommendations-card">
            <h2>Recommended settings for next cycle</h2>
            <p className="muted">Based on what got skipped, here are three ways to adjust — pick one or keep what you have.</p>
            <div className="recommendations-grid">
              {recommendations.map((rec) => (
                <article className={`rec-card ${rec.isCurrent ? "rec-card-current" : ""}`} key={rec.id}>
                  <span className="rec-badge">{rec.badge}</span>
                  <h3>{rec.title}</h3>
                  <p className="muted">{rec.body}</p>
                  <button disabled={rec.isCurrent} onClick={rec.onApply}>
                    {rec.buttonLabel}
                  </button>
                </article>
              ))}
            </div>
          </section>
        </>
      )}

      {state === "clear" && (
        <section className="clear-card">
          <span className="clear-icon">&#10003;</span>
          <div>
            <h2>All clear — nothing needs you right now</h2>
            <p className="muted">{clearMessage}</p>
          </div>
        </section>
      )}

      {state === "live" && liveTrade && (
        <section className="live-card">
          <div className="live-card-head">
            <span className="live-icon">$</span>
            <div>
              <h2>A real trade was just placed</h2>
              <p className="muted">Real money is involved in this one. Here's exactly what happened.</p>
            </div>
          </div>
          <div className="live-detail">
            <strong>{liveTrade.headline}</strong>
            <span className="muted">{liveTrade.detail}</span>
          </div>
          <Link href={liveTrade.href}>See full trade detail &rarr;</Link>
        </section>
      )}

      <section className="monitoring-section">
        <div className="monitoring-header">
          <h2>How things are running</h2>
          <span className="status-ok">Nothing else is blocked</span>
        </div>
        <div className="monitoring-grid">
          {monitoring.map((m) => (
            <div className="monitoring-card" key={m.label}>
              <span className="muted">{m.label}</span>
              <strong>{m.value}</strong>
              <span className="muted">{m.sub}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="recent-result-strip">
        <div>
          <strong>{recentResult.headline}</strong>
          <span className="muted">{recentResult.sub}</span>
        </div>
        <Link href={recentResult.href}>See full activity &rarr;</Link>
      </section>

      <section className="explore-more">
        <h2>Explore more</h2>
        <div className="explore-grid">
          <ExploreCard href="/dashboard/performance" title="Performance" body="P&L, win rate, and how each market is doing." />
          <ExploreCard href="/dashboard/config" title="Settings" body="Risk rules, notifications, and which markets to watch." />
          <ExploreCard href="/dashboard/help" title="Help" body="How a trading cycle works, in five steps." />
        </div>
      </section>
    </div>
  );
}

function ExploreCard({ href, title, body }: { href: string; title: string; body: ReactNode }) {
  return (
    <Link className="explore-card" href={href}>
      <strong>{title}</strong>
      <span className="muted">{body}</span>
    </Link>
  );
}
