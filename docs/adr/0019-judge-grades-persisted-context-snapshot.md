# The QA judge grades a persisted snapshot of the context the coach actually saw

Chat persists the hydrated dynamic context of the system prompt as in-order `ChatMessage` rows (`kind="context"`), written only when the context differs from the session's last persisted snapshot, and `qa.render_transcript` renders them as `[context]` blocks in sequence.
The judge's view thereby regains the invariant ADR 0016 assumed but never had: everything the coach could ground a claim in is visible to the judge.

The forces, from a production false fail (2026-07-27): the athlete asked what injuries were logged, the coach answered with the one open niggle - accurately - and the nightly judge failed `grounded_data` because no tool result contained injury data.
The coach never needed a tool: `_system_prompt` (`chat/agent.py`) hydrates eleven dynamic data blocks into the template on every turn - races, athlete block, training mode, HR zones, pace profile, Garmin plan, readiness, active niggles, strength signal, plus name and date - and `render_transcript` (`qa.py`) shows the judge only persisted turns and tool calls.
So any coach claim grounded in those blocks (a race goal, a typical easy pace, today's readiness, an open niggle) is unfalsifiable from the judge's chair; the niggle case is merely the first instance of the class.
The hydrated prompt was never persisted anywhere, because ADR 0016 deliberately hashes only the static template for `prompt_version` - hashing daily data would mint a version per user per day - and nothing else had a reason to store it.
The snapshot is per change, not per session: `_system_prompt` re-hydrates every turn, and ADR 0016's resumed sessions span days, so readiness and niggles can legitimately differ between a session's first and last assistant turn.

## Considered Options

- **Move injected context behind tools (coach must call `get_niggles` etc.)** - rejected: it makes injury awareness conditional on the model deciding to look before every prescription, a reliability regression on safety-relevant data; it shrinks the product's correctness to fit the grader.
- **Reconstruct context as-of the session date at judge time** - rejected: it duplicates the hydration logic forever and only for fields with temporal columns (`onset_date`/`resolved_date` work for niggles; readiness and pace profile have no as-of story), so the fail class reopens with every new template field.
- **Loosen the `grounded_data` rubric to accept claims the coach "might have had in context"** - rejected: unverifiable grounding is no grounding; a fabricated niggle would pass exactly like a real one, which guts the rubric item the incident proved is working.
- **Snapshot once per session** - rejected: resumed sessions re-hydrate across days, so a single snapshot misattributes late-session claims to stale context; the judge would trade false fails for false passes.
- **Persist the full rendered prompt including the static template** - rejected: the static text is already identified by `prompt_version` and would be duplicated verbatim on every session; only the dynamic fills carry information the judge lacks.
- **New table keyed `(user_id, session_id, turn)`** - rejected: `ChatMessage` already gives ordering, session addressing, and renderer integration for free (tool calls took the same route in ADR 0016); a parallel table re-implements all three.
- **Persist deduplicated context snapshots as in-order `ChatMessage` rows and render them to the judge** - chosen.

## Consequences

- `render_transcript` interleaves `[context]` blocks with turns and tool results, so the judge sees context evolution in order and the member-report freeze (`feedback` surface `chat_session`) inherits the same completeness for free.
- The `grounded_data` criteria change to name `[context]` blocks as legitimate grounding alongside tool results; that edits the rubric module, so `rubric_version` changes and trend lines reset, per ADR 0016's stamps.
- `JUDGE_SYSTEM` joins the `rubric_version` hash: the judge's own instructions define verdict semantics exactly like the criteria do, and the accompanying edit exposed that they could previously change without a version bump - a silent regime change the stamps exist to prevent.
- Sessions predating the snapshot have no `[context]` rows; their fails of this class remain unfalsifiable and are not re-litigated, the same stance taken for pre-instrumentation verdicts.
- The dedup hash means a quiet session costs one extra row and a multi-day session a handful; storage is noise, but every turn now pays a hash of the hydrated context.
- Health values, race goals, and injury notes now flow to the judge provider inside `[context]` blocks; ADR 0016 already accepted exactly this exposure for tool results, and the same single config lever governs it.
- The snapshot doubles as a flight recorder for chat (what did the coach see when it said that?), extending ADR 0014's stance from analysis artifacts to conversations.
- The motivating session's transcript becomes an anonymized must-pass case in the judge-quality evals once the renderer includes context, locking the fix against rubric regressions.
- `prompt_version` semantics are untouched: it still hashes the static template plus style line, and the snapshot rows carry data, not identity - ADR 0016's version-grouping survives.
