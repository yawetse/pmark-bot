# Infrastructure

CloudFormation defines the AWS deployment contract for `codex-poly-bot`.

- Region: `us-east-1`
- Compute: ECS Fargate
- Images: ECR backend and frontend repositories
- Data: RDS Postgres and S3 snapshots
- Secrets: environment-scoped AWS Secrets Manager paths
- Notifications: SES email identity
- Observability: CloudWatch Logs

The task role can read only `/codex-poly-bot/${EnvironmentName}/...` secrets. S3 lifecycle rules retain raw snapshots for 365 days and normalized snapshots for 730 days.
