// REQ: REQ-UI-002

import type { ReactNode } from "react";
import {
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  CircleAlert,
  Database,
  GitBranch,
  KeyRound,
  LogIn,
  MonitorCheck,
  Send,
  ShieldCheck,
  WalletCards,
} from "lucide-react";

import { MethodExplorer } from "@/components/product-story/method-explorer";

const GATE_GROUPS = [
  {
    title: "Operator",
    body: "Approved identity, permitted account mode, live setting, and emergency stop state.",
    icon: KeyRound,
  },
  {
    title: "Market data",
    body: "Current, supported, sufficiently liquid, and open for trading.",
    icon: Database,
  },
  {
    title: "Model decision",
    body: "A complete provider decision with sufficient confidence and available budget.",
    icon: BrainCircuit,
  },
  {
    title: "Strategy consensus",
    body: "Recorded signals satisfy the configured agreement rule.",
    icon: GitBranch,
  },
  {
    title: "Risk",
    body: "The proposed exposure stays inside every capital limit.",
    icon: ShieldCheck,
  },
  {
    title: "Execution",
    body: "The venue account is reconciled and the order intent is safely persisted.",
    icon: Send,
  },
] as const;

const AUTHORIZATION_PATH = [
  "Market clears deterministic screen",
  "Probability case is recorded",
  "Trade decision is recorded",
  "Capital limits approve the exposure",
  "Venue account is reconciled",
] as const;

type ProductLandingFrameProps = {
  accessFeedback?: ReactNode;
};

function ProductLandingFrame({ accessFeedback }: ProductLandingFrameProps) {
  return (
    <div className="landing-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <header className="landing-header">
        <a className="landing-brand" href="#top" aria-label="Codex Poly Bot home">
          <span className="landing-brand-mark" aria-hidden="true">
            CP
          </span>
          <span>
            <strong>Codex Poly Bot</strong>
            <small>Controlled market automation</small>
          </span>
        </a>
        <nav className="landing-nav" aria-label="Landing page">
          <a href="#method">How it works</a>
          <a href="/story">Read the story</a>
          <a href="#gates">Safety gates</a>
          <a className="button landing-nav-cta" href="/api/auth/github/start">
            Sign in
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        </nav>
      </header>

      <main id="main-content">
        <section className="landing-hero" id="top" aria-labelledby="landing-title">
          <div className="landing-hero-copy">
            <p className="landing-kicker">
              <span aria-hidden="true" />
              Operator-controlled trading system
            </p>
            <h1 id="landing-title">
              Every trade must
              <span> earn the right to run.</span>
            </h1>
            <p className="landing-lede">
              Codex Poly Bot turns live market data into reviewable trading decisions across
              Polymarket and Alpaca. It can simulate or submit orders within limits an
              operator can inspect and change.
            </p>

            {accessFeedback}

            <div className="landing-hero-actions">
              <a className="button primary landing-primary-action" href="/api/auth/github/start">
                <LogIn size={18} aria-hidden="true" />
                Continue with GitHub
                <ArrowRight size={17} aria-hidden="true" />
              </a>
              <a className="landing-text-link" href="#method">
                See the decision path
                <ArrowRight size={16} aria-hidden="true" />
              </a>
            </div>
            <p className="landing-auth-note">
              GitHub identifies approved dashboard operators. Trading and model credentials
              are not shared with GitHub.
            </p>
          </div>

          <aside className="authorization-card" aria-label="Example trade authorization path">
            <div className="authorization-card-header">
              <div>
                <span>ORDER AUTHORIZATION</span>
                <strong>Candidate review</strong>
              </div>
              <span className="deny-badge">Deny by default</span>
            </div>
            <div className="candidate-card">
              <span className="candidate-symbol">?</span>
              <div>
                <small>MARKET CANDIDATE</small>
                <strong>Evidence before exposure</strong>
              </div>
              <span className="candidate-state">Review</span>
            </div>
            <ol className="authorization-list">
              {AUTHORIZATION_PATH.map((gate, index) => (
                <li key={gate}>
                  <span className="authorization-index">{String(index + 1).padStart(2, "0")}</span>
                  <span>{gate}</span>
                  <CheckCircle2 size={17} aria-hidden="true" />
                </li>
              ))}
            </ol>
            <div className="authorization-outcome">
              <ShieldCheck size={20} aria-hidden="true" />
              <div>
                <small>ONLY AFTER ALL GATES PASS</small>
                <strong>Simulate or submit</strong>
              </div>
              <ArrowRight size={18} aria-hidden="true" />
            </div>
          </aside>
        </section>

        <section className="landing-section method-section" id="method" aria-labelledby="method-title">
          <div className="landing-section-heading">
            <div>
              <p className="landing-section-label">THE DECISION ENGINE</p>
              <h2 id="method-title">Five stages. One recorded decision.</h2>
            </div>
            <p>
              Each loop narrows the opportunity set before capital is involved. Open any
              stage to inspect the evidence, algorithms, decision rule, and operator controls.
            </p>
          </div>

          <MethodExplorer />
        </section>

        <section className="landing-section gates-section" id="gates" aria-labelledby="gates-title">
          <div className="gates-intro">
            <p className="landing-section-label">THE LIVE-ORDER BOUNDARY</p>
            <h2 id="gates-title">A good idea is not enough to place a trade.</h2>
            <p>
              A decision can exist without being eligible for execution. These checks form
              the final boundary between an approved thesis and an order.
            </p>
            <div className="gate-result">
              <CircleAlert size={19} aria-hidden="true" />
              <span>
                <strong>Any gate fails</strong>
                No live order. The refusal stays visible in the audit trail.
              </span>
            </div>
          </div>

          <div className="gate-grid">
            {GATE_GROUPS.map((gate, index) => {
              const Icon = gate.icon;
              return (
                <article className="gate-card" key={gate.title}>
                  <div className="gate-card-heading">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
                  </div>
                  <h3>{gate.title}</h3>
                  <p>{gate.body}</p>
                </article>
              );
            })}
          </div>
        </section>

        <section className="landing-section control-section" aria-labelledby="control-title">
          <div className="control-story">
            <p className="landing-section-label">PRODUCT BOUNDARIES</p>
            <h2 id="control-title">Automation with explicit limits.</h2>
            <p>
              You decide where the bot can operate and how much exposure it can take. Codex
              Poly Bot versions those settings, applies them on the next loop, and records
              what it did with them.
            </p>
          </div>

          <div className="control-limits">
            <div className="control-limit-card">
              <WalletCards size={21} aria-hidden="true" />
              <div>
                <strong>Explicit venue control</strong>
                <p>
                  Venues do not become eligible because credentials exist. An operator must
                  enable the venue and choose the permitted account mode.
                </p>
              </div>
            </div>
            <div className="control-limit-card">
              <ShieldCheck size={21} aria-hidden="true" />
              <div>
                <strong>Conservative scope</strong>
                <p>
                  Alpaca supports long stocks and ETFs plus disabled-by-default,
                  easy-to-borrow U.S. equity shorts. Options, crypto, hard-to-borrow locates,
                  and margin-funded long purchases are refused.
                </p>
              </div>
            </div>
            <div className="control-limit-card">
              <MonitorCheck size={21} aria-hidden="true" />
              <div>
                <strong>Venue-confirmed results</strong>
                <p>
                  Performance uses confirmed balances, positions, and fills. Simulated or
                  unfilled orders do not appear as actual results.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="landing-cta" aria-labelledby="cta-title">
          <div>
            <p className="landing-section-label">OPERATOR ACCESS</p>
            <h2 id="cta-title">Inspect the system before you change it.</h2>
            <p>
              Sign in to review current mode, blocked gates, model decisions, risk settings,
              audit events, and venue-confirmed performance.
            </p>
          </div>
          <a className="button primary landing-primary-action" href="/api/auth/github/start">
            <LogIn size={18} aria-hidden="true" />
            Continue with GitHub
            <ArrowRight size={17} aria-hidden="true" />
          </a>
        </section>
      </main>

      <footer className="landing-footer">
        <span>
          Codex Poly Bot · <a href="/story">Read the product note</a>
        </span>
        <p>
          Trading involves risk. Automated decisions can be wrong. Access does not remove the
          need for operator review.
        </p>
      </footer>
    </div>
  );
}

function LoginAccessFeedback({
  error,
  status,
}: {
  error?: string;
  status?: string;
}) {
  if (error) {
    return (
      <p className="landing-auth-message is-error" role="alert">
        <CircleAlert size={17} aria-hidden="true" />
        {error}
      </p>
    );
  }
  if (status === "signed_out") {
    return (
      <p className="landing-auth-message" role="status">
        <CheckCircle2 size={17} aria-hidden="true" />
        You have signed out.
      </p>
    );
  }
  return null;
}

export function PublicProductLanding() {
  return <ProductLandingFrame />;
}

export function LoginProductLanding({
  error,
  status,
}: {
  error?: string;
  status?: string;
}) {
  return (
    <ProductLandingFrame
      accessFeedback={<LoginAccessFeedback error={error} status={status} />}
    />
  );
}
