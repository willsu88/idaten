# Coach quality feedback loop

How Idaten knows whether the coach is good, and how that signal turns into a better coach.
Agreed with Will 2026-07-21 (Idea D in ROADMAP.md).

The one-line operating model: **a flight recorder, not an autopilot.**
Capture is automated and continuous; improvement is a deliberate human act that the captured data makes fast and evidence-based.
The system prompt never changes on its own.

## What gets rated

- **Coach note** (the morning daily review, `DailyCoachNote` on Today) - highest volume, the relationship surface; catches tone/grounding drift fastest.
- **Execution analysis** (the post-run note on `ResultCard` / activity detail) - highest stakes; where hallucination risk concentrates (invented numbers, ungrounded race-goal claims).
- **Edit proposals** - no thumbs; accept/dismiss is the decision signal. A dismiss offers an optional one-tap reason: "Didn't want the change" (preference) vs "The reasoning was wrong" (the quality signal).
- **Chat replies** - deliberately NOT rated; the athlete already corrects the coach in-line, and ratings there would be noise.

Thumbs are ghost icons on the shared `CoachNote` component - tap-optional, never a prompt, re-tappable to change.
A thumbs-down offers preset chips (wrong / off tone / too long / not useful) plus an optional free-text line.
Chips make aggregation possible; the text preserves specifics for eval cases.

## The four stages

### Stage 1 - Capture (fully automated)

Every rating writes one `feedback` row that FREEZES the complete example: the rated output text, the inputs that produced it, and the producing prompt's version hash.

- `DailyReview` stores its review `snapshot` + `prompt_version` at generation time.
- `Activity` stores `execution_analysis_context` (the exact LLM input payload) + `execution_analysis_prompt_version`.
- The feedback row copies these at rating time, so later data changes can't corrupt the example.

Why this matters: without frozen inputs, a thumbs-down is "she didn't like something once"; with them, it is a reproducible test case `(inputs, output, label, reason)`.

### Stage 2 - See it (fully automated)

`GET /api/feedback/summary` (admin-only) feeds a quality panel on `/admin`, next to the cost card: thumb rates per surface and per user, and the recent-negative list with tags, comments, and the offending text.
Its job is passive: a glance answers "is anything worth acting on, and on which surface?".

### Stage 3 - The eval regression harness (cases accumulate automatically; RUNNING them is human-initiated)

There is no cron and no schedule.
The trigger is noticing a problem (via Stage 2, or a direct complaint) and deciding to fix it.
A fix session looks like:

1. Pull the negative rows - each is already a ready-made test case with its frozen snapshot.
2. Edit the offending system prompt (`REVIEW_SYSTEM_PROMPT` / `EXECUTION_ANALYSIS_SYSTEM_PROMPT`).
3. Replay the stored snapshots through the candidate prompt (`pytest -m eval` pattern, real LLM, costs cents); LLM-judge each new output against the specific complaint plus the standing rubric (no invented numbers, grounded claims, house style).
4. A sample of thumbs-up outputs act as anti-regression anchors - the judge checks the new prompt still produces output of that character.
5. Ship only when the negative cases pass and the positive anchors hold.

This turns prompt editing from "it feels better" into red-green: 0 regressions across the labelled set.
Any future prompt edit - whatever motivated it - should run against the accumulated set before deploy, so quality ratchets.

### Stage 4 - Personalization (manual, rare)

When the same reason recurs enough to be a preference rather than a bug ("too long", "too much jargon"), distill it into ONE stable line in that athlete's `style_prompt`.
Human-reviewed, changed rarely.
This is the ONLY path by which feedback reaches the live prompt.

## What we deliberately never do

- Pipe raw ratings into the live context ("she disliked yesterday's note") - invites approval-chasing and churn, the exact failure the anti-churn posture guards against.
- Auto-regenerate on a thumbs-down - it is captured, not acted on in-session.
- Let the system edit its own prompts - unsupervised drift in the coach's voice is a real risk to save a minutes-per-month task.
- Fine-tune - at household volume the labelled set tests prompts, it does not train weights.

Revisit the automation question only if the user count makes manual review impractical (~50+ users of daily feedback).
At household scale, human-in-the-loop is the feature, not the compromise.

## Implementation map

- Capture: `backend/app/feedback.py` (`record`, frozen provenance), `Feedback` model, provenance columns on `DailyReview` / `Activity`, stamps in `planner.evaluate_today` / `write_execution_analysis`.
- API: `POST /api/feedback` (upsert per user+surface+artifact), `GET /api/feedback/summary` (admin), `my_feedback` / `analysis_feedback` state on the review and activity payloads.
- UI: thumbs in `components/coach-note.tsx`; dismiss-reason chips on `EditProposalCard`; quality panel on `/admin`.
- Contract: API_CONTRACT.md v1.23.
