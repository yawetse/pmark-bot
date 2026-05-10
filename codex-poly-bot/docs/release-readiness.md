# Release Readiness

REQ: REQ-DEP-005, REQ-OBS-001, REQ-OBS-003, REQ-OBS-004, REQ-OBS-005, REQ-OBS-006

## Automated Checks

| Area | Status | Evidence |
|------|--------|----------|
| Traceability | Pass | `scan_traceability()` checks every declared `REQ-*` for at least one spec test and one implementation or approved design trace. |
| Pending spec tests | Pass | `scan_traceability()` fails if any `pending(` call remains in spec test files. |
| Audit | Pass | Audit coverage is required for live order events and dashboard mutations. |
| Health | Pass | Health coverage is required for dashboard observability and degraded worker status. |
| Deployment | Pass | CI test gates, AWS infrastructure, and dev/prod separation are checked before deployment readiness passes. |
| Live trading safety | Deferred | Live enablement remains deferred until production credentials, account approvals, account reconciliation evidence, and operator signoff are configured. |

## Release Gate

Release review passes only when readiness checks are `pass` or explicitly `deferred`.
Any `fail` status blocks release until the missing test, trace, deployment check, or safety decision is corrected.
