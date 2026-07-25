import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  ShieldAlert,
} from "lucide-react";

import { MethodExplorer } from "@/components/product-story/method-explorer";

// REQ: REQ-UI-016, REQ-UI-023

const FAQS = [
  {
    question: "Can the bot place real trades?",
    answer: "Only when real-money mode is enabled and the venue, credentials, market hours, risk checks, and emergency stop all permit the order. Simulation remains the safe default.",
  },
  {
    question: "Why did the latest check place no trade?",
    answer: "Open Activity to see where the latest candidates stopped. A market filter, confidence rule, strategy vote, risk rule, venue condition, or disabled live setting can stop an order.",
  },
  {
    question: "Where are confirmed results?",
    answer: "Performance uses venue-confirmed balances, positions, and fills. It excludes practice and unfilled orders and marks missing financial data unavailable.",
  },
  {
    question: "What does unavailable mean?",
    answer: "The app does not have an authoritative value for that item. It shows unavailable instead of substituting zero or inferring a financial result from incomplete records.",
  },
  {
    question: "How do I stop new orders?",
    answer: "Open detailed Operations from Activity or Settings and use the emergency stop. The control applies across models and venues.",
  },
] as const;

export function HelpAboutView() {
  return (
    <div className="ia-page help-page" aria-labelledby="help-title">
      <header className="ia-page-heading help-heading">
        <div>
          <p className="section-label">Help</p>
          <h1 id="help-title">Understand every decision</h1>
          <p>Inspect how Codex Poly Bot finds evidence, narrows candidates, makes decisions, and controls exposure.</p>
        </div>
        <CircleHelp aria-hidden="true" size={30} />
      </header>

      <section className="ia-panel help-process help-method-guide" aria-labelledby="help-process-title">
        <div className="ia-section-heading">
          <div>
            <p className="section-label">Decision engine</p>
            <h2 id="help-process-title">Five stages, with the details behind each one</h2>
            <p>Open a stage for its inputs, strategies, decision rule, output, and operator controls.</p>
          </div>
        </div>
        <MethodExplorer />
      </section>

      <section className="ia-panel help-faq" aria-labelledby="help-faq-title">
        <div className="ia-section-heading"><div><p className="section-label">Questions</p><h2 id="help-faq-title">Common questions</h2></div></div>
        <div className="help-faq-list">
          {FAQS.map((faq, index) => (
            <details key={faq.question} open={index === 0}>
              <summary>{faq.question}<ArrowRight aria-hidden="true" size={16} /></summary>
              <p>{faq.answer}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="help-safety-note" aria-labelledby="help-safety-title">
        <ShieldAlert aria-hidden="true" size={21} />
        <div><strong id="help-safety-title">Real-money safety</strong><p>Turning on real-money mode does not bypass the other gates. Use the emergency stop in detailed Operations when new order handling must stop.</p></div>
        <Link href="/dashboard/operations">Open operations <ArrowRight aria-hidden="true" size={15} /></Link>
      </section>

      <Link className="button subtle help-back-link" href="/dashboard"><ArrowLeft aria-hidden="true" size={15} />Back to Overview</Link>
    </div>
  );
}
