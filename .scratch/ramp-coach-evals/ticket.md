# Ticket: eval cases for the coach's ramp-guardrail behavior

Filed 2026-07-27 (open item from the 2026-07-21 ramp build, ROADMAP Idea E - ROADMAP dissolved into tickets, see git history). Status: ready.

## The gap

`metrics.ramp_signal` (ACWR zones + chronic trend + forward projection) is unit-tested (`test_ramp.py`, 13 cases), and the REVIEW/author prompts carry ramp rules - but there are no evals protecting the coach's *behavior* on ramp signals.
Nothing catches a prompt regression where the coach stops trimming a high-ramp week or starts alarming on one down week.

## The work

Seeded ramping/detraining athletes through the layer 3-4 eval machinery (`pytest -m eval`), per the `add-eval-case` skill:

- High ramp + planned hard week → proposes trimming, protects the long run (trajectory: a proposal exists; judge: names the ramp warmly, no raw ratios in the note).
- Detraining + upcoming race → gentle-rebuild note, no alarm.
- One down week (travel) → no proposal, no alarm (anti-churn).

## Rider

Per-athlete threshold tuning if the feedback loop (COACH_QUALITY.md) shows the band nagging - data-driven, wait for signal.
