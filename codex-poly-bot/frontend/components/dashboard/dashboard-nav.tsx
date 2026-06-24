// REQ: REQ-UI-004, REQ-UI-008, REQ-UI-010, REQ-UI-011

export function DashboardNav() {
  return (
    <header className="topbar">
      <div className="brand">codex-poly-bot</div>
      <nav className="nav" aria-label="Dashboard">
        <a href="/dashboard">Status</a>
        <a href="/dashboard/config">Config</a>
        <a href="/dashboard/models/claude">Claude</a>
        <a href="/dashboard/models/openai">OpenAI</a>
        <a href="/dashboard/comparison">Comparison</a>
        <a href="/dashboard/operations">Operations</a>
        <a href="/dashboard/system">System</a>
        <a href="/dashboard/help">Help</a>
      </nav>
    </header>
  );
}
