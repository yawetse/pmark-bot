# Codex Poly Bot Deployment Evidence

Captured: 2026-06-22 07:15 America/New_York

## Development

- URL: https://dev-codex-poly-bot.repetere.net
- Health check: `HTTP/2 200` from `https://dev-codex-poly-bot.repetere.net/health`
- Screenshot: [development-home.png](development-home.png)

## Production

- URL: https://codex-poly-bot.repetere.net
- Health check: `HTTP/2 200` from `https://codex-poly-bot.repetere.net/health`
- GitHub OAuth start: `HTTP 307`, client ID present, production callback URL present, no `github_client_id_missing` error
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
- GitHub production OAuth app:
  - Client ID configured in the GitHub `production` environment.
  - Client secret configured in the GitHub `production` environment and deployed to the production stack.
- LLM provider secrets:
  - `/codex-poly-bot/development/openai/api-key`: provider-like key stored
  - `/codex-poly-bot/development/anthropic/api-key`: provider-like key stored
  - `/codex-poly-bot/production/openai/api-key`: provider-like key stored
  - `/codex-poly-bot/production/anthropic/api-key`: provider-like key stored
- SES identity: `asyncdoc.net`
- SES DKIM status: `SUCCESS`
- SES sending verification: `VerifiedForSendingStatus=true`

## Notes

- Both environments terminate HTTPS on the ALB using the issued `*.repetere.net` ACM certificate.
- Route53 aliases are configured for the development and production hostnames.
- The visible app state is the OAuth sign-in screen.
- OpenAI and Anthropic AWS Secrets Manager entries have been replaced with provider-issued API keys.
