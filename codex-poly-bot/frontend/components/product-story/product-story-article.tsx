import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  GitCompareArrows,
  LogIn,
  ScanSearch,
  ShieldCheck,
  X,
} from "lucide-react";

import { MethodExplorer } from "@/components/product-story/method-explorer";

const DECISION_PATH = [
  {
    label: "Observe",
    detail: "Markets, prices, liquidity, history, and target-wallet activity",
  },
  {
    label: "Evaluate",
    detail: "Deterministic screens, model estimates, and strategy signals",
  },
  {
    label: "Authorize",
    detail: "Consensus, capital limits, account state, and execution gates",
  },
  {
    label: "Act",
    detail: "Persist an order intent, simulate or submit, then reconcile",
  },
] as const;

const PRODUCT_SCOPE = [
  "Scans Polymarket opportunities and a configured long-only Alpaca universe",
  "Records probability estimates, confidence, strategy signals, and refusals",
  "Sizes approved exposure within operator-defined capital limits",
  "Separates dry-run decisions from venue-confirmed positions and performance",
] as const;

const PRODUCT_BOUNDARIES = [
  "It does not guarantee returns or treat a model score as an order",
  "It does not enable a venue just because credentials exist",
  "It does not count simulated or unfilled orders as actual performance",
  "It does not support options, short selling, margin, or unrestricted assets in Alpaca v1",
] as const;

export function ProductStoryArticle() {
  return (
    <div className="story-shell">
      <a className="skip-link" href="#story-content">
        Skip to article
      </a>

      <header className="story-header">
        <a className="landing-brand" href="/" aria-label="Codex Poly Bot home">
          <span className="landing-brand-mark" aria-hidden="true">
            CP
          </span>
          <span>
            <strong>Codex Poly Bot</strong>
            <small>Controlled market automation</small>
          </span>
        </a>
        <nav className="story-nav" aria-label="Article">
          <a href="/">
            <ArrowLeft size={15} aria-hidden="true" />
            Product overview
          </a>
          <a className="button story-nav-cta" href="/api/auth/github/start">
            Sign in
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        </nav>
      </header>

      <main id="story-content">
        <article>
          <header className="story-hero">
            <div className="story-hero-copy">
              <p className="story-label">A PRODUCT NOTE ON CONTROLLED MARKET AUTOMATION</p>
              <h1>
                Trading bots are easy to start.
                <span>Knowing when to do nothing is harder.</span>
              </h1>
              <p className="story-deck">
                I built Codex Poly Bot to test a simple operating model: every automated
                trade should carry enough evidence, authorization, and risk context to
                explain why it was allowed to run.
              </p>
            </div>

            <aside className="story-summary" aria-label="The short version">
              <span>THE SHORT VERSION</span>
              <p>
                Poly Bot scans Polymarket and Alpaca, evaluates candidates through several
                independent methods, and only simulates or submits an order after every
                required gate passes.
              </p>
              <a href="#how-it-works">
                See the five-stage process
                <ArrowDown size={15} aria-hidden="true" />
              </a>
            </aside>
          </header>

          <section className="story-prose story-opening" aria-labelledby="problem-title">
            <p className="story-section-index">01 / THE PROBLEM</p>
            <div>
              <h2 id="problem-title">A prediction is not permission to trade.</h2>
              <p>
                Automated trading systems can collapse several different decisions into one
                action. They find a market, estimate an outcome, calculate a position, and
                submit an order. When those steps are hidden inside one loop, it becomes
                difficult to separate a useful signal from a safe trade.
              </p>
              <p>
                Poly Bot treats each opportunity as a candidate, not an instruction. A
                candidate can have a strong model score and still fail because liquidity is
                weak, strategies disagree, the account is not reconciled, or the proposed
                exposure exceeds a limit. Refusing the trade is a valid result.
              </p>
              <blockquote>
                The core rule is direct: no single model, strategy, wallet, or price movement
                has authority to place an order.
              </blockquote>
            </div>
          </section>

          <section className="story-system" aria-labelledby="system-title">
            <div className="story-system-heading">
              <p className="story-section-index">02 / THE OPERATING MODEL</p>
              <h2 id="system-title">Evidence becomes a trade through explicit stages.</h2>
              <p>
                The system keeps discovery, judgment, authorization, and execution separate.
                Each stage produces a record that the next stage can accept or refuse.
              </p>
            </div>

            <ol className="story-decision-path">
              {DECISION_PATH.map((step, index) => (
                <li key={step.label}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                  </div>
                  {index < DECISION_PATH.length - 1 ? (
                    <ArrowRight aria-hidden="true" />
                  ) : (
                    <ShieldCheck aria-hidden="true" />
                  )}
                </li>
              ))}
            </ol>

            <div className="story-system-rule">
              <GitCompareArrows size={22} aria-hidden="true" />
              <p>
                <strong>Records connect the stages.</strong> The bot can show what it saw,
                which methods ran, what they concluded, which gates passed, and what the
                venue later confirmed.
              </p>
            </div>
          </section>

          <section
            className="story-method"
            id="how-it-works"
            aria-labelledby="story-method-title"
          >
            <div className="story-method-heading">
              <div>
                <p className="story-section-index">03 / HOW IT WORKS</p>
                <h2 id="story-method-title">Five stages narrow the opportunity.</h2>
              </div>
              <p>
                Open any stage for the inputs, strategies, algorithms, decision rule, and
                operator controls used at that point.
              </p>
            </div>
            <MethodExplorer />
          </section>

          <section className="story-prose story-gates" aria-labelledby="gates-story-title">
            <p className="story-section-index">04 / WHY THE GATES MATTER</p>
            <div>
              <h2 id="gates-story-title">A good thesis can still end in no trade.</h2>
              <p>
                Model quality is only one part of the decision. The system also checks the
                operator, market data, strategy agreement, risk limits, account state, and
                execution conditions. Live eligibility requires all of them.
              </p>

              <div className="story-gate-equation" aria-label="Trade authorization rule">
                <span>Evidence</span>
                <strong>+</strong>
                <span>Consensus</span>
                <strong>+</strong>
                <span>Risk approval</span>
                <strong>+</strong>
                <span>Reconciled venue</span>
                <strong>=</strong>
                <span className="is-result">Eligible order</span>
              </div>

              <p>
                If a required input is missing or contradictory, the default is refusal. The
                reason stays in the audit trail. That makes “no trade” observable instead of
                indistinguishable from a broken loop.
              </p>
            </div>
          </section>

          <section className="story-scope" aria-labelledby="scope-title">
            <div className="story-scope-heading">
              <p className="story-section-index">05 / PRODUCT BOUNDARIES</p>
              <h2 id="scope-title">What Poly Bot does, and what it does not do.</h2>
            </div>
            <div className="story-scope-grid">
              <section aria-labelledby="does-title">
                <div className="story-scope-title">
                  <Check size={18} aria-hidden="true" />
                  <h3 id="does-title">What it does</h3>
                </div>
                <ul>
                  {PRODUCT_SCOPE.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
              <section aria-labelledby="does-not-title">
                <div className="story-scope-title is-boundary">
                  <X size={18} aria-hidden="true" />
                  <h3 id="does-not-title">What it does not do</h3>
                </div>
                <ul>
                  {PRODUCT_BOUNDARIES.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </div>
          </section>

          <section className="story-closing" aria-labelledby="closing-title">
            <ScanSearch size={28} aria-hidden="true" />
            <div>
              <p className="story-section-index">TRY THE SYSTEM</p>
              <h2 id="closing-title">Inspect the decisions before trusting the automation.</h2>
              <p>
                The dashboard exposes the current operating mode, candidate funnel, model
                decisions, refusals, risk settings, audit events, orders, and
                venue-confirmed results. Start in dry-run mode, review what the bot would do,
                and change the limits before considering live execution.
              </p>
              <div className="story-closing-actions">
                <a className="button primary story-primary-action" href="/api/auth/github/start">
                  <LogIn size={18} aria-hidden="true" />
                  Continue with GitHub
                  <ArrowRight size={17} aria-hidden="true" />
                </a>
                <a href="/">
                  View the product overview
                  <ArrowRight size={16} aria-hidden="true" />
                </a>
              </div>
              <p className="story-access-note">
                GitHub sign-in confirms whether an account is approved for dashboard access.
                Market and model credentials are not shared with GitHub.
              </p>
            </div>
          </section>
        </article>
      </main>

      <footer className="story-footer">
        <span>Codex Poly Bot</span>
        <p>
          <CircleAlert size={14} aria-hidden="true" />
          Trading involves risk. Automated decisions can be wrong. Historical behavior does
          not guarantee future results.
        </p>
      </footer>
    </div>
  );
}
