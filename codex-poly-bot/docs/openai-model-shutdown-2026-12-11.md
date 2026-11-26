# OpenAI model transition for December 11, 2026

This changes model names and request compatibility only. The OpenAI Responses
endpoint, strict scoring and summary schemas, token caps, prompts, venue and
trading controls, and model-budget limits are unchanged.

| Workload | Old selection (including 2025-08-07 snapshot) | Replacement |
| --- | --- | --- |
| Default OpenAI scoring, tick-summary fallback | GPT-5 Mini | `gpt-6.1-terra` |
| Lower-cost scoring option, primary tick summary | GPT-5 Nano | `gpt-6-luna` |

Saved model aliases and snapshots continue to work. All three tick-summary
model settings (primary, fallback, and comma-separated fallback list) are
normalized before duplicate removal. Explicit unrelated tick-summary model IDs
remain unchanged. Historical rows retain their original model IDs and costs.
Scoring's retired `minimal` effort maps to `low`, the lowest supported
nonzero setting. Omitted or supported explicit scoring efforts are preserved.
Tick summary still uses the provider default reasoning effort.

Both replacements support Responses and Structured Outputs. The tick-summary
default estimates use published Standard uncached token rates per million
(input/output): Luna **$0.10/$0.50**, Terra **$1.00/$5.00**. Explicit
`OPENAI_INPUT_COST_PER_MILLION_TOKENS` and
`OPENAI_OUTPUT_COST_PER_MILLION_TOKENS` overrides retain their precedence.
Review any deployment override for stale GPT-5 rates before rollout,
particularly because scoring still uses its existing provider-level rate
configuration and fallback. Do not treat estimated costs as invoices or assume
pricing parity or equivalent scoring behavior.

This change does not activate trading. Before any separately authorized rollout,
review permissions, active model configuration, effective estimates, and budget
impact. Verify the model/schema using a separately approved, synthetic
non-trading request; then compare representative fixtures without passing
results to execution. This patch has no live verification.

Sources: [shutdown schedule](https://developers.openai.com/api/docs/deprecations#upcoming-deprecations),
[Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra),
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
[API pricing](https://developers.openai.com/api/docs/pricing).
