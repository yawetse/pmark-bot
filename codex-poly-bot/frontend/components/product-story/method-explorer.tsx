"use client";

// REQ: REQ-UI-023

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  BrainCircuit,
  Database,
  GitBranch,
  MonitorCheck,
  SearchCheck,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Algorithm = {
  name: string;
  description: string;
};

type MethodStep = {
  number: string;
  title: string;
  summary: string;
  output: string;
  icon: LucideIcon;
  inputs: string[];
  algorithms: Algorithm[];
  decisionRule: string;
  operatorControl: string;
};

const METHOD_STEPS: MethodStep[] = [
  {
    number: "01",
    title: "Find repeatable behavior",
    summary:
      "Use historical trades to identify wallets and market patterns with a record worth following.",
    output: "Target wallet cohort",
    icon: Database,
    inputs: [
      "Normalized fills",
      "Closed positions",
      "Realized P&L",
      "Win rate",
      "Market category",
    ],
    algorithms: [
      {
        name: "Qualification floor",
        description:
          "Start with wallets that have at least 100 completed trades and a win rate above 70 percent.",
      },
      {
        name: "Profit ranking",
        description:
          "Rank qualifying wallets by realized P&L so a high hit rate with weak returns does not dominate.",
      },
      {
        name: "Category fit",
        description:
          "Measure results by category. A wallet that performs well in crypto does not become a signal for every market.",
      },
      {
        name: "Cohort overlap",
        description:
          "Count when several target wallets take the same side of the same market.",
      },
    ],
    decisionRule:
      "Wallet activity contributes evidence. It never authorizes an order by itself.",
    operatorControl:
      "The operator controls target wallets, qualification thresholds, categories, and history windows.",
  },
  {
    number: "02",
    title: "Remove weak candidates",
    summary:
      "Apply deterministic screens before model scoring so cost and attention stay on credible opportunities.",
    output: "Accepted queue or refusal",
    icon: SearchCheck,
    inputs: [
      "Active markets",
      "Bid and ask depth",
      "Spread",
      "Resolution time",
      "Tradable symbols",
    ],
    algorithms: [
      {
        name: "Venue eligibility",
        description:
          "Reject disabled venues, closed markets, unsupported assets, halted symbols, and candidates outside trading hours.",
      },
      {
        name: "Order-book screen",
        description:
          "Require configured liquidity and depth while keeping spread and estimated slippage inside their limits.",
      },
      {
        name: "Resolution window",
        description:
          "Keep Polymarket candidates inside the configured time window. The seeded scanner range is 4 to 168 hours.",
      },
      {
        name: "Stock universe",
        description:
          "Limit Alpaca candidates to the configured long-only stock and ETF universe.",
      },
    ],
    decisionRule:
      "Rejected candidates are recorded with a reason and never consume model budget in that loop.",
    operatorControl:
      "The operator can change liquidity, spread, timing, category, and symbol-universe rules.",
  },
  {
    number: "03",
    title: "Build the probability case",
    summary:
      "Evaluate each survivor from several angles and record the probability, confidence, thesis, and cost.",
    output: "Provider decision record",
    icon: BrainCircuit,
    inputs: [
      "Candidate metrics",
      "Historical base rates",
      "Recent context",
      "Wallet overlap",
      "Model budget",
    ],
    algorithms: [
      {
        name: "Base rate",
        description:
          "Compare the candidate with historical outcomes for similar events or market conditions.",
      },
      {
        name: "Recent context",
        description:
          "Check whether new information changes the case implied by historical behavior.",
      },
      {
        name: "Target-wallet check",
        description:
          "Measure whether qualified wallets are aligned with the candidate and on which side.",
      },
      {
        name: "Disposition check",
        description:
          "Look for pricing behavior tied to recency, anchoring, crowding, or another known decision bias.",
      },
      {
        name: "Independent provider scoring",
        description:
          "Claude and OpenAI produce separate records with their own prompt version, budget, probability, and confidence.",
      },
    ],
    decisionRule:
      "A provider failure, exhausted budget, or missing score blocks that provider from creating an order.",
    operatorControl:
      "The operator controls provider budgets, confidence rules, prompts, and enabled reasoning checks.",
  },
  {
    number: "04",
    title: "Form a trade decision",
    summary:
      "Run focused strategies independently, then use agreement strength to determine whether a trade can continue.",
    output: "Full, half, or no position",
    icon: GitBranch,
    inputs: [
      "Model probability",
      "Market price",
      "Related markets",
      "Target-wallet activity",
      "Price direction",
    ],
    algorithms: [
      {
        name: "Arbitrage",
        description:
          "Detect inconsistent prices across related outcomes or markets where the combined pricing creates an edge.",
      },
      {
        name: "Convergence",
        description:
          "Look for price movement that is closing the gap between the market and the model estimate.",
      },
      {
        name: "Whale copy",
        description:
          "Use configured target-wallet activity and delay rules as a directional signal.",
      },
      {
        name: "Stock and ETF signal",
        description:
          "Evaluate price action, volume, event context, liquidity, account state, and long-only constraints for Alpaca.",
      },
    ],
    decisionRule:
      "Two or more aligned signals allow a full risk-approved position. One allows half. Directional conflict means no trade.",
    operatorControl:
      "The operator controls which strategies run, their thresholds, and the consensus rule.",
  },
  {
    number: "05",
    title: "Size, submit, and monitor",
    summary:
      "Turn an approved decision into bounded exposure, then watch confirmed positions for a reason to exit.",
    output: "Order intent and position lifecycle",
    icon: MonitorCheck,
    inputs: [
      "Estimated probability",
      "Market price",
      "Available capital",
      "Open positions",
      "Venue state",
    ],
    algorithms: [
      {
        name: "Fractional Kelly",
        description:
          "Calculate a Kelly-based size and cap the fraction at 0.25 before applying absolute risk limits.",
      },
      {
        name: "Cumulative risk limits",
        description:
          "Apply position, daily-loss, allocation, open-position, market-hours, and long-only limits together.",
      },
      {
        name: "Slippage protection",
        description:
          "Estimate execution impact from current market data and refuse orders outside the venue limit.",
      },
      {
        name: "Position lifecycle",
        description:
          "Monitor targets, stops, volume changes, stale theses, fills, venue state, and reconciliation until exit.",
      },
    ],
    decisionRule:
      "The bot writes an idempotent order intent before submission. Unknown or mismatched venue state blocks another order.",
    operatorControl:
      "The operator controls dry-run or live mode, risk caps, exit rules, and the emergency stop.",
  },
];

export function MethodExplorer() {
  return (
    <div className="method-track">
      {METHOD_STEPS.map((step) => {
        const Icon = step.icon;
        const descriptionId = `method-dialog-description-${step.number}`;

        return (
          <Dialog.Root key={step.number}>
            <article className="method-step">
              <div className="method-step-top">
                <span>{step.number}</span>
                <Icon size={21} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <h3>{step.title}</h3>
              <p>{step.summary}</p>
              <div className="method-step-output">
                <span>Produces</span>
                <strong>{step.output}</strong>
              </div>
              <Dialog.Trigger asChild>
                <button
                  className="method-step-trigger"
                  type="button"
                  aria-label={`Explore ${step.title}`}
                >
                  Explore the method
                  <ArrowUpRight size={16} aria-hidden="true" />
                </button>
              </Dialog.Trigger>
            </article>

            <Dialog.Portal>
              <Dialog.Overlay className="method-dialog-overlay" />
              <Dialog.Content
                className="method-dialog"
                aria-describedby={descriptionId}
              >
                <div className="method-dialog-header">
                  <div>
                    <p className="method-dialog-phase">STAGE {step.number} OF 05</p>
                    <Dialog.Title>{step.title}</Dialog.Title>
                    <Dialog.Description id={descriptionId}>
                      {step.summary}
                    </Dialog.Description>
                  </div>
                  <Dialog.Close asChild>
                    <button
                      className="method-dialog-close"
                      type="button"
                      aria-label={`Close ${step.title} details`}
                    >
                      <X size={19} aria-hidden="true" />
                    </button>
                  </Dialog.Close>
                </div>

                <div className="method-dialog-route" aria-label={`${step.title} data flow`}>
                  <div>
                    <span>Inputs</span>
                    <strong>{step.inputs.length} evidence groups</strong>
                  </div>
                  <ArrowUpRight size={18} aria-hidden="true" />
                  <div>
                    <span>Method</span>
                    <strong>{step.algorithms.length} decision checks</strong>
                  </div>
                  <ArrowUpRight size={18} aria-hidden="true" />
                  <div>
                    <span>Output</span>
                    <strong>{step.output}</strong>
                  </div>
                </div>

                <section className="method-dialog-section" aria-labelledby={`inputs-${step.number}`}>
                  <h3 id={`inputs-${step.number}`}>Evidence used</h3>
                  <div className="method-dialog-pills">
                    {step.inputs.map((input) => (
                      <span key={input}>{input}</span>
                    ))}
                  </div>
                </section>

                <section className="method-dialog-section" aria-labelledby={`algorithms-${step.number}`}>
                  <h3 id={`algorithms-${step.number}`}>Strategies and algorithms</h3>
                  <div className="method-dialog-algorithms">
                    {step.algorithms.map((algorithm, index) => (
                      <article key={algorithm.name}>
                        <span>{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <h4>{algorithm.name}</h4>
                          <p>{algorithm.description}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <div className="method-dialog-rule">
                  <span>DECISION RULE</span>
                  <strong>{step.decisionRule}</strong>
                </div>

                <div className="method-dialog-operator">
                  <span>Operator control</span>
                  <p>{step.operatorControl}</p>
                </div>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        );
      })}
    </div>
  );
}
