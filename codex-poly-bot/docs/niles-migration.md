# niles identity migration

niles is the website, software project, and project agent name. This change updates visible product copy, page metadata, package metadata, agent instructions, and CI display names. Existing deployment identifiers remain compatibility names until the infrastructure migration is reviewed and authorized.

## Current source and deployment

The repository is [yawetse/pmark-bot](https://github.com/yawetse/pmark-bot). Current production source history points to main commit `3fd6cf56ed2c440e4fccc886d8878d05187e3177`, with [successful workflow 31030382416](https://github.com/yawetse/pmark-bot/actions/runs/31030382416). That workflow evidence does not independently attest the currently running image.

## Coordinated technical migration

| Surface | Current compatibility name | Proposed name and required checks |
| --- | --- | --- |
| Codex saved project | pmark-bot | niles; change its display label through supported UI and preserve project path and chat association |
| GitHub repository | yawetse/pmark-bot | yawetse/niles; review integrations, redirects, remotes, branch protections, Actions environments, and external links before repository rename |
| Source directory | codex-poly-bot | niles; migrate build contexts, scripts, Docker Compose mounts, tests, and documentation together |
| Workflow filename | codex-poly-bot-ci.yml | niles-ci.yml; audit workflow references and badge links; current CI display name becomes niles CI |
| Production and development domains | codex-poly-bot.repetere.net and dev-codex-poly-bot.repetere.net | selected production nilesagent.com; retain current development hostname and old production hostname for rollback; verify DNS, TLS, exact OAuth callbacks, origins, cookies and realtime routes before cutover |
| AWS stacks, ECS services, ECR images, database and storage names | codex-poly-bot prefixes | niles prefixes; review resource replacements and data migration, costs, rollback, and release gates before applying |
| Secret references | /codex-poly-bot/{environment}/... | keep current paths until an approved migration verifies every consumer; never copy values into issues, code, or logs |
| Observability namespace and services | codex-poly-bot namespace and service labels | migrate dashboards, alert rules, export configuration, and historical continuity together |
| Browser preference key | codex-poly-bot-theme | retain to preserve saved preferences; a future key migration must read existing values before writing the new key |
| Historical specs and evidence | SPEC-CODEX-POLY-BOT, REQ identifiers, old screenshots and reports | retain immutable identifiers and historical evidence; active project name is niles |

Repository/resource renames remain separate. The production hostname cutover uses the existing nilesagent.com zone and existing hosting; see `nilesagent-domain-cutover.md`. Trading settings, funding behavior, order execution, and financial safety gates are unchanged.

## Remaining work

[Issue 272](https://github.com/yawetse/pmark-bot/issues/272) tracks the consolidated backlog, supported chat-history reconciliation, and reversible local cleanup. Before external cutover, confirm the migration scope and cost, validate authentication and read-only dashboard routes in a preview, then approve the specific deployment and account changes.
