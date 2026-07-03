import Link from "next/link";

import type { StatusItem } from "@/components/dashboard/status-overview";
import {
  DEFAULT_WALLET_CREDENTIALS,
  type WalletCredentialView,
} from "@/components/dashboard/wallet-status";

// REQ: REQ-UI-004, REQ-UI-009, REQ-OBS-005

type GuideStep = {
  title: string;
  body: string;
  meta?: string;
};

export function GettingStartedGuide({
  credentials = DEFAULT_WALLET_CREDENTIALS,
  statusItems = [],
}: {
  credentials?: WalletCredentialView[];
  statusItems?: StatusItem[];
}) {
  const blockedSteps = buildBlockedCredentialSteps(credentials);
  const tradingLoop = statusItems.find((item) => item.label === "Trading loop");
  const worker = statusItems.find((item) => item.label === "Ingestion");
  const notification = statusItems.find((item) => item.label === "Notification");
  const llmCredentials = credentials.filter(
    (credential) => credential.venue === "llm" && credential.present,
  );
  const llmLabels = llmCredentials.map(
    (credential) => credential.label ?? credential.publicIdentifier,
  );
  const isLiveBlocked =
    blockedSteps.length > 0 || tradingLoop?.state === "blocked";

  return (
    <section className="panel setup-guide" aria-labelledby="getting-started-title">
      <div className="guide-heading">
        <div>
          <h2 id="getting-started-title">Getting Started</h2>
          <p>
            Trading is not running because live execution is still gated. The app can
            monitor the environment, show account readiness, and keep the operator
            notified while the remaining setup items are finished.
          </p>
        </div>
        <span className={`status ${isLiveBlocked ? "blocked" : "ok"}`}>
          {isLiveBlocked ? "action needed" : "ready for signoff"}
        </span>
      </div>

      <div className="guide-columns">
        <div className="guide-section">
          <h3>What is working now</h3>
          <ul className="guide-list">
            <li>{worker ? formatStatus(worker) : "Scheduler status is loading."}</li>
            <li>
              {notification
                ? formatStatus(notification)
                : "Notification status is loading."}
            </li>
            <li>
              {llmLabels.length > 0
                ? `${llmLabels.join(" and ")} are configured.`
                : "LLM API readiness is loading."}
            </li>
          </ul>
        </div>

        <div className="guide-section">
          <h3>Why trading has not started</h3>
          <ul className="guide-list">
            {blockedSteps.map((step) => (
              <li key={step.title}>
                <strong>{step.title}</strong>
                <span>{step.body}</span>
                {step.meta ? <small>{step.meta}</small> : null}
              </li>
            ))}
            {tradingLoop?.state === "blocked" ? (
              <li>
                <strong>Live trading gate</strong>
                <span>
                  Complete the live-trading checklist, including simulation evidence,
                  risk limits, emergency-stop test, SES recipient approval, and operator
                  signoff.
                </span>
                <small>Checklist: codex-poly-bot/docs/live-trading-checklist.md</small>
              </li>
            ) : null}
          </ul>
        </div>
      </div>

      <div className="guide-section next-steps">
        <h3>Next steps</h3>
        <ol className="step-list">
          <li>
            <strong>Keep production in monitor mode.</strong>
            <span>
              Use the dashboard to confirm ingestion, notifications, and account status.
              Live orders should stay gated until every blocker is cleared.
            </span>
          </li>
          <li>
            <strong>Finish account credentials outside the app.</strong>
            <span>
              Add the missing production credential values in AWS Secrets Manager, then
              redeploy production so the status rows refresh.
            </span>
          </li>
          <li>
            <strong>Use the control pages before enabling live trading.</strong>
            <span>
              Review risk settings in Settings, then use Run to confirm the emergency
              stop and manual-review state before operator signoff.
            </span>
          </li>
        </ol>
        <div className="guide-actions" aria-label="Dashboard next step links">
          <Link className="button" href="/dashboard/config">
            Review settings
          </Link>
          <Link className="button" href="/dashboard/operations">
            Open run
          </Link>
        </div>
      </div>
    </section>
  );
}

function buildBlockedCredentialSteps(
  credentials: WalletCredentialView[],
): GuideStep[] {
  const steps: GuideStep[] = [];
  const polymarket = credentials.find((credential) =>
    credential.venue.includes("polymarket"),
  );
  const alpaca = credentials.find((credential) => credential.venue === "alpaca");

  if (polymarket && !polymarket.present) {
    steps.push({
      title: "Polymarket wallet",
      body:
        polymarket.message ||
        "A required production Polymarket credential value is missing.",
      meta: `Reference: ${polymarket.reference ?? "/codex-poly-bot/production/polymarket"}`,
    });
  }

  if (alpaca && !alpaca.present) {
    const status = (alpaca.status ?? "").toLowerCase();
    steps.push({
      title: "Alpaca account",
      body:
        status === "reviewing"
          ? "The live Alpaca account is still under review. Wait for approval before live Alpaca trading."
          : alpaca.message || "Production Alpaca credentials are not ready.",
      meta: `Reference: ${alpaca.reference ?? "/codex-poly-bot/production/alpaca"}`,
    });
  }

  return steps;
}

function formatStatus(item: StatusItem): string {
  return `${item.label}: ${item.value}.`;
}
