# Ticket: the forward plan generator ignores the menstrual cycle

Filed 2026-07-30 off a real user report: an author-mode athlete's tracked cycle is noted by the app but the coach never gives her chiller workouts around her upcoming period.
Status: ready to build - decisions grilled and locked 2026-07-31; snapshot plumbing + prompt block + one pytest + two eval cases.

## Problem Statement

Cycle handling is instruction-complete in only one of the two coach paths.

The cycle signal is computed once and injected into a shared snapshot that feeds every plan-writing LLM call.
`build_snapshot` puts `menstrual_cycle` (from `metrics.cycle_phase`, which emits `phase`, `ease_recommended`, `days_to_next_period`, etc.) into the JSON at `planner.py:560`.
So the data reaches every call site identically.

But only the daily *review* system prompt tells the model what to do with it.
`REVIEW_SYSTEM_PROMPT` (`planner.py:1475-1486`) spells out the easing/green-lighting guidance: soften a prescribed hard session when `ease_recommended` is true, green-light quality in `follicular` when readiness is good, mention it warmly in the coach note.
The forward plan generator's `SYSTEM_PROMPT` (`planner.py:145-241`) never mentions the cycle at all.
The field rides along in the JSON payload with no instruction, so the model treats it as noise and writes a normal week.

A second gap found during grilling: the snapshot's `menstrual_cycle` is computed for **today only**.
The forward generator writes 7 days ahead, so even with prompt guidance it would have to derive future ease days by date arithmetic off `next_period_date` - exactly the silent-failure math LLMs get wrong.

### Why author-mode users get nothing

For editor-mode users this is a narrow gap - only the forward-authored week misses the cycle; the daily review (running `REVIEW_SYSTEM_PROMPT`) still softens same-day.

For **author-mode** users the guidance fires in **neither** path, because the daily review delegates author-mode week-writing straight back to the cycle-blind generator:

```python
# _evaluate_today_locked, planner.py:1682-1683
if mode == "author":
    changed = generate_plan(db, user_id, source="daily_review")  # -> SYSTEM_PROMPT, no cycle guidance
```

So for an author-mode athlete:
- forward daily-job generation -> `generate_plan` -> `SYSTEM_PROMPT` (cycle-blind)
- daily review -> `generate_plan` -> `SYSTEM_PROMPT` (cycle-blind)

The cycle data is computed, stored, and shown in the UI correctly, then ignored by every LLM call that touches the plan.
That is exactly the reported symptom: the app "notes down" the cycle but never eases the workouts.

## Decisions (grilled 2026-07-31)

1. **Plumb per-day cycle data; no prompt date math.**
   `build_snapshot` adds an `upcoming` list inside `menstrual_cycle`: for each of the next 7 dates, `{date, phase, ease_recommended}` computed by looping the pure-arithmetic `metrics.cycle_phase`.
   The model never derives a date; code produces the fact, the LLM obeys it - the same trust boundary `cycle_phase`'s docstring already commits to.
   The review call sees the new field too (shared snapshot); that is additive and harmless, and `REVIEW_SYSTEM_PROMPT` is untouched.
2. **Flag-only easing, no extra placement bias.**
   The prompt says: no quality session or the week's hardest long run on a day where `upcoming[].ease_recommended` is true; prefer easy/recovery there; on a very low-readiness early-flow day consider rest.
   No "keep hard days away from the window" language - `ease_recommended` already covers the premenstrual days plus early flow, which is the whole physiological window, and days ~4+ before the period need no easing.
3. **Two hand-maintained wordings, not a shared constant.**
   The review block reasons about today's single dict; the generator block reasons about the 7-day `upcoming` list - a shared constant would be mushy or hole-ridden.
   Drift is guarded by the ease window living in `metrics.cycle_phase` code and by eval cases on the forward path.
4. **Follicular green-light carries the niggle veto.**
   Confident quality placement in `follicular` applies only when readiness is good AND nothing severity >= 2 is open, mirroring the review prompt's "pain outranks green-light" ordering (`planner.py:1494-1496`).
   The broader gap - `SYSTEM_PROMPT` has no run-planning niggle guidance at all - is filed separately as [forward-prompt-niggle-guidance](../forward-prompt-niggle-guidance/ticket.md).
5. **Interaction with the daily review is compositional, not conflicting.**
   Both paths read the same deterministic flag in the same direction; the review's anti-churn rule makes it a no-op safety net once the generator complies; author mode has only one decision-maker anyway.

Keep the block a gentle bias, not a hard rule: don't churn a sound plan, don't invent hard work the plan doesn't need, and let the day rationale carry it with care and warmth, never clinically.

## Test

- **Layer 1 (free, deterministic):** pytest for the snapshot plumbing - `upcoming` has 7 entries with correct dates/phases/flags straddling a phase boundary, and is absent when tracking is off.
- **Layers 3-4 (paid eval, via `add-eval-case`), both against `generate_plan`:**
  1. Ease case: author-mode snapshot with flagged premenstrual/early-flow days where the plan would otherwise place quality -> judge that the generated week keeps those days easy and the rationale acknowledges it warmly.
  2. Follicular guard: follicular week with good readiness -> quality is NOT suppressed - protects against the "cycle present -> be gentle everywhere" over-generalization.
     Deliberately mechanical (assert a quality day exists), no judge: suppression is assertable, and an assertable fact never goes to a judge.

## Pointers

- `SYSTEM_PROMPT` (`backend/app/planner.py:145-241`) - the forward generator prompt missing the cycle block.
- `REVIEW_SYSTEM_PROMPT` cycle block (`backend/app/planner.py:1475-1486`) - the existing guidance to mirror; do not modify.
- `build_snapshot` (`backend/app/planner.py:560`) - where `menstrual_cycle` gains the `upcoming` list.
- `cycle_phase` (`backend/app/metrics.py:190-248`) - pure arithmetic; loop it over the next 7 dates.
- `generate_plan` (`backend/app/planner.py:902`) - forward generator, used by both the daily job and author-mode review.
- `_evaluate_today_locked` author branch (`backend/app/planner.py:1682-1683`) - why author-mode review inherits the forward prompt.
