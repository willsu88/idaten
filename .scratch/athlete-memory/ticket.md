# Ticket: athlete memory - proactive precedent retrieval

Filed 2026-07-27 from a product brainstorm. Status: parked.
Industry analog: proactive, context-triggered knowledge surfacing (knowledge-agent pattern).
Of the batch, this is the one that most improves Idaten as an actual product: coaches remember, snapshots do not.

## The idea

The planner and chat coach currently see a fixed-size aggregate snapshot (by design, for constant cost).
Add a retrieval layer over full history - past training blocks, RPE/feel notes, race reports, injuries, gear changes - and let the coach proactively cite precedent:
"the last time you stacked three poor-sleep nights before a long run (March), you cut it short at 14k."

Key property: knowledge is PUSHED into the conversation based on current context, not only pulled when the user asks.

## Shape

- A `search_history` tool for the chat agent (pull path) - cheapest first step, no infra.
- Push path for the daily planner: before the plan call, a retrieval step selects K relevant precedent episodes and appends them to the snapshot as short text summaries.
  This preserves the constant-cost property: K is fixed, episodes are summarized.
- Episode store: precomputed per-week/per-block summaries in SQLite (generated once, at sync or weekly-summary time), searched by metadata filters + embedding or even plain keyword to start.
- Subjective data is the differentiator: RPE notes and free-text feel comments are where precedent lives; structured metrics alone are already in the aggregates.

## Open questions

1. Retrieval quality bar: a wrong precedent confidently cited is worse than none - does each retrieved episode need a relevance check before injection?
2. Embeddings (new dependency) vs SQLite FTS5 keyword search - at single-athlete data volume FTS5 may be genuinely enough.
3. Where do race reports / long-form notes get written? May need a small "journal" input in the UI first - possible sub-ticket.
4. Interaction with the fixed-snapshot cost invariant is a design constraint, not a nice-to-have - document in an ADR if built.
