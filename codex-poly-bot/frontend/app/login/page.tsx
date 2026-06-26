// REQ: REQ-UI-002

type LoginPageProps = {
  searchParams: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  return (
    <main className="page-shell auth-shell">
      <section className="panel auth-panel">
        <p className="section-label">Operator access</p>
        <h1>Sign In To Codex Poly Bot</h1>
        <p className="panel-note">
          GitHub OAuth is required before dashboard views or mutation routes load.
        </p>
        {params.error ? <p className="status-message blocked">{params.error}</p> : null}
        <a className="button primary" href="/api/auth/github/start">
          Continue with GitHub
        </a>
      </section>
    </main>
  );
}
