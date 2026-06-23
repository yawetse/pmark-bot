// REQ: REQ-UI-009, REQ-WAL-005

export type WalletCredentialView = {
  id?: string;
  label?: string;
  venue: string;
  provider: string;
  publicIdentifier: string;
  present: boolean;
  status?: string;
  reference?: string;
  message?: string | null;
};

export const DEFAULT_WALLET_CREDENTIALS: WalletCredentialView[] = [
  {
    venue: "polymarket_us",
    provider: "openai",
    publicIdentifier: "not generated",
    present: false,
  },
  {
    venue: "alpaca",
    provider: "claude",
    publicIdentifier: "not connected",
    present: false,
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
