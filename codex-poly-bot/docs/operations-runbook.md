# Operations Runbook

REQ: REQ-DEP-004, REQ-EXE-014, REQ-OBS-005, REQ-WAL-006

Use this runbook for live incidents, degraded health, bad deploys, and credential failures.

## Immediate Stop

1. Activate the kill switch from the dashboard operations view or the live-control API.
2. Verify `LIVE_ENABLED=false` and kill switch state is active for all venues and model providers.
3. Confirm open-order cancellation attempts are recorded for enabled venues.
4. Review recent audit events and system health indicators in the dashboard.

## Credential or Venue Failure

1. Keep live mode disabled for the affected venue.
2. Verify the missing wallet, brokerage, or API credential in AWS Secrets Manager.
3. Confirm the secret path uses the active environment prefix.
4. Rerun dry-run checks before re-enabling venue flags.

## ECS Rollback

Use ECS rollback when a bad deploy affects application code and the database migration is backward compatible.

1. Find the previous healthy task definition revision:

```bash
aws ecs list-task-definitions \
  --family-prefix codex-poly-bot-production-backend \
  --sort DESC
```

2. Update the service to the previous known healthy task definition:

```bash
aws ecs update-service \
  --cluster codex-poly-bot-production-cluster \
  --service codex-poly-bot-production-backend \
  --task-definition codex-poly-bot-production-backend:PREVIOUS_REVISION
```

3. Wait for service stability:

```bash
aws ecs wait services-stable \
  --cluster codex-poly-bot-production-cluster \
  --services codex-poly-bot-production-backend
```

4. Verify dashboard health, recent audit events, and notification delivery.

## RDS Restore Point Guidance

Use RDS restore only when data corruption or an unsafe migration requires database recovery. Prefer a point-in-time restore to a new DB instance, validate it, then cut over through a controlled change.

1. Identify the last known good restore point.
2. Restore the database to a new RDS instance from that restore point.
3. Run schema and smoke checks against the restored instance.
4. Keep live trading disabled until the restored database is verified.
5. Update application configuration to the restored endpoint only after approval.
6. Keep the failed database available for investigation until incident review is complete.

Do not use RDS restore as the first response to a normal application regression. Roll back ECS first when the schema remains compatible.
