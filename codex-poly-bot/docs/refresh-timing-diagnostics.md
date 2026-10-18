# Temporary portfolio refresh timing diagnostic

This diagnostic is off unless `PORTFOLIO_REFRESH_DIAGNOSTICS_UNTIL` is set to a
future timezone-aware UTC timestamp. The backend clamps the activation to at
most 24 hours from process start. The deploy script and CloudFormation expose
the value as an optional parameter; GitHub Actions reads it from the matching
environment variable. The default is empty in every environment.

While active, each existing post-funding heartbeat gains `refreshTiming` with
whole-millisecond durations for the portfolio refresh, config reload, funding
tick, and full cycle, plus a fixed `ok`/`failed` refresh outcome. The heartbeat
is still written at the same point. A slow phase (at least 90 seconds) or a
failed phase can also emit a line with only phase name, outcome, and elapsed
milliseconds. A portfolio refresh or funding tick still running after 90
seconds emits the same bounded signal with outcome `running`, even if its
provider call never returns. These lines are limited to one per 15 minutes and
96 per process.
No account identifiers, financial amounts, credentials, endpoint URLs, or
exception text are added to diagnostic telemetry.

The diagnostic does not change the refresh interval, scheduler cadence,
heartbeat age threshold, provider calls, funding decisions, or trading flags.
A phase that never returns cannot produce a completion duration. The watchdog
still identifies an in-flight refresh or funding tick. The synchronous config
reload cannot emit a slow warning until it returns. Review that limit before
enabling in production.

For a reviewed rollout, set a single absolute UTC expiry no more than 24 hours
ahead in the production GitHub environment variable, deploy, and verify the
CloudFormation parameter and ECS environment value by name and timestamp.
After the window, clear the variable in the same environment and deploy again.
Do not publish account-level values or log bodies in the review record.
Merging this patch to `main` itself triggers the production workflow even with
the diagnostic disabled. Setting the GitHub variable alone does not redeploy
ECS; activation and removal each need a controlled deployment.
