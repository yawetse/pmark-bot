// REQ: REQ-UI-009, REQ-WAL-005

export type WalletCredentialView = {
  venue: string;
  provider: string;
  publicIdentifier: string;
  present: boolean;
};

const WALLET_CREDENTIALS: WalletCredentialView[] = [
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

export function WalletStatus() {
  return (
    <section className="panel">
      <h2>Wallets And Accounts</h2>
      <ul className="status-list">
        {WALLET_CREDENTIALS.map((credential) => (
          <li key={`${credential.venue}-${credential.provider}`}>
            <span>
              {credential.venue} / {credential.provider}
            </span>
            <span>
              {credential.publicIdentifier}{" "}
              <span className={`status ${credential.present ? "ok" : "blocked"}`}>
                {credential.present ? "present" : "missing"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
