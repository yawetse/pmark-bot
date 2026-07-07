// REQ: REQ-UI-009, REQ-WAL-005

export type WalletCredentialView = {
  id?: string;
  label?: string;
  venue: string;
  provider: string;
  publicIdentifier: string;
  present: boolean;
  requiredForLive?: boolean;
  status?: string;
  reference?: string;
  message?: string | null;
};

export const DEFAULT_WALLET_CREDENTIALS: WalletCredentialView[] = [
  {
    id: "polymarket_us-openai-wallet",
    label: "Polymarket US / OpenAI",
    venue: "polymarket_us",
    provider: "openai",
    publicIdentifier: "not generated",
    present: false,
    reference: "/codex-poly-bot/local/polymarket_us/openai/wallet",
  },
  {
    id: "polymarket_us-claude-wallet",
    label: "Polymarket US / Claude",
    venue: "polymarket_us",
    provider: "claude",
    publicIdentifier: "not generated",
    present: false,
    reference: "/codex-poly-bot/local/polymarket_us/claude/wallet",
  },
  {
    id: "alpaca-claude-account",
    label: "Alpaca / Claude",
    venue: "alpaca",
    provider: "claude",
    publicIdentifier: "not connected",
    present: false,
    reference: "/codex-poly-bot/local/alpaca/claude/api-key",
  },
  {
    id: "alpaca-openai-account",
    label: "Alpaca / OpenAI",
    venue: "alpaca",
    provider: "openai",
    publicIdentifier: "not connected",
    present: false,
    reference: "/codex-poly-bot/local/alpaca/openai/api-key",
  },
];

export function WalletStatus({
  credentials = DEFAULT_WALLET_CREDENTIALS,
}: {
  credentials?: WalletCredentialView[];
}) {
  return (
    <section className="panel">
      <h2>Wallets And Accounts</h2>
      <ul className="status-list">
        {credentials.map((credential) => (
          <li key={credential.id ?? `${credential.venue}-${credential.provider}`}>
            <span>
              {credential.label ?? `${credential.venue} / ${credential.provider}`}
            </span>
            <span>
              {credential.publicIdentifier}{" "}
              <span className={`status ${credential.present ? "ok" : "blocked"}`}>
                {credential.status ?? (credential.present ? "present" : "missing")}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
