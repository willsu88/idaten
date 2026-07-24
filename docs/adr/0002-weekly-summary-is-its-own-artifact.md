# Weekly summary is its own artifact, not part of an activity or daily review

We wanted a coach-written retrospective of each training week, and considered delivering it inside Sunday's execution analysis or inside Monday's daily review.
We decided it is a standalone artifact instead: its own table (one row per member per summary week, keyed by user_id + week_start_date), its own Coach call site (`weekly_summary`), generated in Monday's daily job independently of the daily review.

## Considered Options

- **Embed in Sunday's execution analysis** - rejected: only exists if a Sunday activity happened, the week isn't closed until midnight Sunday, and the analysis age cap makes it unreachable days later.
- **Fold into Monday's daily review** - rejected: the review's job is forward-looking ("what do I do today"); every day already receives 7-day context and deliberately does not narrate it. One prompt doing both jobs does both badly.
- **Standalone artifact** - chosen: survives weeks with no activities (the most coaching-critical weeks), lives permanently on the Week page, and can later serve as compact context for block-level reasoning.

## Consequences

- The weekly summary is a full quality-loop citizen: persona stamped at generation, frozen snapshot, prompt_version, thumbs feedback, `llm_usage` call site `weekly_summary`.
- It always generates (no pending_data gate) and is forward-only (no backfill of pre-launch weeks).
- Its snapshot includes the previous week's summary text (one week of lookback) for trend awareness; the daily review does not consume it.
- Week boundaries flow through a single helper so a future user-configurable week start (Sunday vs Monday) is a config read, not a migration; past summaries stay frozen to the anchor they were written under.
