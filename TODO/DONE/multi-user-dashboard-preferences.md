# Multi-User Dashboard Preferences

Purpose: close the dashboard bug where user-selected runtime settings and display preferences could be saved but not consistently loaded from the database in a multi-user deployment.

## Scope

- [x] Keep dashboard display preferences scoped by authenticated username and environment.
- [x] Keep runtime config versions scoped by normalized config owner, with shared config as fallback.
- [x] Resolve the scheduler runtime config owner from `RUNTIME_CONFIG_USERNAME`, the single allowlisted user, or the latest active allowlisted user-owned database config.
- [x] Update requirements, test spec, HLD, LLD, task acceptance criteria, and implementation plan.
- [x] Add backend regression coverage for multi-user preference isolation and scheduler owner resolution.

## Evidence

- `uv run pytest tests/spec/test_dashboard_oauth.py tests/spec/test_dashboard_api.py`
- Result: 52 passed.
