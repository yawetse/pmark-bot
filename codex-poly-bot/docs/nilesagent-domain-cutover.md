# Production canonical hostname

The selected production hostname is https://nilesagent.com. Development keeps its current hostname. The existing codex-poly-bot.repetere.net DNS and wildcard certificate remain available for configuration rollback. No repository/resource rename or trading change is included.

The existing listener certificate remains CertificateArn. AdditionalCertificateArn attaches the apex certificate in us-east-1 without removing the wildcard. Production ApplicationDomainName configures both NEXTAUTH_URL and the backend trusted origin. Retain the old exact GitHub OAuth callback while adding the exact nilesagent.com callback in the existing app; do not create credentials or grants.

LegacyApplicationDomainName specifies the old host. EnableLegacyDomainRedirect is false by default so redirects can be enabled after the new host is verified. When enabled, the frontend proxy returns temporary302/no-store only for old-host GET/HEAD navigation. It matches the actual Host header because Next may normalize request.url to an internal listener. API bodies and data routes are not redirected. Old OAuth start/callback navigation returns to new-host login with a fixed domain_changed status; no codes, state, query parameters or cookies cross hosts. Existing host-only sessions require new-host sign-in.

Rollback restores the prior ApplicationDomainName, disables redirects, restores the prior task/image/configuration, and preserves the old DNS/certificate/callback. DNS alone does not roll back authentication. Do not remove the old mapping or cache permanent redirects during this transition.
