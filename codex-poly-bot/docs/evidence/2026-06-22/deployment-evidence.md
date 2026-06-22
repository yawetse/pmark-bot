# Codex Poly Bot Deployment Evidence

Captured: 2026-06-22 01:12 America/New_York

## Development

- URL: https://dev-codex-poly-bot.repetere.net
- Health check: `HTTP/2 200` from `https://dev-codex-poly-bot.repetere.net/health`
- Screenshot: [development-home.png](development-home.png)

## Production

- URL: https://codex-poly-bot.repetere.net
- Health check: `HTTP/2 200` from `https://codex-poly-bot.repetere.net/health`
- Screenshot: [production-home.png](production-home.png)

## AWS State

- AWS account: `506304330252`
- Region: `us-east-1`
- Development stack: `codex-poly-bot-development`
- Production stack: `codex-poly-bot-production`
- Production stack status: `UPDATE_COMPLETE`
- Production ECS services:
  - `codex-poly-bot-production-backend`: desired `1`, running `1`
  - `codex-poly-bot-production-frontend`: desired `1`, running `1`
- SES identity: `asyncdoc.net`
- SES DKIM status: `SUCCESS`
- SES sending verification: `VerifiedForSendingStatus=true`

## Notes

- Both environments terminate HTTPS on the ALB using the issued `*.repetere.net` ACM certificate.
- Route53 aliases are configured for the development and production hostnames.
- The visible app state is the OAuth sign-in screen. Dashboard access depends on the GitHub OAuth app callback configuration and secrets.
- OpenAI and Anthropic AWS Secrets Manager entries exist. Replace the CloudFormation placeholder values with provider-issued API keys before using model-backed workflows.
