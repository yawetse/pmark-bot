import { ArrowLeft, ArrowRight, CircleAlert, LogIn } from "lucide-react";

const DECISION_PATH = [
  {
    label: "Observe",
    detail: "Collect current prices, liquidity, history, and market activity.",
  },
  {
    label: "Evaluate",
    detail: "Apply deterministic screens, probability estimates, and strategy signals.",
  },
  {
    label: "Authorize",
    detail: "Check agreement, capital limits, account state, and execution conditions.",
  },
  {
    label: "Act",
    detail: "Persist the intent, simulate or submit, and reconcile the result.",
  },
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
        <article className="story-article">
          <header className="story-hero">
            <p className="story-label">A PRODUCT NOTE ON CONTROLLED MARKET AUTOMATION</p>
            <h1>Why a trading bot should be allowed to do nothing</h1>
            <p className="story-deck">
              Most trading bots are designed around execution. Poly Bot starts from a
              different premise: refusal is part of a valid decision.
            </p>
            <p className="story-publication-note">Product note · July 2026</p>
          </header>

          <div className="story-reading-layout">
            <aside className="story-reader-note" aria-label="Article summary">
              <span>IN ONE SENTENCE</span>
              <p>
                Poly Bot turns market signals into reviewable decisions, then requires
                evidence, agreement, and risk approval before an order can run.
              </p>
              <nav aria-label="Article sections">
                <a href="#question">The question</a>
                <a href="#candidate">Candidate, not instruction</a>
                <a href="#process">How it works</a>
                <a href="#gates">Why the gates matter</a>
                <a href="#try">How to try it</a>
              </nav>
            </aside>

            <div className="story-body">
              <p className="story-opening-paragraph">
                Producing a prediction and authorizing an action are different problems.
                Trading systems need to handle both without treating one as the other.
              </p>
              <p>
                A model can estimate the probability of an outcome. It cannot, by itself,
                decide whether a system should act on that estimate. The order may be too
                large. The market may be too thin. The account may be out of sync. Two
                strategies may have reached opposing conclusions. A useful prediction can
                still produce a bad trade.
              </p>
              <p>
                That distinction is the starting point for Codex Poly Bot. It does not treat
                every signal as a reason to move money. The system must be able to explain
                why it traded, why it refused, and which evidence supported either result.
              </p>

              <section id="question" aria-labelledby="question-title">
                <h2 id="question-title">The question behind the system</h2>
                <p>
                  Automated trading demos tend to focus on the exciting part: a model finds
                  an opportunity and an order appears. The difficult work sits between those
                  two events. Market data has to be current. The opportunity has to be
                  tradable. Independent methods need to agree. Capital limits have to hold
                  across the portfolio. The venue has to confirm what happened.
                </p>
                <p>
                  The design question is straightforward: can a small trading system make
                  the quality of the control path matter as much as the quality of the
                  prediction?
                </p>
                <p>
                  Poly Bot is a working answer. It scans prediction markets on Polymarket
                  and a configured stock and ETF universe through Alpaca. Eligible short
                  entries are available behind a separate disabled-by-default gate. It can
                  run in dry-run mode or submit live orders when the operator has enabled
                  that path. The same decision process applies in both modes.
                </p>
              </section>

              <blockquote>
                A prediction describes what may happen. Authorization decides whether the
                system is permitted to act.
              </blockquote>

              <section id="candidate" aria-labelledby="candidate-title">
                <h2 id="candidate-title">Every opportunity starts as a candidate</h2>
                <p>
                  The main design choice is that a market opportunity enters the system as a
                  candidate, not an instruction. That sounds like a small distinction, but
                  it changes the behavior of the entire application.
                </p>
                <p>
                  A candidate can be rejected before a model sees it because the market is
                  closed, the spread is too wide, liquidity is weak, or the asset is outside
                  the approved universe. It can survive those screens and still stop because
                  a model failed, its confidence was too low, or the model budget was
                  exhausted. It can have a strong probability estimate and still stop
                  because the strategies disagree. It can pass all of that and still fail a
                  risk or account-state check.
                </p>
                <p>
                  Each refusal is recorded with a reason. “No trade” becomes an observable
                  decision instead of an empty space in the activity log.
                </p>
              </section>

              <figure className="story-process-figure" id="process">
                <figcaption>
                  <span>THE DECISION PATH</span>
                  <strong>Evidence becomes exposure through four separate responsibilities.</strong>
                </figcaption>
                <ol>
                  {DECISION_PATH.map((step, index) => (
                    <li key={step.label}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{step.label}</strong>
                        <p>{step.detail}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              </figure>

              <section aria-labelledby="work-title">
                <h2 id="work-title">How the decision is built</h2>
                <p>
                  The process begins with evidence. For Polymarket, that includes current
                  prices, order-book depth, spread, resolution time, market category, and
                  the activity of selected wallets with a repeatable track record. For
                  Alpaca, it includes price action, volume, event context, market hours,
                  liquidity, and the current account state.
                </p>
                <p>
                  Deterministic screens run first. They are cheap, explicit, and easy to
                  audit. A disabled venue, unsupported asset, closed market, weak order
                  book, or excessive estimated slippage should not consume model budget.
                  Removing those candidates early keeps the more expensive reasoning focused
                  on opportunities that could actually become trades.
                </p>
                <p>
                  The candidates that remain receive a probability case. The system records
                  the estimated probability, confidence, thesis, prompt version, provider,
                  and cost. Claude and OpenAI can produce separate decision records. A
                  provider failure does not disappear into a blended score. It remains a
                  failed input.
                </p>
                <p>
                  Focused strategies then evaluate different parts of the case. Arbitrage
                  looks for inconsistent pricing across related outcomes. Convergence looks
                  for the market moving toward the model estimate. Whale-copy logic treats
                  qualified wallet activity as a directional signal. The stock and ETF
                  strategy evaluates its own price, volume, liquidity, and account
                  constraints.
                </p>
                <p>
                  Agreement determines how much of the proposed position can continue. Two
                  or more aligned signals can support a full risk-approved position. One
                  signal supports half. Directional conflict means no trade. Strategy output
                  informs authorization; it does not bypass it.
                </p>
              </section>

              <section id="gates" aria-labelledby="gates-title">
                <h2 id="gates-title">Why the gates matter</h2>
                <p>
                  A good thesis is not enough to place an order. Before live execution, Poly
                  Bot checks the operator, the market data, the model decision, strategy
                  agreement, cumulative risk, and the state of the venue account. Every
                  required gate has to pass.
                </p>
                <p>
                  The risk layer applies position limits, daily-loss limits, allocation
                  limits, open-position limits, market-hours rules, and Alpaca account and
                  borrow eligibility together. Position sizing uses a fractional Kelly calculation
                  as an input, caps the fraction, and then applies the absolute limits. A
                  mathematically attractive size does not override a configured boundary.
                </p>
                <p>
                  Execution has its own boundary. The bot writes an idempotent order intent
                  before submission and reconciles its view with the venue. Unknown or
                  mismatched venue state blocks another order. Reported performance comes
                  from confirmed balances, positions, and fills. Simulated and unfilled
                  orders do not become actual results.
                </p>
              </section>

              <blockquote>
                The goal is not to trade as much as possible. The goal is to know which
                decisions earned the right to run.
              </blockquote>

              <section aria-labelledby="boundaries-title">
                <h2 id="boundaries-title">What the product does not claim</h2>
                <p>
                  Poly Bot does not guarantee returns, and it does not make automated
                  trading safe. Models can be wrong. Historical wallet behavior can stop
                  repeating. Market structure can change faster than a strategy adapts. A
                  valid control path limits how the system acts; it does not remove market
                  risk.
                </p>
                <p>
                  The current Alpaca scope is narrow: long stocks and ETFs plus explicitly
                  enabled easy-to-borrow U.S. equity shorts. Options, crypto, hard-to-borrow
                  locates, margin-funded long purchases, and unsupported asset classes are
                  refused. A venue does not become eligible because credentials exist. The
                  operator must enable it, select the permitted account mode, and set the
                  exposure limits.
                </p>
                <p>
                  Those constraints are part of the product, not temporary obstacles around
                  it. Automation becomes easier to trust when its authority is visible and
                  finite.
                </p>
              </section>

              <section id="try" aria-labelledby="try-title">
                <h2 id="try-title">How to try it</h2>
                <p>
                  The dashboard exposes the current operating mode, candidate funnel, model
                  decisions, refusals, risk settings, audit events, orders, and
                  venue-confirmed results. Start in dry-run mode. Review what the bot would
                  have done, inspect the refusal reasons, and change the limits before
                  considering live execution.
                </p>
                <p>
                  The public product overview contains the interactive five-stage method
                  guide for anyone who wants the algorithm details. Dashboard access uses
                  GitHub to identify approved operators. Market and model credentials are
                  not shared with GitHub.
                </p>

                <div className="story-end-note">
                  <p>
                    Poly Bot is designed to make automated decisions legible. The system can
                    act, but it must also be able to stop, refuse, and explain why.
                  </p>
                  <div className="story-closing-actions">
                    <a
                      className="button primary story-primary-action"
                      href="/api/auth/github/start"
                    >
                      <LogIn size={18} aria-hidden="true" />
                      Continue with GitHub
                      <ArrowRight size={17} aria-hidden="true" />
                    </a>
                    <a href="/#method">
                      Explore the technical methods
                      <ArrowRight size={16} aria-hidden="true" />
                    </a>
                  </div>
                </div>
              </section>
            </div>
          </div>
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
