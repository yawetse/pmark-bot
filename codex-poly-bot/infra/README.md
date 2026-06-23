# Infrastructure

CloudFormation defines the AWS deployment contract for `codex-poly-bot`.

- Region: `us-east-1`
- Compute: ECS Fargate
- Images: ECR backend and frontend repositories
- Data: RDS Postgres and S3 snapshots
- Secrets: environment-scoped AWS Secrets Manager paths
- Notifications: SES email identity
- Observability: CloudWatch Logs
- HTTPS: optional custom hostname with ACM certificate and ALB redirect

The task role can read only `/codex-poly-bot/${EnvironmentName}/...` secrets. The task execution role can read the same prefix for ECS secret injection. S3 lifecycle rules retain raw snapshots for 365 days and normalized snapshots for 730 days.

Runtime profile parameters control live trading and venue enablement:

- Development: `TradingAccountMode=paper`, `LiveEnabled=false`, `AlpacaEnabled=true`, Polymarket disabled.
- Production: `TradingAccountMode=live`, `LiveEnabled=true`, `PolymarketUsEnabled=true`, `AlpacaEnabled=true`.

Pass the matching values from `parameters/dev.json` or `parameters/prod.json` when creating or updating the CloudFormation stack.

Use the shared deploy helper locally or in GitHub Actions:

```bash
./codex-poly-bot/scripts/deploy-stack.sh development
./codex-poly-bot/scripts/deploy-stack.sh production
```

The script reads VPC, subnet, domain, certificate, GitHub OAuth, and generated secret parameters from environment variables. GitHub Actions uses the same script before publishing ECR images so a new stack has repositories before the image push runs.
