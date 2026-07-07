# Model Provider Account Matrix

Purpose: support separate live account slots for `polymarket_us / openai`, `polymarket_us / claude`, `alpaca / openai`, and `alpaca / claude` so model performance can be compared without sharing trading credentials.

- [x] Add dashboard credential rows for all four venue/provider account combinations.
- [x] Gate live entry orders by `venue:model_provider` credential status.
- [x] Route live entry orders through provider-specific venue submitters.
- [x] Add optional ECS secret injection for provider-specific Polymarket and Alpaca variables.
- [x] Update local env placeholders, env sync mapping, docs, requirements, tests, and task traceability.
- [x] Preserve the rule that secret values, private keys, API keys, seed phrases, and raw `.env` values are not displayed or copied by automation.

