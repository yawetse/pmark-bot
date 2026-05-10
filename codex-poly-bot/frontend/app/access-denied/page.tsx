// REQ: REQ-UI-003

export default function AccessDeniedPage() {
  return (
    <main className="page-shell">
      <section className="panel" style={{ maxWidth: 560 }}>
        <h1>Access denied</h1>
        <p>Your GitHub account is not on the dashboard allowlist.</p>
        <a className="button" href="/login">
          Return to sign in
        </a>
      </section>
    </main>
  );
}
