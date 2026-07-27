# HR targets are stored as resolved zone bands, never point values

A stored HR target (`target_hr_low`/`target_hr_high` on a plan day or on any step inside its `steps` blocks) is always a real range anchored on the athlete's HR zones; `low == high` is invalid data, not a tight target.
The decision has two halves: the Garmin coach mirror resolves single-number prescriptions into zone bands at write time, and the LLM paths enforce a minimum band width at generation and edit time.

The forces: Garmin's coach taskList prescribes workouts with a single HR number (e.g. `18:00@172bpm`), and `_coach_day_fields` (`planner.py`) wrote that number as both bounds, so the majority of HR-target days in production carried a zero-width band.
Three consumers treat the pair as a corridor: the frontend renders "HR 145-145", `garmin/push.py` `_target` pushes the bounds verbatim as a custom HR zone so the watch alerts constantly, and `execution.py` `_step_segment` scores time-in-band against a 0 bpm corridor so a correctly-executed run scores as a failure.
The LLM paths (plan generation, the chat edit tool) had no width check at all, and the model anchors on degenerate bands it sees in `current_upcoming_plan` - one zero-width `chat_edit` day existed in production.
ADR 0010 named this gap in its consequences: editor-mode grounding must speak HR, and the pace guard needed an HR analog.

The resolution rule: the band is the athlete's zone containing the prescribed number, from `settings_store.hr_zones` - the same single source execution scoring uses (Garmin-observed boundaries first, LTHR-Friel fallback).
On an exact zone boundary, the lower zone wins for easy/recovery/long days and the higher zone for quality days.
When zones are unavailable, or the number falls outside every zone, the band is a fixed ±7 bpm around the number - never a snap into the nearest zone, which would relocate the coach's prescribed effort to fit a possibly-stale zone table.
Enforcement on the LLM paths follows the pace-guard precedent: `generate_plan` gets one corrective retry when any band (day-level or step-level) is narrower than 5 bpm, `check_week` warns, and the chat edit tool mechanically widens a degenerate band to its containing zone.

## Considered Options

- **Store the point, widen at read** (the `PACE_BAND_MPS` precedent in `garmin/push.py`) - rejected: it blesses `low == high` as legal, making the invariant unenforceable - a degenerate band from any source becomes indistinguishable from an intentional point target, every consumer (UI, push, scoring, the LLM snapshot) needs its own widening logic, and the model keeps seeing and copying degenerate bands.
  The pace precedent does not transfer: `target_pace` is a single field, so widening at push is the only option there; the HR pair's entire meaning is a band.
- **Remodel to a zone reference** (`target_zone: "z2"`, derive the band everywhere) - rejected: the cleanest concept, but a schema migration across the plan schema, chat tool, frontend, push, and execution scoring for no behavioral gain - the LLM already plans in bpm bands anchored on zones.
- **Always ±N around the number, no zone lookup** - rejected: produces bands that straddle zone boundaries, contradicting the zone-anchored product story and the zone-anchored execution-scoring semantics.
- **Resolve into the zone band at write time** - chosen.

## Consequences

- All consumers work unchanged: the corridor stored is the corridor rendered, pushed, and scored.
- The band is frozen at resolution time, which matches the established semantics of `put_garmin_hr_zones`: forward planning uses the current zone configuration, a past day stays judged against what was in effect when it was written.
- Stored bands are resolved data, not Garmin's raw prescription; the original single number survives only in the day's description text.
- The editor-mode mirror re-materializes still-`planned` days nightly, so future degenerate days self-heal on deploy; past days and user-owned edits keep their zero-width bands in storage.
- Legacy degenerate bands are handled at scoring time, not by migration: execution scoring resolves any stored band narrower than 5 bpm through the same widening rule before scoring, already-stored execution scores are never recomputed, and the widening rule lives in one shared function with three call sites (mirror write, chat-tool clamp, scoring guard).
- The chat-tool clamp silently mutates model output; this is accepted because it widens to the same zone band the mirror rule produces, so the repair cannot contradict the edit's intent.
- Pin-style protection of user edits (the author-mode-edit-pins ticket) must not shield days that fail this validation, or a degenerate band gets fenced off from the nightly self-heal; that ordering constraint is recorded in both tickets.
