# Ticket: per-call-site model routing on the LLM seam

Filed 2026-07-27 (from the 2026-07-20 architecture review, ROADMAP Idea B finding 2 - ROADMAP dissolved into tickets, see git history). Status: idea.

## The problem

Model choice is global: every call uses `config.anthropic_model`.
A one-line edit-summary pass pays the same rate as a full structured plan generation.
Usage accounting (built 2026-07-20, `LlmUsage` table + `/admin`) now makes per-call-site cost visible, so we can see which features deserve a cheaper model.

## Leaning

- A small optional `model`/`tier` arg on the `LLMClient` methods; route cheap deterministic call sites (execution analysis, edit summaries, clean-up passes) to a smaller model, keep the big model for planning + chat.
- `instance_settings` is the natural config home (per the coach-toggles work, docs/adr/0003).
- Couples with [[llm-seam-extraction]]: if the seam extracts first, the tier arg is a library interface change - coordinate.

## Riders (small, same area)

- Confirm the live Anthropic model's rates in `usage.PRICES` (OpenAI rates are real; Anthropic still best-estimate).
- Optional per-request provider tagging (OpenAI `user` / Anthropic `metadata`) as belt-and-braces attribution.
- A usage time-series view if 30-day totals stop being enough.
