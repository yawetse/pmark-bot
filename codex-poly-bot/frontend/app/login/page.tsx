// REQ: REQ-UI-002

type LoginPageProps = {
  searchParams: Promise<{ error?: string }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  return (
    <main className="page-shell">
      <section className="panel" style={{ maxWidth: 560 }}>
        <h1>Sign in to codex-poly-bot</h1>
        <p>GitHub OAuth is required before dashboard views or mutation routes load.</p>
        {params.error ? <p className="status blocked">{params.error}</p> : null}
        <a className="button primary" href="/api/auth/github/start">
          Continue with GitHub
        </a>
      </section>
    </main>
  );
}
