# Garmin Bot — Roadmap & Decisions

Working document. Current state, agreed decisions, and the phased build plan.
Updated: 2026-07-24 (Idea F fully closed out: code-review fixes deployed and live browser eyeball of all strength surfaces done. The A-F block is complete; next candidates are hill runs, model routing, friends).
Prior: 2026-07-23 (Idea F strength/cross-training selected as the next block and spec'd: parallel support-sessions lane, weekly-target Settings contract, works in both author and editor mode - see the Idea F DESIGN SPEC below).
Prior: 2026-07-20 (product + architecture review with Will: six new IDEAS captured below - injury/niggle signal, per-user token/cost accounting, proactive morning delivery, coach-quality feedback loop, macro/periodization guardrail, strength as first-class; plus two model-agnostic-seam findings. None built yet).
Prior: 2026-07-19 (execution score + analysis SHIPPED end-to-end: scoring, attribution, review feedback, forward-looking coach-attributed analysis; plus no-em-dash house style, Trends 7-day daily charts, About hidden from nav. Hill-run workouts still a backlog idea, not built).

## IDEAS — 2026-07-20 product + architecture review (captured, design still open)

Six ideas surfaced in a review of current features, plus two architecture findings on the model-agnostic seam.
None are spec'd or built.
Recording the reasoning, the leaning, and the open questions so we don't re-derive them at spec time.

Recommended next block (Will to confirm sequencing): **B (token/cost accounting) + A (injury tracking) + C-lite (eager review generation - push itself was rejected 2026-07-21, see Idea C)**.
All three slot into machinery we already built, and A is the one genuine hole in the coaching model.

### Architecture findings — the model-agnostic seam (confirmed by reading `app/llm/`)

The seam itself is sound and stays: `LLMClient` Protocol in `app/llm/__init__.py`, `make_client(provider)` as the single switch, lazy provider imports, neutral OpenAI-shaped wire format that the Anthropic client translates at its own boundary.
The planner and chat agent talk only to `LLMClient`, never to a provider SDK.
Two gaps, both load-bearing for the ideas below:

1. **The seam discards `usage`.** `complete` / `stream` / `complete_structured` return only `Response(content, tool_calls)` (or a parsed dict); the provider's `usage` object (input/output/cache-read/cache-creation tokens) is dropped on the floor.
The only mention of `usage` in the whole backend is a COMMENT in `anthropic_client.py` ("verify via usage.cache_read_input_tokens") - which today you cannot, because nothing records it.
This is THE choke point for token accounting (Idea B): every LLM call in the app funnels through these three methods, so one change here instruments everything.
2. **Model choice is global, not per-call.** Every call uses `config.anthropic_model` (Opus).
A one-line "strip em-dash / edit summary" style pass pays the same Opus rate as a full structured plan generation.
Once cost is visible (Idea B), we will likely want to route cheap deterministic calls (execution analysis, edit summaries, clean-up passes) to a smaller model and keep Opus for planning + chat - a small optional `model`/`tier` arg on the client methods.

### Idea A - Injury / niggle tracking (fourth deterministic review signal)

Want: let the athlete tell the coach "my knee hurts", have that PERSIST and bias the plan down until it clears.

**Strategic fit - this is the biggest hole in the coaching model.**
Every review signal today is physiological-state (readiness = HRV/sleep/body-battery) or execution (did you hit the session).
A real coach's single most important input is pain, and there is currently NO channel for it.
Injury is the #1 thing that derails amateur runners, and it is exactly what a greedy daily optimizer (Garmin DSW) structurally cannot see - same argument that justified cycle tracking.
It reuses the whole existing pipeline: a fourth deterministic signal computed in `metrics.py`, handed to `evaluate_today` as grounding alongside `readiness` / `structural_signals` / `menstrual_cycle`, with the model proposing an ease-off through the existing PendingEdit machinery.
Near-zero new downstream plumbing.

**Leaning (not decided):** a lightweight "log a niggle" input - location (body part), severity (1-3 / niggle-pain-injury), onset date, optional note; open until the athlete marks it resolved.
Fed into `build_snapshot` as `active_niggles`; a `REVIEW_SYSTEM_PROMPT` bullet biases toward easing / cross-training / rest while a niggle is open, and flags when load is ramping into a sore area.
Model SUGGESTS, does not churn - same posture as cycle and structural signals.
Storage: likely a small `niggles` table (open/resolved rows with dates), NOT a settings blob, since we want history and multiple concurrent entries - unlike the single-anchor cycle model.

**Open questions:** severity taxonomy and how hard each tier biases the plan; does an open niggle also suppress the execution-score nudge to progress; surface (a Today card + a Settings/"health" room, or folded into the RPE moment); auto-resolve after N days of no mention vs explicit resolve only; interaction with the "green-light progression" review signals (a niggle should veto a green-light).

**DECIDED (Will 2026-07-21, all open questions closed):**
- **Chat is the front door.** Telling the coach "my knee hurts" is the natural channel: two new chat tools `log_niggle` / `resolve_niggle` (same server-side write pattern as `set_day_intent`).
"My knee's fine now" in chat resolves it - one row update, two doors (chat and UI card are equivalent).
- **Severity taxonomy:** 1 = niggle (minor, monitor), 2 = pain (real pain, protect), 3 = injury.
An open severity >= 2 VETOES the execution-signal green-light; severity 1 biases against stacking hard days.
- **No nagging.** Reporting is athlete-initiated; the RPE moment is NOT extended with a pain ask.
The only prompt is a check-in after a severity-scaled quiet window: 7 days for severity 1 (minor things clear in days), 14 for severity 2-3 (real injuries take weeks; asking sooner is a nag).
"Still sore" re-arms the window, so a long injury gets a gentle check-in roughly every two weeks.
- **Explicit resolve only**, never auto-resolve.
- **Surface:** `NiggleCard` on Today (below `CycleTodayCard`), rendered ONLY while something is open - never a permanent widget; a compact "Niggles & injuries" Settings card is the standing UI entry point.

**BUILD LOG — DONE + DEPLOYED 2026-07-21 (306 backend tests green; tsc + next build clean):**
- **`niggles` table** (`models.py`, auto-created): `id, user_id, body_part, severity 1-3, onset_date, resolved_date (null = open), note, source (chat|ui), checkin_date`. A table, not a settings blob - history + concurrent entries.
- **`app/niggles.py`** - `active_niggles(db, uid, today)` (the deterministic signal: dicts with `days_open`, `severity_label`, `show_checkin`; returns None when clear so the "only present when reported" prompt framing holds), `log_niggle` (normalizes body part; re-logging an open part UPDATES it - one knee, not two rows; future onset clamped to today; severity clamped 1-3), `resolve_niggle` / `checkin_niggle` (ownership-checked).
- **Review pipeline:** `build_snapshot` gains `active_niggles` (flows to both the daily review and author-mode plan generation); `REVIEW_SYSTEM_PROMPT` bullet: bias down while open, severity >= 2 vetoes green-lights, name the body part warmly in the coach_note, suggest-don't-churn.
- **Chat:** `log_niggle` + `resolve_niggle` tools; system prompt carries the open list (so the model knows ids and doesn't double-log) + a rule to log on any pain mention, resolve on "it's better", ease around open issues, and defer to a professional for severity-3/persistent pain (coach, not clinician).
- **API:** `GET/POST /api/niggles`, `POST /api/niggles/{id}/resolve`, `POST /api/niggles/{id}/checkin`; `/dashboard/today` gains top-level `niggles`. Contract **v1.22**.
- **Frontend:** `NiggleCard` on Today (severity chips amber/rose, optimistic Resolved button, check-in variant "Still bothered by your left knee?" with Better now / Still sore), `NiggleLogDialog` (body part, severity select, note, onset date), `NigglesSettingsCard` on Settings.
- **Tests:** `test_niggles.py` (10: log/resolve roundtrip, same-part dedupe, severity-scaled check-in windows + re-arm, clamps, tenant isolation, chat tools, snapshot, endpoints + validation); tool-inventory test updated. Suite 306 green.
- **Deployed 2026-07-21** via `docker compose up -d --build` after an in-container predeploy backup (`garmin_bot_backup_predeploy_niggles_20260721.db`; no sync/backfill was running). `niggles` table auto-created empty; live smoke: unauth `GET /api/niggles` 401, frontend 200.
- **Still open:** live browser eyeball of the card + a real chat log/resolve turn; the "load ramping into a sore area" refinement (needs per-area load attribution - out of scope).

### Idea B - Per-user LLM token + cost accounting (admin observability)

Want: as the admin whose API key funds the household, SEE what each user costs, per feature, and whether prompt-caching is paying off.

**Why now.** Nothing exists today.
`rate_limit.py` caps chat by MESSAGE COUNT (5/5min, 15/day, admin exempt), which bounds spend only by proxy - one plan-generation turn with 8 tool rounds and a 32k structured output costs vastly more than a one-line reply, yet both count as "1 message".
And we invested in prompt-caching (the load-bearing system-prompt cache) with no way to confirm the hit rate.

**Leaning (strong):** instrument at the SEAM, not the call sites (see architecture finding 1).
- One `llm_usage` table, mirroring the `SyncLog` pattern: `user_id, ts, provider, model, call_site (plan|review|chat|execution_analysis|edit_summary|...), input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, est_cost_usd`.
- The `call_site` tag is the valuable dimension - it tells us WHICH feature is expensive, which is what drives optimization and model-routing (finding 2). Pass it as a per-request context/tag through the client methods.
- Cost is DERIVED from a small per-model price map, not stored raw; cache-read vs full-input kept separate so the caching lever is visible.
- One `LLMClient` change: the three methods also return usage (or take an `on_usage` callback). Zero changes to planner/chat/execution logic.
- Surface on a tiny admin-only view: per-user daily/monthly cost, per-call-site breakdown, cache-hit ratio.

**Why it ranks high:** it is the prerequisite for cost-routing (finding 2) and for trusting the caching already built, and it is roughly a day of work.
It also turns "chat is probably the expensive part" and "caching helps" from guesses into facts.

**Open questions:** admin-view surface (a new `/admin` route vs a Settings section gated on `is_admin`); do we ever show a user their OWN usage (probably not - it reads as surveillance in a coaching relationship); retention/rollup of the raw rows; whether to add a real cost-based budget/alert on top of the existing message-count limiter.

### Idea C - Proactive morning delivery (push the daily review, don't wait for a visit)

Want: the coach REACHES OUT in the morning ("readiness is low, I eased today's session") instead of waiting for the athlete to open the app.

**DECIDED (Will 2026-07-21): no push channel. Build EAGER GENERATION instead; push demoted to a parked idea with a revival trigger.**

Reasoning from the design discussion:
- The original framing ("the review text already exists, ungifted") was stale: the review is LAZY (`evaluate_today` fires on first Today visit, `scheduler.py` daily job does no LLM work).
So the real hole was never delivery, it was that on a day the app isn't opened before a run, the coach's daily call (e.g. "readiness is low, I eased the session") silently never happens.
- Asked directly, Will says running before opening the app is VERY RARE for both athletes.
That kills the substantive case for a notification channel; what remains (engagement, "feels coach-like") doesn't justify the infra - service worker + PWA manifest + VAPID keys + subscription lifecycle + iOS add-to-home-screen, all NEW machinery, unlike Ideas A/B/D which slot into existing seams.
- Web push beat email/Telegram on channel choice (keeps the app as the only surface), so IF push is ever revived, it's web push.

**What to build instead - eager generation (small, no new infra):**
- Extend the daily job in `scheduler.py`: after sync, if `data_ready` (`metrics.has_recovery_data`), run `evaluate_today`.
- Data not ready at plan_hour (late Garmin sync, or a no-sleep night): do NOT generate - reuse the existing `data_ready` gate, never review on missing data.
Retry via the existing 30-minute `catch_up` interval until data lands.
The existing lazy path (`/dashboard/review` poll + `ensure_fresh_today` self-heal) stays as-is and remains the fallback.
- Net effect: the morning note exists by ~plan_hour+5 on normal days; Today opens instantly with the note already there; the rare pre-app run is still covered for anyone who opens the app even briefly.
- Cost: one LLM call per user per day now happens even on never-opened days (was: zero). Bounded (2 users), and Idea B's token accounting is the right watchdog - sequence B before or with this.

**Open question (rare-day only):** should late-arriving data upgrade a `done_structural` review to a full one (one extra LLM call)?
Today `dashboard_evaluate` treats `done_structural` as final. Lean yes (the review's whole point is reacting to readiness), decide at build time.

**Parked (revival trigger):** build web push only if we catch ourselves missing morning notes in practice, or a third user joins who isn't a daily-open user.
If revived: one push per day hard cap (cycle-drift lesson), data-gated with a plan_hour+3h cutoff falling back to a structural-review push, opt-in per user.

Related UX item recorded in `UX_IMPROVEMENTS.md`: calm "no sleep data yet" Today state instead of perpetual "syncing…", with "Review anyway" promoted.

**BUILD LOG — DONE 2026-07-21 (contract v1.25; 325 backend tests green; tsc + next build clean):**
- **Eager generation:** `_eager_review` in `scheduler.py`, called from `_job_for_user` after the sync commit - gated on `has_recovery_data` + review-not-done, and a review failure never fails the sync job (logged, rolled back, lazy path recovers).
- **Late-data retry:** `catch_up` now calls `_retry_pending_reviews()` on ticks where the daily job already ran - for each Garmin user with a pending review: `sync_only_job` then `_eager_review`. No cutoff (an afternoon sleep still gets its review); absent data costs one data sync per 30-min tick and zero LLM calls.
- **Idempotency hardening (the race the eager pass created):** `evaluate_today` now takes a per-user lock and re-checks done-state (with `db.refresh`, since the racing session's copy can be stale) before running - scheduler eager pass and Today-page lazy trigger can never double-spend. `test_review_reuses_daily_row` updated to assert the new contract (second same-day call returns the done review untouched).
- **Calm overdue state:** `GET /dashboard/review` gains `data_overdue` (not data_ready AND >= plan_hour+2h household time, via new `scheduler.now_local()`); `DailyCoachNote` renders the calm card + promoted secondary Button and slows polling 5s to 60s.
- **Tests:** `test_eager_review.py` (8: gate on ready/absent/bare-row data, skip-when-done, failure swallowed, evaluate_today idempotent incl. structural flag, retry-after-late-sync + no-resync-once-done, data_overdue endpoint before/after threshold and after data lands).
- **Structural-upgrade question resolved by the lock:** late data does NOT upgrade a `done_structural` review (unchanged behavior, now explicit in `evaluate_today`'s guard). Revisit only if a real rough-night day shows the structural note aging badly.

### Idea D - Coach-quality feedback loop (thumbs on coach output)

Want: a 👍/👎 (plus optional reason) on coach notes, plan edits, and execution analyses, so we can TELL if the coach is good and eventually tune it.

**Strategic fit.** For an LLM coaching product this is the missing quality signal - right now there is no eval set and no way to know when the model wrote something wrong or off-voice.
Storing the rating WITH the snapshot that produced it gives us a labelled dataset for regression-testing prompt changes and, later, for calibration.
Pairs naturally with Idea B (the admin quality/cost view).

**Leaning (not decided):** a minimal rating on each coach-authored surface (coach_note, edit summary, execution analysis), persisted with a foreign key to the producing artifact + the input snapshot hash.
No user-visible behavior change beyond the control itself; value is internal/admin at first.

**Open questions:** which surfaces get it first (coach_note is the highest-volume); free-text reason vs thumbs-only; whether a 👎 should trigger any immediate re-generation or is purely captured; how the labelled set feeds prompt iteration (manual review vs an eval harness).

**DECIDED (Will 2026-07-21, all open questions closed). Full operating model documented in `COACH_QUALITY.md` (repo root) - the four-stage loop, what's automated vs manual, "flight recorder, not autopilot".**
- **Surfaces:** thumbs on the morning coach note AND the post-run execution analysis (both render via the shared `CoachNote`, so one implementation covers both).
Edit proposals get NO thumbs - accept/dismiss is the decision signal - but a dismiss offers an optional one-tap reason ("Didn't want the change" vs "The reasoning was wrong"; the second is the quality signal).
Chat replies deliberately unrated.
- **👎 input:** preset chips (wrong / off_tone / too_long / not_useful) + optional free text.
- **Purely captured:** a 👎 never triggers regeneration; raw feedback never enters a live prompt (anti-sycophancy). Improvement is human-initiated (Stage 3 eval sessions); the only live-prompt path is a distilled per-user style line (Stage 4, rare, human-reviewed).

**BUILD LOG — DONE 2026-07-21 (315 backend tests green; tsc + next build clean):**
- **Provenance at generation time (the load-bearing piece):** `DailyReview` gains `snapshot` + `prompt_version`; `Activity` gains `execution_analysis_context` (the exact LLM input payload) + `execution_analysis_prompt_version`. Stamped in `evaluate_today` and `write_execution_analysis`; `feedback.prompt_version()` = sha256[:12] of the system prompt, so quality is attributable to prompt revisions.
- **`app/feedback.py` + `feedback` table:** `record()` upserts one row per (user, surface, artifact_ref) and FREEZES artifact_text + producing context + prompt_version into the row - every rating is a complete (inputs, output, label, reason) eval case. Ownership-checked; unknown tags dropped. `summary()` = Stage-2 aggregation (per-surface/per-user up/down/dismiss-reason counts + recent-negative list).
- **API:** `POST /api/feedback` (422 bad surface/rating, 404 missing/foreign artifact), `GET /api/feedback/summary` (admin-gated like `/usage`); `my_feedback` on the review payload, `analysis_feedback` on activity detail + Today's completed_workout. Contract **v1.23**.
- **Frontend:** thumbs in shared `CoachNote` (optional prop - unrated surfaces unchanged), 👎 popover with chips + text; wired in `DailyCoachNote` + execution-analysis renders; dismiss-reason chips on `EditProposalCard`; `AdminQualityCard` on `/admin`.
- **Tests:** `test_feedback.py` (9: provenance freezing both surfaces, dismiss reason, upsert-in-place, foreign/missing artifact rejection, stable prompt hash, summary aggregation, endpoint roundtrip + validation, admin-only summary).
- **Gotcha for future columns:** `Mapped[Any]` JSON columns are NOT NULL by default - new nullable JSON columns need explicit `nullable=True` (broke 56 tests until fixed).

### Idea E - Macro / periodization guardrail (training-load ramp)

Want: a BLOCK-altitude signal between the daily review and the race goal - "you are ramping load too fast" and a visible arc to race day.

**Strategic fit.** The product is excellent at the DAILY altitude and has races/predictions at the GOAL altitude, but the multi-week BLOCK layer is thin.
A training-load ramp guardrail (ACWR, or CTL/ATL/TSB) computed from data we ALREADY ingest would (a) give the coach a deterministic "ramping too fast / detraining" signal - again the multi-week pattern DSW misses - and (b) give the athlete a visible build toward race day.
Same "deterministic signal feeds the review" shape as the other three signals.

**Leaning (not decided):** compute a rolling acute:chronic workload ratio (or a simple CTL/ATL/TSB) from activity load; add it to `build_snapshot` with guardrail thresholds (flag ramp > ~1.5, flag detraining); optionally a Trends surface showing the ramp against a safe band and the arc to the primary race.
More work than A-D (needs a load model + a validated ramp threshold), so sequence it AFTER the first block.

**Open questions:** load metric (Garmin `trainingEffect` / TRIMP / our own) and whether we trust ACWR's known statistical criticisms; threshold calibration per athlete; is this a coach signal only, an athlete-facing chart only, or both; overlap with Garmin's own acute/chronic load (don't just re-skin what the watch shows).

**ANSWERS (settled at build time, 2026-07-21):** load metric = the existing `activity_load` (Garmin `training_load` with duration fallback, incl. intent-day estimates) - no new load model; ACWR criticisms addressed by NOT using the raw daily ratio (see calibration below); both coach signal AND athlete chart; not a re-skin because ours is (a) forward-looking on the PLANNED week and (b) coach-actioned via PendingEdit.

**BUILD LOG — DONE + DEPLOYED 2026-07-21 (340 backend tests green; tsc + next build clean; predeploy backup `garmin_bot_backup_predeploy_ramp_20260721.db`). Live smoke: Will acwr 0.91 safe/flat, Julianne 0.74 safe/flat - both correctly quiet; endpoints auth-gated.**
- **Calibration spike FIRST (read-only, both users' 300-day history).** The raw daily 7/28 ratio fired ~20% of days (noise + post-break restarts on a near-zero chronic) - unusable. Final rule: chronic FLOOR (>= 15 load/day) + PERSISTENCE (ratio must hold > edge for 3 consecutive days) -> Will 5-6 real episodes/10mo, Julianne 2, all genuine ramps. Detraining (-15%/21d alone flagged 83 days for Will) ships as an exposed trend NUMBER the model reads in context, never a hard zone.
- **`metrics.ramp_signal(db, uid, today, planned_days)`** - zones safe/caution(>1.3)/high(>1.5) with floor + persistence; `chronic_trend` building/flat/detraining; **comeback rule**: the floor is WAIVED when the athlete held a real base any time in 90 days, so month-off-then-full-volume flags (the risky case) while a brand-new runner's first weeks don't (noise). Forward-looking `planned_next_week.acwr_if_executed` projects the ratio if the upcoming plan is executed - the half no watch widget shows. `planned_day_load` = minutes x per-type intensity factor (validated vs completed days' actual Garmin loads, ~25% - fine for a band check).
- **Wired as the fifth review signal:** `build_snapshot` gains `load_ramp` (flows to review AND author plan generation); `REVIEW_SYSTEM_PROMPT` bullet (high -> propose trimming the least important session, protect the long run; planned-week high -> trim even when today looks fine; detraining + race -> rebuild gently / license to build when safe; never alarm on one down week; no raw ratios in the coach_note). Author mode: `SYSTEM_PROMPT` ramp line + `check_week(days, budget, chronic_daily_load)` mechanical assertion (warnings-logged pattern kept, no silent repair).
- **Trends chart:** `/api/analytics` gains `ramp` (daily series + band edges + zone_today + chronic_trend + race marker); `RampChart` in the Load group - ratio line over green/amber/rose bands, null-gapped below the floor, plain-language copy. Contract **v1.25**.
- **Tests:** `test_ramp.py` (13) - the conversation's scenarios are named cases: travel-week return NOT flagged (28d baseline absorbs one down week), month-off return IS flagged (comeback rule), single hot day guarded by persistence, new-runner floor, detraining reported-not-zoned, forward projection, check_week warning.
- **Still open:** eval cases for the coach's ramp behavior (seeded ramping/detraining athletes, opt-in `-m eval`); per-athlete threshold tuning if the D feedback loop shows the band nagging.

### Idea F - Strength / cross-training as first-class (minor, later)

Want: strength and cross-training as real, plannable, trackable sessions - not just "rest".

**Strategic fit.** Execution scoring and plans are run-only by design; most injury-resilient amateur plans include strength, and this connects directly to Idea A (injury prevention).
Lower priority and larger surface (new session types, new UI, non-run "execution"), so noted as a later idea, not part of the next block.

**Open questions:** do we PLAN strength (prescribe) or just LOG it; how it interacts with the run-only execution score; whether Garmin's strength-activity data is rich enough to score against, or it stays a simple did-it log.

**DESIGN SPEC (2026-07-23, Will + design review; NOT built). Selected as the next block.**

Grounding facts from code (verified 2026-07-23):
- The LOAD side already works: sync ingests ALL activity types and `metrics.load_series` sums load from every activity, so strength/cross sessions already count toward CTL/ATL/TSB and the ramp signal.
What is missing is visibility (UI and snapshot don't name them) and planning (the coach can't prescribe them).
- `PlanDay` is one row per (user, date) with a single `workout_type` - "easy run + strength after" is not representable in the run-plan table.

**DECIDED - the parallel-lane architecture.**
Strength/mobility/cross lives in its OWN lightweight table (`support_sessions`: date, kind, duration_min, focus, note, status, source), a lane BESIDE the run plan, never a second session inside `plan_days`.
Consequences, all intentional:
- Both modes support it identically, because the author/editor split governs only the RUN lane.
Garmin plans are run-only and always will be, so Idaten's coach is the sole owner of the strength lane in BOTH modes.
- Zero collision with editor-mode materialization and its override-protection rules - the daily re-copy never touches the strength lane.
- Execution scoring stays run-only; strength completion is a simple did-it: a synced Garmin strength/cardio activity on the session's date auto-completes it, with a manual "did it without the watch" tap as fallback (DayIntent spirit).
- In editor mode, strength cards are badged as the Idaten coach's - never passed off as Garmin's plan (existing rule).

**DECIDED - the weekly target setting is the contract (Will 2026-07-23).**
A "Strength training" Settings card: sessions per week (0-3, default 0 = feature opt-in) + focus preference (coach decides [default] / full body / upper / lower).
This turns "should the coach suggest strength?" into a deterministic signal, the house pattern:
- `weekly_target - (planned + done this week)` is computed in code and added to `build_snapshot`.
The coach never decides WHETHER strength is wanted (the athlete said so); it decides WHEN and WHAT.
- Author mode: plan generation receives the target and PLACES the sessions when it writes the week - after easy days, never the day before quality or the long run, respecting the ramp budget.
Ships as part of the plan (no approval step), same as every other authored day; still written to the support lane.
- Editor mode: the coach PROPOSES placements around Garmin's run week through the existing approval queue - same target, same signal, different write path, mirroring exactly how the modes already differ for run edits.
- The target is GUIDANCE, not a quota: on a high-ramp or heavy-niggle week the coach may place fewer and say why.
- No nagging on missed sessions (niggle precedent): propose placement early in the week, never guilt-trip.
- Niggle interplay is the payoff: an open niggle biases focus toward targeted prevention work (knee -> hips/glutes) regardless of the focus preference, and the snapshot lets the coach connect "skipped both strength sessions the week the knee flared".

**UX surfaces:**
- Today: a compact secondary card under the run workout ("+ Strength · 25 min · hips & glutes") with a one-line why; flips to done on sync-match.
- Week: a small badge on days carrying a session; the week summary line gains "2 of 2 strength". The week keeps reading as a RUN week with support work attached.
- Chat: the natural front door, like niggles - "add some strength this week" -> proposal.
- Settings: the target card above.

**Phasing:**
1. Phase 1 - SEE it: surface synced non-run activities properly on Today/Week/Activities and name recent support sessions in `build_snapshot`. Render + snapshot work only, no planning.
2. Phase 2 - PLAN it: `support_sessions` table, the Settings target, author-mode placement, editor-mode proposals, done-matching, Today/Week cards.
3. Phase 3 (later, only if wanted): push a simple timed strength workout to the watch, structured exercise content, quality scoring. This is where the surface gets big - deferred.

**Open questions (settle at build time):** exact `kind` taxonomy (strength / mobility / cross vs just strength first); whether the coach may propose EXCEEDING the target (lean no - respect the contract, suggest changing the setting instead); how the review speaks about a completed strength session (brief acknowledgement vs silence); whether Phase 1 ships alone or folded into Phase 2.

**BUILD LOG — Phase 1 (SEE it) DONE + DEPLOYED 2026-07-23 (contract v1.31; 382 backend tests green; tsc + next build clean; predeploy backup `garmin_bot_backup_predeploy_support_20260723.db` taken in-container; live smoke: unauth today/week 401, frontend 200, new code confirmed in the running image):**
- Scoping finding that shrank the phase: the coach and the load model already SEE non-run activities - sync ingests all types, `load_series` sums load from every activity, and `build_snapshot.recent_activities` has no run filter (7-day window, with type/name/duration). The Activities list already handles all types with filter chips too. Phase 1 was therefore pure surfacing: Today, Week, and a prompt bullet.
- **`GET /api/dashboard/today` gains `support_activities`** - today's non-run activities (`type` not containing "run", so every `…running` variant stays a run): id, type, name, duration_min, training_load, rpe (athlete RPE, else Garmin-logged).
- **`GET /api/plan/week` `days[]` gain `support`** - per-day non-run sessions (id, type, name, duration_min), built from the `week_acts` query the summary already ran (no extra query).
- **Frontend:** new `components/support-session-card.tsx` - `SupportSessionCard` on Today (below the workout/result card, rendered only when something was done; icon + name + type · duration · RPE, links to activity detail) and `SupportChip` on Week day rows (icon + duration chip beside the intent chip, z-raised above the row's nav link). `SupportActivity` type in `lib/types.ts`.
- **Prompt:** `REVIEW_SYSTEM_PROMPT` bullet - non-run sessions are real training, already counted in the load aggregates; acknowledge naturally, factor into fatigue reasoning (heavy legs after strength work is normal), never describe such a day as "did nothing", never score them.
- **Tests:** `test_support_activities.py` (3: today lists non-run only with rpe fallback + excludes `…running` variants and yesterday; empty case; week per-day mapping).
- Live browser eyeball of both surfaces done 2026-07-24.

**BUILD LOG — Phase 2 (PLAN it) DONE + DEPLOYED 2026-07-23 (contract v1.32; 397 backend tests green; tsc + next build clean; predeploy backup `garmin_bot_backup_predeploy_strength_20260723.db` in-container; live smoke: unauth today/strength 401, frontend 200, `support_sessions` table + `pending_edits.strength` column auto-migrated, no startup errors). Taxonomy decision (Will): strength ONLY - the `kind` column leaves room for mobility/cross later.**
- **`support_sessions` table** (`models.py`, auto-created): id, user_id, date, kind, duration_min, focus, rationale, status planned|completed|skipped, source author|chat_edit|manual, activity_id. `PendingEdit` gains nullable `strength` JSON (the Mapped[Any] NOT-NULL gotcha honored; additive column auto-migrates).
- **Settings contract:** `strength` blob {sessions_per_week 0-3 default 0, focus coach|full|upper|lower} in `settings_store.DEFAULTS` + `normalize_strength` on GET/PUT (cycle pattern).
- **`app/support.py`** - the lane's module: `strength_signal` (Mon-Sun target/done/planned_upcoming/remaining; done counts DISTINCT days with a completed session or any strength activity, so unplanned gym work honors the contract), `match_completed` (idempotent read-path auto-complete: planned session + synced `%strength%` activity same date -> completed + activity_id; no sync hook needed), `apply_sessions` (validating writer: in-window dates, one per date, clamped to target; `replace=True` for the author's daily re-plan drops its own stale placements but NEVER touches manual/completed rows - the materialization rule transplanted), `create_strength_proposal` (the PendingEdit twin of create_pending_edit, same supersession).
- **Author mode:** `PLAN_SCHEMA` gains required `strength_sessions`; SYSTEM_PROMPT placement rules (only when the snapshot has a strength block; after easy/rest days, never before quality/long run; guidance-not-quota; niggle overrides focus preference); `generate_plan` applies clamped to `target - done_this_week` with replace=True. `build_snapshot` gains `strength` (None until opted in - flows to plan, review, and chat).
- **Editor mode / chat:** `propose_strength_sessions` tool (rejects when not opted in, pointing the athlete to Settings); `accept_edit` applies `edit.strength` as source=chat_edit (additive upsert, replace=False - an accepted proposal must not wipe author placements on other days); chat system prompt carries the strength signal + placement/no-nagging rules; `edit_dict` exposes `strength`.
- **REVIEW_SYSTEM_PROMPT:** strength bullet - part of the week's load (no hard run the morning after heavy strength), brief warm acknowledgement, NEVER nag; remaining_to_plan mid-week at most earns a light "ask me in chat" nudge; niggle -> prevention-work mention.
- **API:** `POST /api/strength` (manual add; 409 on a non-planned holder; upserts over a planned coach placement), `POST /api/strength/{id}/complete`, `DELETE /api/strength/{id}` - ownership-checked; today gains `strength_session`; week days gain `strength` + summary gains `strength {target, done}`.
- **Frontend:** `StrengthTrainingCard` (Settings, Off/1/2/3 + focus, optimistic like cycle), `StrengthTodayCard` (planned card with the coach's why + Mark done; hides itself when auto-completed - the activity's own row covers it), `StrengthChip` on Week rows (dashed planned / solid green manual-done), week summary "1 of 2 strength", `EditProposalCard` renders strength proposals as addition rows.
- **Tests:** `test_strength.py` (15: normalizer clamps, settings roundtrip, signal gating/counting, match completes + ignores runs, apply clamp/validate, replace preserves manual+completed, proposal opt-in gate, proposal->accept roundtrip, chat dispatch both gates, manual add/complete/delete + 409, tenant isolation, today/week payloads, snapshot gating). Updated: tool-inventory set, week-summary empty shape.
- Live browser eyeball done 2026-07-24 (Settings card, author-mode placement, chat proposal roundtrip).
- **Still open:** Week has no manual "add strength" affordance yet (chat or the coach covers it).

**FOLLOW-UP — review-initiated strength placements + Settings mode tooltip, DONE + DEPLOYED 2026-07-24 (contract v1.32.1; 403 backend tests green; tsc + next build clean; predeploy backup `garmin_bot_backup_predeploy_strengthreview_20260724.db` in-container; live smoke: unauth today 401, frontend 200, backend log clean):**
- **The editor-mode gap closed.** The daily review can now ATTACH strength placements to its proposal instead of only nudging toward chat: `REVIEW_SCHEMA.proposal` gains `strength_sessions` (planner item shape), and a proposal may be strength-only (`should_propose` true, `days: []`).
- **One shared path.** `create_pending_edit` gains a `strength` param (validated against the weekly target via `support._valid_sessions`); `create_strength_proposal` now delegates to it, so chat and review share one validation + supersession path. Placements land on the same `PendingEdit.strength`, so the existing proposal card renders them with zero frontend changes.
- **Anti-nag enforced in code, not just prompt:** `support.strength_proposal_muted` - a strength-carrying proposal dismissed this week (chat- or review-created) mutes review placements until Monday; the call site strips them before `create_pending_edit`, and a stripped-to-empty proposal creates no edit. Run-only dismissals never mute; chat can still propose any time.
- **Prompt:** the REVIEW strength bullet now says place-don't-nudge (once, early in the week, suitable days only, dismissal is final - "this is enforced too"); `should_propose` description names unplaced strength as a valid reason.
- **Settings UX (Will's ask):** the strength card's "Sessions per week" label gains an `InfoTip` - author mode auto-places around your runs; Garmin Coach (editor) mode proposes for approval; either way guidance-not-quota.
- **Tests (6 new in `test_strength.py`, 21 total):** strength-only pending edit, empty-both rejection, mute set/cleared by dismissal, run-only dismissal doesn't mute, editor review attaches placements end-to-end (stubbed LLM), muted review creates no edit.

**CODE-REVIEW FIXES — 2026-07-24 (post-review; 405 backend tests green; tsc clean; DEPLOYED 2026-07-24 - verified `target=len(edit.strength)` in the running backend image, containers rebuilt after the latest commit):**
- A /code-review pass (8 finder angles + verification) found two CONFIRMED bugs in the proposal-ACCEPT path, both the same root: accept-time re-validation against CURRENT state silently dropped approved sessions while returning ok.
  (1) Late accept: `apply_sessions` was windowed on `dt.date.today()`, so accepting a Tuesday proposal on Saturday dropped its Wed/Fri sessions.
  (2) Target lowered (e.g. to 0) between proposal and accept clamped the write to nothing.
- **Fix (one principle):** the approval is the authority - accept now validates against the proposal's own creation window (`edit.created_at.date()`) and never re-clamps (`target=len(edit.strength)`). Past-dated sessions applied late still reconcile via `match_completed` if the athlete actually trained. Two regression tests added (`test_strength.py`, 23 total).
- Also swept the em dash out of the four USER-VISIBLE strings the review flagged (strength card description, InfoTip body, two toasts) per the no-em-dash rule - hardcoded UI strings bypass the runtime `strip_em_dashes` that protects LLM output. Comments/prompts keep the repo's existing style.
- Review findings NOT acted on (accepted as-is at household scale, tracked here): `strength_signal` double-queries the strength-activity range (restructure `match_completed` to share the prefetch); `strength_proposal_muted` filters week + strength-ness in Python instead of the SQL WHERE.

## SECURITY HARDENING — pre-open-source + pre-multi-user (captured 2026-07-20, from a code read; NONE fixed yet except where noted)

Two planned routes drive this: (1) open-source the code on GitHub, (2) run the platform ourselves and invite a few friends.
Both share one root: get secrets out of the committed surface AND out of plaintext at rest.
Findings below are from reading `auth.py`, `models.py`, `config.py`, `api.py`, `garmin/client.py` on 2026-07-20 - real, not assumed.

### What is already RIGHT (keep it; do not regress)

- **App passwords are bcrypt** (`auth.hash_password` = `bcrypt.hashpw` + per-password `gensalt`).
- **Sessions are opaque 256-bit random tokens** (`secrets.token_hex(32)`), httpOnly cookie, server-side `auth_sessions` rows, 90-day expiry.
- **Invite / password-reset tokens store only the SHA-256**; the raw token appears once in the URL (`InviteToken.token_hash`).
- **Tenant isolation is correct** - `current_user` binds identity from the session cookie, NEVER from client input, and every data table hangs off `user_id`. This is the thing usually gotten wrong; it is right here.
- **Config is fully env-driven** - every secret comes from `.env` (`config.py`), nothing hardcoded in tracked source; `.env.example` exists as the placeholder template.
- **The DB is a single file OUTSIDE the code tree** (`db_path=/data/garmin_bot.db`), so code and data separate cleanly.

### ROUTE 1 - open-sourcing: architecture supports it, nothing ENFORCES it yet

**Verdict: SQLite design is well-suited to open-sourcing** (env-driven config + single external DB file + `.env.example` template already present).
**The gap: there is NO `.gitignore`, and the project is not a git repo yet.**
A naive `git init && git add .` today would commit: `.env` (real Anthropic/OpenAI keys AND a real Garmin password); `data/garmin_bot.db` (+ `-wal`/`-shm`) = the LIVE DB with bcrypt hashes, plaintext Garmin passwords, all health/GPS data; `data/*backup*.db` and `backups/*.db` (same data, several copies); `data/garmin_tokens/{id}/garmin_tokens.json` (live Garmin OAuth tokens); plus `backend/.venv`, `frontend/node_modules`, `frontend/.next`, `.DS_Store`, `.caffeinate.pid`.
**The lucky part: no git history exists yet** - a correct `.gitignore` added BEFORE the first commit means the secrets never enter history, so no scrubbing problem.
**Pre-flight (in order):** add `.gitignore` → run a one-time secret scan (`gitleaks`/`trufflehog`) → then `git init`.
Also scrub `README.md` / docker-compose / `.env.example` for any real values before the first push.
**STATUS: `.gitignore` ADDED 2026-07-20** (blocks Route 1; done first per Will). Secret scan + `git init` still to do.

### ROUTE 2 - inviting friends: solid foundation, ONE serious hole + two smaller

**THE serious hole - `garmin_password` is stored in PLAINTEXT.**
`models.py` `garmin_password: Mapped[str | None]` is a plain `String`; `api.py` writes `user.garmin_password = body.password` as-is; `garmin/client.py` reads it back to authenticate; zero encryption anywhere (grep finds no Fernet/cryptography/SECRET_KEY).
Why it matters more than the app itself: a Garmin credential unlocks GPS tracks of every run (where a friend lives / works), sleep, resting HR, full health history.
That password sits in cleartext in `garmin_bot.db` AND in every `.db` backup - any DB/backup leak or server compromise hands over friends' Garmin logins directly.
Bcrypting the app password while storing a MORE sensitive third-party password beside it in plaintext is the weak link.
**Leaning:** encrypt `garmin_password` at rest with a key from env (Fernet/AES via `cryptography`), key NEVER in the DB; add an auto-migration that encrypts existing rows on startup (same `_auto_migrate` pattern already used for additive columns). The `garminconnect` library needs the password to re-auth when cached OAuth tokens expire, so we cannot drop it entirely - encryption at rest is the realistic fix.

**Smaller issue 1 - session cookie missing `Secure`.**
`api.py` `set_cookie(...)` sets `httponly=True, samesite="lax"` but NOT `secure=True`, so over the tunnel the session token can ride a plain-HTTP hop. Fix: add `secure=True` (both `set_cookie` call sites, lines ~86 and ~217).

**Smaller issue 2 - no login brute-force throttle.**
`rate_limit.py` covers CHAT only; the `/login` path (`verify_password`) has no attempt limiter. Low risk for an invite-only group but cheap insurance: a per-IP / per-account login throttle.

**Also:** the Garmin OAuth token cache on disk (`garmin_tokens.json`, dir mode 0700) is plaintext too - lower priority than the DB password but same class; treat `.db` backups as secrets regardless.

**NOT the concern: SQLite itself.** For a handful of friends it is operationally fine (single process, low concurrency); data safety here is about the plaintext credential, backup handling, and transport - none of which change with Postgres.

**Priority order (Route 2):** (1) encrypt `garmin_password` at rest + migrate existing rows; (2) `secure=True` on the cookie; (3) treat `.db` backups as secrets; (4) login throttle.
Each is its own small reviewed change; (1) is the one that actually protects friends' most sensitive data.

**BUILD LOG — 2026-07-20 DONE + DEPLOYED (1, 2, 4; 291 backend tests green). Item 3 is operational, not code.**
- **(1) Garmin password encrypted at rest.** New `app/crypto.py` - Fernet symmetric encryption (the password must be recoverable to re-auth with Garmin, unlike the one-way bcrypt app password). Stored values are tagged `gb1:<token>`; untagged values are treated as legacy plaintext and returned unchanged on read, so nothing breaks mid-migration. Key resolution: `SECRET_KEY` env (any passphrase → derived Fernet key) else an auto-generated `<data_dir>/.secret_key` file created `0600` - deliberately OUTSIDE the DB and NOT in `.db` backups, so a database/backup leak alone cannot decrypt. Wired encrypt on write (`garmin/connect`, initial-user bootstrap), decrypt on read (`garmin/client.get_garmin`). Startup migration `auth.encrypt_existing_credentials()` (idempotent, in `main` lifespan) encrypts legacy rows in place.
- **(2) Session cookie `Secure`.** Both `set_cookie` sites now pass `secure=config.cookie_secure` (new config, default `True`; tests force `false` because TestClient is plain-HTTP). Production is HTTPS behind the Cloudflare tunnel, so the flag holds.
- **(4) Login brute-force throttle.** `rate_limit.check_login/record_login_failure/clear_login_failures` - after `LOGIN_MAX=10` failures per `LOGIN_WINDOW_S=15min` for a username, further attempts get 429 (checked BEFORE password work; keyed per-username so guessing one account can't lock out others; cleared on success). Wired into `/login`.
- **Tests:** `test_crypto.py` (4: roundtrip, non-determinism, legacy passthrough, migrate-only-plaintext) + 3 login-throttle tests in `test_auth.py`; new autouse `conftest` fixture resets in-memory rate-limit state per test. `cryptography>=42` added to `requirements.txt`. `.env.example` documents `SECRET_KEY` + `COOKIE_SECURE`.
- **Deploy (backend-only rebuild):** predeploy backup taken via the in-container SQLite backup API (`garmin_bot_backup_predeploy_encrypt_20260720.db`) - never copied the WAL DB from the host. Migration log: "encrypted 2 legacy Garmin password(s) at rest". Verified live: both users `encrypted=True` with a working decrypt round-trip; key file present `0600`; `get_garmin(user 1)` builds + logs in fine (decrypt→Garmin path intact); login throttle returns 429 on the 11th bad attempt.
- **(3) Backups as secrets — operational note (not code):** `.db` files (incl. the new predeploy backup) are already `.gitignore`d so they never reach the open-source repo; the encryption key file lives beside them but is NOT captured in a `.db` backup, so shipping a backup off-box no longer leaks Garmin credentials. Encrypting or access-restricting the backup files themselves is still a good habit but out of code scope.
- **Still open (deferred):** BYOB per-user LLM key (Phase 2) - when built, the stored user key reuses this same `crypto` encrypt-at-rest path. Garmin OAuth token cache on disk stays plaintext (dir `0700`); lower priority than the DB password, tracked but not fixed here.

## DECIDED — Tenant levels / admin separation (Will 2026-07-20; BUILDING)

Motivated by Will noticing that Julianne (a non-admin) sees the household Members section in Settings.
Goal: an invited friend should see NOTHING administrative - member management lives on its own admin-only surface.

**Current state, read from code (2026-07-20) - the fix is scoped by what actually leaks:**
- **Admin ACTIONS are already server-gated.** `POST /invites`, `POST /users/{id}/reset_link`, and member deletion all use `Depends(admin_user)` → non-admin gets a hard 403. No privilege-escalation hole.
- **The frontend already hides the action buttons** from non-admins (`me.is_admin` on the Invite button, `isAdminViewer && !member.is_me` per row).
- **What LEAKS is information + altitude, not privilege:** `MembersCard` renders for EVERYONE on `/settings`, so a non-admin sees the full roster (usernames, admin badge, Garmin-connected dots) plus a "managed by the admin" note. And `GET /members` is gated only by `current_user`, so the roster is readable by any logged-in user via the API regardless of the UI.

**DECIDED design:**
1. **Split the altitude.** `/settings` becomes PURELY personal (own display name, password, Garmin connection, coach persona, cycle, plan hour). Household administration moves to a dedicated **`/admin`** surface.
2. **`/admin` is admin-only, hidden AND gated.** An "Admin" nav item appears only for admins (desktop sidebar + mobile More); the page itself redirects a non-admin away. Crucially this is DEFENSE IN DEPTH, not UI-hiding-as-security: `GET /members` moves behind `admin_user` too, so the server is the source of truth (matters because the code is about to be open-sourced and the API will be poked).
3. **Roles stay two-level.** First user = admin (already `ensure_admin`), invitees = members (already non-admin). No new role tiers - admin/member is all this needs. Whoever runs the OSS instance administers THEIR instance; their invitees are plain members.

**Scope for THIS change (kept tight):** move `MembersCard` to `/admin`, add the gated nav item + page, gate `GET /members`.
The LLM-provider selector (already `me.is_admin`-gated inline in `AccountCard`) is left in place for now; it is another instance-level admin setting that COULD consolidate onto `/admin` later, noted as a follow-up not built here.
The `/admin` page is also the intended future home for Idea B's per-user token/cost view.

**DEFERRED - BYOB / per-user API key (explicitly NOT part of this change).**
This is a different axis (WHO PAYS for LLM calls), not authorization.
Today one shared key (`config.anthropic_api_key`) funds everyone, which is correct for the private household instance (Will WANTS to pay for a few friends; Idea B + the message rate-limiter give visibility + a spend cap).
For OPEN-SOURCE, a hybrid is the right eventual shape: instance default key (admin's) with an optional per-user override, resolved per-user-with-instance-fallback.
It is Phase-2 and inherits the "encrypt every per-user secret at rest" rule from the security section (a stored user API key is one more secret).

**BUILD LOG — 2026-07-20 DONE + DEPLOYED (284 backend tests green; tsc clean + next build clean, `/admin` route emitted).**
- **Backend:** `GET /members` moved from `Depends(current_user)` to `Depends(admin_user)` - the roster is now 403 for non-admins (the actions were already admin-gated). New test `test_members_list_is_admin_only` locks it (non-admin → 403); `test_members_list` still green for the admin path.
- **Frontend:** `CoachProvider` now fetches `authMe` alongside settings and exposes `useIsAdmin()` (new `IsAdminContext`). Sidebar + MobileNav append an admin-only "Admin" item (Shield icon, `/admin`), gated by `useIsAdmin()`. New `app/admin/page.tsx` hosts `MembersCard`, guards client-side (redirects non-admins / logged-out to `/` via `router.replace`) as UX on top of the server gate. `MembersCard` removed from `/settings` (import + render), so a non-admin's Settings is now purely personal.
- **Defense in depth honored:** the client redirect + hidden nav are UX; the real boundary stays the server (`admin_user` on `/members` and all mutations).
- **Deployed 2026-07-20** via `docker compose up -d --build` (code-only, no migration; `./data` DB volume untouched). Live smoke: unauth `GET /api/auth/members` → 401 (was any-logged-in-user before), frontend `/` 200, `/admin` route 200.
- **Not done (as scoped):** LLM-provider selector stays inline in Settings `AccountCard` (still `me.is_admin`-gated); consolidating it onto `/admin` is a noted follow-up. BYOB per-user key remains deferred (Phase 2). Still pending: eyeball in a logged-in browser through the tunnel - as Julianne (no Admin nav item; `/admin` redirects her home) and as Will (Admin item + roster render).

## DECIDED — Token/cost accounting + LLM provider on /admin (Idea B) — BUILT + DEPLOYED 2026-07-20

Self-monitor at the seam (NOT per-user provider keys - that's BYOB/Phase 2), store in SQLite, render on the `/admin` page we just built. No Grafana (over-engineering at household scale; the table exports later if ever needed).

**BUILD LOG — DONE + DEPLOYED (296 backend tests green; tsc + next build clean; live-verified a real row).**
- **Seam captures usage.** New neutral `usage.Usage{input, output, cache_read, cache_creation}`. `make_client(provider, *, user_id, call_site)` binds attribution to the client; each client records after every call. Anthropic maps its split counters straight across (usage is already on `get_final_message()`); OpenAI needed two fixes - `stream_options={"include_usage": True}` and capturing the trailing usage-only chunk BEFORE the `if not chunk.choices: continue` guard - and subtracts `cached_tokens` out of `prompt_tokens` so cost isn't double-counted. `usage.record()` is best-effort (never breaks a chat/plan) and skips unattributed calls (user_id=None, e.g. tests).
- **Storage + cost.** New `LlmUsage` table (auto-created by `create_all`, no migration): `user_id, ts, provider, model, call_site, {input,output,cache_read,cache_creation}_tokens, cost_usd`. `usage.PRICES` = per-model USD/1M rates for input/output/cache-read/cache-write, matched exact → longest-prefix → `_DEFAULT`. Tokens exact; cost is the editable estimate.
- **Attribution wired** at all four `make_client` sites: `plan`, `review`, `execution_analysis` (planner), `chat` (agent). Each already had `user_id` in scope.
- **Admin endpoint.** `GET /api/auth/usage?days=30` (`admin_user`-gated) aggregates total + `by_user` + `by_call_site` with a cache-hit %. `days` clamped 1..365.
- **`/admin` LLM section.** New `AdminLlmCard` = provider selector (moved off Settings - the follow-up from the tenant-levels change is now DONE) + 30-day usage: cost/tokens/cache-hit stat tiles, a by-feature table, a by-member table. `MembersCard` + `AdminLlmCard` now compose the admin page; Settings `AccountCard` no longer holds the provider dropdown.
- **Tests:** `test_usage.py` (6: per-component cost, prefix/default rates, record writes-row + skips-unattributed, endpoint aggregation + admin-only). Fixed 5 pre-existing `make_client` stub lambdas across tests to accept the new kwargs (`lambda provider=None, **_kw: stub`).
- **Live-verified:** one real chat turn wrote exactly one row - `openai/gpt-5.6-luna`, `call_site=chat`, 3026 in / 8 out, $0.00386 (cost via `gpt-5` prefix fallback since `gpt-5.6-luna` isn't in `PRICES` - add an entry for exact cost). Table present, endpoint 401 unauth.
- **Price map filled with real rates (2026-07-20).** Will supplied OpenAI's sheet; `PRICES` now carries the gpt-5.x family (Standard tier, short-context): `gpt-5.6-sol/terra/luna`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.4` + `-mini/-nano/-pro`. Live model `gpt-5.6-luna` = $1.00 in / $0.10 cached / $1.25 cache-write / $6.00 out. Anthropic rates (`claude-opus-4-8` etc.) remain best-estimate until the live Anthropic model is confirmed. After the redeploy the seam's 1 test chat row + its chat session were deleted, so accounting starts from a clean slate.
- **Follow-ups:** confirm the live Anthropic model's rates; optional per-request provider tagging (OpenAI `user` / Anthropic `metadata`) as belt-and-braces; a time-series view if 30-day totals aren't enough. BYOB per-user keys stays Phase 2 and will reuse the `crypto` encrypt-at-rest path.

## IDEAS — not yet spec'd (captured 2026-07-18, Will raised, design still open)

Two features Will floated; neither is thought through yet.
Recording the technical findings so we don't re-derive them, plus the open design questions to settle before a build spec.

### Idea 1 — Hill runs as a workout type

Want: prescribe hill/elevation-interval sessions and (eventually) grade the athlete on them.

**Technical finding — Garmin CANNOT trigger or target intervals by elevation.**
Garmin's structured workout format (the FIT workout schema the watch executes) supports these step triggers only: time, distance, calories, HR-above/below, and "open" (lap-button press) — there is NO "climb X meters" trigger for running.
Step targets are pace/speed, HR, cadence, or power — grade exists in the FIT spec ONLY as a trainer-resistance target for indoor cycling, so the watch will not enforce "you're on a 6% grade, push."
Consequence: a hill workout on Garmin is normal time-/distance-based intervals PLUS a text instruction telling the runner where to run them; the watch cannot know or enforce that it happened on a hill.
NOTE: this is from the FIT spec, NOT yet verified against our actual `garminconnect` push path — verify the exact supported step trigger/target types before committing to a build.

**Leaning (not decided):** prescribe hills by EFFORT (HR or effort target) with a text cue like "on a 4-6% grade", not by pace (uphill pace is a meaningless target).
HR naturally absorbs the extra load of the climb, so the target stays honest across grades.
On analysis we DO get the activity's elevation gain back from Garmin, so we can VERIFY a hill run actually happened on a hill even though the watch could not enforce it.

**Open questions:** how does a hill workout render on the plan / push to the watch; effort vs pace target; how the coach decides when to program one; do we verify-by-elevation on completion.

### Idea 2 — Post-run execution score + LLM analysis

Want: for every completed run, generate (a) an execution score on how we did vs the prescription, and (b) a written analysis.
Will's own question: should the score be purely computed, with only the analysis from the LLM.

**Leaning (strong) — score is PURELY deterministic; only the textual analysis comes from the LLM.**
Reasons: a score must be comparable/trendable over time (an LLM number drifts and isn't calibrated, so an 82 in March would not mean an 82 in June); the comparison is structured and we already hold both sides (prescription = target pace/HR + interval structure + duration/distance + the day; actuals from Garmin); it matches the existing architecture where deterministic signals (`readiness`, `structural_signals`) feed the LLM — execution score is just another deterministic signal and the analysis is the LLM layer on top; and LLMs are unstable judges but good narrators, so asking one to both score and explain invites it to rationalize its own number.
Compute a weighted 0-100 from a few clean planned-vs-actual components: completion (happened, right day, right volume), structure adherence (reps landed in the target band), intensity match (splits/HR vs prescribed zone as a band not a point), volume match.
Weight by workout type — a hard interval session leans on intensity+structure; an easy run leans on staying BELOW a HR cap, so going too hard should COST points (a naive "faster = better" score misses this).
Then hand the LLM `{prescription, actuals, score, component_breakdown}` and let it write the coaching narrative referencing the numbers rather than inventing them; the deterministic score means the prose can't contradict it, and the breakdown can show in the UI as the receipts behind the analysis.

**Load-bearing caveat to honor:** score against the FINAL prescription AFTER Idaten's edits, not Garmin's original — if Idaten itself eased the plan (cycle, low readiness) a "missed" hard session must not be graded as a failure.

**Scope narrowed (Will, 2026-07-19):** score ONLY Run/treadmill activities, and ONLY when the run was an attempt at that day's planned workout (Garmin coach plan OR Idaten plan). A regular/casual run is NOT scored. No per-component weighting — keep it simple. So the crux is ATTRIBUTION (was this run an attempt at the plan), and the four-tier model below decides it; scoring is the easy downstream half.

**Attribution — four tiers (Will agreed 2026-07-19):**
1. Definitive link → score silently (no prompt).
2. Strong shape match on a planned non-rest day, single run → score silently.
3. Genuinely ambiguous (planned workout exists but run looks nothing like it / planned rest but ran hard / two runs that day) → ONE lightweight confirm, folded into the EXISTING Today RPE moment (`RpeCard`), NOT a new nag; ask about the SPECIFIC workout ("Was this your Threshold session?" [Yes / No, just a run]); remember "No" and never re-ask for that activity.
4. No plan / rest day / obviously casual → no score, no ask, ever.
Bias: when unsure, DON'T score. In a coaching-relationship app an unfair score on a casual jog is worse than a missing one.

**SPIKE RESULT (2026-07-19, read-only `get_activity` against both live accounts).** Answered the two design-deciding questions:
- **William (Garmin 255) — Garmin already scores plan runs.** `summaryDTO.directWorkoutComplianceScore` is present on his Garmin-coach-plan runs (live values 91 / 86 / 60 / 34 — the 34 was his Tempo, so it's a real per-workout adherence score) and ABSENT on his free runs. So for a Garmin-plan run on the 255 we PULL Garmin's score, we do not compute.
- **Julianne (Garmin 165) — no score at all.** Her plan runs carry `trainingEffect` but ZERO `directWorkoutComplianceScore`. Her watch does not compute it → we compute for her.
- **Attribution link (bonus, both users):** every coach-plan run carries `metadataDTO.trainingPlanId` (Will `45820109`, Julianne `45820254`); free runs do not. This is a TIER-1 attribution signal for Garmin-coach runs on BOTH watches — if `trainingPlanId` is present, Garmin already decided the activity executed the coach plan, so no shape-match or prompt is needed. Covers most real traffic today (both live users are editor-mode on the Garmin coach plan).
- Case matrix: Garmin-plan run on 255 → attribute by `trainingPlanId`, PULL `directWorkoutComplianceScore`. Garmin-plan run on 165 → attribute by `trainingPlanId`, WE compute. Idaten-pushed run (either watch) → WE compute (attribution gap, see below). Free run → tier 4, no score.

**Gaps to settle at spec time:**
- **Idaten-push attribution has no per-workout link.** `get_activity` exposes `trainingPlanId` (coach plan) but NOT a `workoutId` for an individually pushed workout — so Idaten-push attribution can't match by id from this payload; fall back to date + shape match, or find the linkage on the scheduled-workout/calendar endpoint. Only matters once an Idaten workout is actually pushed.
- **Does the 255 also score an Idaten-pushed workout?** `directWorkoutComplianceScore` is Garmin's "did you follow the structured workout" score; if Idaten pushes a structured workout to the 255, the watch MIGHT produce a compliance score against our targets too (→ pull, not compute, even for Idaten runs on the 255). Untestable until the first live Idaten push to Will's watch — probe then.

**Score source = CAPABILITY detection, never device detection (Will's requirement 2026-07-19, DECIDED).** Do NOT branch on watch model (255 vs 165) — that needs a stale allowlist. Detect the FIELD: `summaryDTO.directWorkoutComplianceScore` present → PULL Garmin's score; absent → COMPUTE ours. Presence is per-ACTIVITY not per-device, so this is self-correcting for every edge: a free run on a 255 emits no compliance score (no workout to comply with) → absent → not scored anyway (tier 4); an Idaten-pushed workout on a 255 → if Garmin scores it the field appears (pull), if not it's absent (compute) — resolves the earlier "does the 255 score Idaten workouts" gap with zero foreknowledge; any future watch that emits the field is supported with no code change. The system reduces to two orthogonal checks, neither naming a device: (1) attribution (four tiers; `trainingPlanId` covers the coach-plan case), (2) score source (`directWorkoutComplianceScore` present ? pull : compute).

**Field dump (2026-07-19, full `summaryDTO` + `get_activity_splits` both accounts):**
- William 255 plan run: `summaryDTO` 54 keys — `distance`, `duration`/`movingDuration`, `averageHR`/`maxHR`/`minHR`, `averageSpeed`/`maxSpeed`/`avgGradeAdjustedSpeed`, `trainingEffect`/`trainingEffectLabel`, plus `directWorkoutComplianceScore` 86 / `directWorkoutRpe` 30 / `directWorkoutFeel` 50. `get_activity_splits` → `lapDTOs` carry per-lap `intensityType`, per-lap `directWorkoutComplianceScore`, and `wktStepIndex`/`wktIndex` (the STRUCTURED-WORKOUT-STEP linkage → enables per-interval scoring where present).
- Julianne 165 plan run: `summaryDTO` 41 keys — same core fields (distance/HR/speed/cadence/trainingEffect + `directWorkoutRpe`/`directWorkoutFeel`) but NO `directWorkoutComplianceScore` and NO `wktStepIndex` linkage. Records the run fine, just no compliance.
- `splitSummaries` on both is a run/walk/stand ROLLUP (`RWD_RUN`/`RWD_WALK`/`INTERVAL_WARMUP`…), NOT the prescribed steps → for structure adherence use `lapDTOs` (with `wktStepIndex`), fall back to aggregate `summaryDTO` when step indices are absent. For a simple easy/tempo run, aggregate (avg HR-in-band + distance/duration + avg pace vs target) suffices for v1; interval-structure scoring is the enhancement.

**Provenance (DECIDED direction):** store a score-source tag (`garmin` vs `idaten`), same pattern as `rpe` vs `garmin_rpe`. Compute ours on the SAME 0-100 scale and calibrate toward Garmin's `directWorkoutComplianceScore` on the same run so a score means the same thing on both watches.

**How Garmin scores it — CONFIRMED empirically (2026-07-19 read-only correlation spike, William's scored runs).** `directWorkoutComplianceScore` = time-integrated closeness of actual HR/pace to the prescribed step's TARGET BAND, per step, aggregated over the workout. Evidence:
- Base run 07-13, overall 60, single easy step auto-lapped per km — score climbs purely with HR toward the band: lap HR 124→compliance 0, 143→21, 157→47, 154→60. Same target, so the score IS the HR-vs-band closeness. (Per-lap value is cumulative: last lap 60 = overall 60; the single-lap Base 07-16 scored 86 = its overall.)
- Tempo run 07-15, overall 34: warmup lap 61, tempo interval lap 44, then COOLDOWN laps run at 167-169 bpm (tempo effort, wrong intensity for a cooldown) dragged the total to 34 — proves it is PER-STEP and penalizes wrong intensity on the wrong segment; overshoot is penalized like undershoot.
- HR is the axis for HR-targeted coach workouts (pace where the step is pace-targeted). Coach target bands live SERVER-SIDE (`associatedWorkoutId` null on coach runs → can't read the bands), which is fine: for the runs WE score we wrote the prescription and own the targets.

**Scoring FUNCTION (DESIGNED 2026-07-19) — one time-integrated number, mimics Garmin.** Completion + structure + intensity collapse into a single metric:
```
score = 100 × ( ∫ credit(t) dt over the FULL prescribed duration ) / prescribed_duration
```
- `credit(t)` = closeness of actual intensity at time t to the target band of the PRESCRIBED step active at t: inside band → 1.0; outside → linear decay to 0 across a tolerance margin beyond the edge (HR ≈ ±12 bpm, pace ≈ ±8-10%); falloff SYMMETRIC (too hot penalized like too easy — matches the tempo-cooldown case).
- Integrate over the PRESCRIBED (not actual) duration → completion falls out for free: bail at half → unrun half is credit-0 → caps ~50; wrong-intensity segment → ~0. No separate completion/structure/volume terms, no weights (per Will).
- Axis: HR for HR-targeted steps, GRADE-ADJUSTED pace (`avgGradeAdjustedSpeed`) for pace-targeted so hills don't unfairly punish. Inputs we already hold: the final post-Idaten prescription (band + duration per step) + cached `Activity.series` (`{t_s, hr, …}`) + `splits`/`lapDTOs` for step alignment.
- Edge cases: aborted early → low via the integral (LLM note says "cut short"); no HR → fall back to pace axis; rest-day override / free run → not attributed (tiers 3-4), never scored. Score against the FINAL post-Idaten prescription, never Garmin's original.

**Calibration (validation plan):** we have William's Garmin scores (86 / 34 / 60) AND his HR series for those exact runs → tune the one knob (tolerance margin) until the formula reproduces ~86/34/60, then trust it on runs Garmin doesn't score (165, Idaten-pushed). Same-scale guarantee: a 60 means the same on every watch.

**Targets availability — DECIDED (2026-07-19 read-only spike, both accounts).** Garmin does NOT expose coach-workout step targets: the coach `taskWorkout` has `workoutId=null` and only workout-level metadata (`workoutName`, `trainingEffectLabel`, `estimatedDurationInSecs`, `estimatedDistanceInMeters`, prose `workoutDescription`) — no steps, no bands, nothing fetchable. So the scoring function keeps ONE formula but has TWO target sources:
- Idaten-pushed run → READ our own per-step bands (we wrote them) → per-step scoring.
- 255 Garmin-coach run → PULL Garmin's `directWorkoutComplianceScore` (field present).
- 165 Garmin-coach run (Julianne, the motivating case) → DERIVE targets: each actual lap's `intensityType` (WARMUP/INTERVAL/COOLDOWN) + the day's `trainingEffectLabel` → an HR-zone band from the ATHLETE'S OWN stored HR zones; run the same time-in-band formula per lap. Degrades to whole-run aggregate if laps lack `intensityType` (verify at build time).

**Storage (DECIDED):** `execution_score` (int 0-100) + `execution_score_source` (`garmin`|`idaten`) columns on `Activity`, additive/auto-migrating, mirroring the `rpe`/`garmin_rpe` provenance pattern. Optional per-segment breakdown JSON for the UI/LLM (recompute vs persist — settle in build).

**Review feedback (DECIDED — Will, 2026-07-19):** the execution score FEEDS BACK into the daily review — a recent-execution-score signal added to `build_snapshot` + a `REVIEW_SYSTEM_PROMPT` bullet (a string of low scores → ease the next block; consistently high → clear to progress). Third retrospective signal alongside readiness/structural.

**READY TO BUILD (2026-07-19) — all architectural unknowns closed. Build order:**
1. Scoring CORE — pure `metrics.execution_score(...)`, both target sources, unit-tested + CALIBRATED against William's known Garmin scores (86/34/60 + his HR series → tune the tolerance margin). No wiring, no risk.
2. Attribution + ingest — four-tier attribution + `present ? pull : compute`, wired into `enrich_activity`; new `Activity` columns; backfill recent runs.
3. Tier-3 prompt — "Was this your {Threshold} session?" folded into the existing `RpeCard`, answer persisted (never re-ask for that activity).
4. Review feedback — recent-score signal into `build_snapshot` + `REVIEW_SYSTEM_PROMPT`.
5. Analysis + UI — LLM writes the narrative from `{score, per-segment breakdown}` (never the number); surface score + analysis on activity detail + Today; trend over time.

**Still-open (settle in build):** exact tier-2 shape-match thresholds; recompute-vs-persist the per-segment breakdown; UI trend surface.

**BUILD LOG — Phase 1 (scoring core) + Garmin-zones unification DONE 2026-07-19 (built + 234 tests green; NOT deployed):**
- **`metrics.execution_score(series, segments, *, tol_hr, tol_speed_frac)`** — pure time-integrated band-closeness scorer. `_band_credit` (1.0 in band, symmetric linear decay to 0 across tolerance). Denominator = PRESCRIBED total so bail-early and wrong-intensity both fall out of one integral. Returns `{score 0-100, breakdown[per-segment {label, axis, target, duration_s, avg_actual, score}]}`. HR axis absolute (tol bpm); pace axis on speed_mps (tol = fraction of band midpoint).
- **`metrics.derive_hr_band(intensity_type, te_label, hr_zones)`** — target for coach runs Garmin doesn't score: warmup/cooldown/rest → z1; RECOVERY intent (label OR intensity) → z1-z2 span; work → TE-label zone (AEROBIC_BASE→z2, TEMPO→z3, THRESHOLD→z4, VO2MAX/SPEED→z5).
- **Zone basis = Garmin's own per-athlete boundaries.** `metrics.hr_zones_from_garmin(payload)` reads `zoneLowBoundary` from the `get_activity_hr_in_timezones` payload we ALREADY fetch in enrich — this is whatever basis (max HR / %HRR / %LTHR / manual) the athlete configured in Garmin, so we match Garmin's scoring without implementing any zone math. Works for Julianne's 165 (whose `get_lactate_threshold` is null) where LTHR-derived zones can't.
- **CALIBRATED** against William's real runs vs Garmin's `directWorkoutComplianceScore`: with Garmin-boundary bands, `tol 10 bpm` → MAE ~9 with correct ordering (Base 60→59, 91→92, 89→89; RECOVERY 86→97; botched TEMPO 34→50). Residual is irreducible heuristic slack (Garmin's exact per-workout targets are hidden). Locked `EXEC_TOL_HR=10`. Earlier LTHR-Friel bands gave MAE ~22 (LTHR=186 was a stale max-HR artifact) → rejected.
- **Zones unified as ONE source (folded in per Will).** New `settings_store.hr_zones(db, uid)` = cached Garmin boundaries (`GARMIN_HR_ZONES_KEY`, own internal key so `sync_profile`'s wholesale write can't wipe it; `put_garmin_hr_zones` keeps the newest observation, captured during enrich update-if-newer) → else LTHR-Friel fallback. `planner._hr_zones` and the activity-detail `hr_zones` in `api.py` now both call it. FIXES the latent planner bug where HR targets were anchored on the bad LTHR (base prescribed at z2=[158,166] vs real [144,161]).
- **Tests:** `test_execution_score.py` (24: band credit, perfect/too-easy/partial, bail-early cap, botched-cooldown structure, pace axis, guards, derive_hr_band incl. RECOVERY span, hr_zones_from_garmin boundaries). Full suite 234 green.
- **DEPLOYED 2026-07-19 (Will OK'd):** backend rebuilt + live; zones backfilled (2 calls). Will z2 corrected [158,166]→[144,161]; Julianne went from NO zones (null LTHR) to a full Garmin-derived set. `parse_splits` now also carries `intensity` + `step_index` (Phase-2 enabler, shipped same deploy).

**BUILD LOG — Phase 2 (attribution + ingest) DONE + DEPLOYED 2026-07-19 (243 tests green; backend-only, no UI/watch/plan change):**
- **`Activity` columns** (additive/auto-migrated): `execution_score` (int 0-100), `execution_score_source` (`garmin`|`idaten`), `execution_breakdown` (JSON per-segment).
- **`app/execution.py`** — two orthogonal decisions, neither naming a device. Attribution (tier-1 only for now): `metadataDTO.trainingPlanId` present (coach run) OR an Idaten-pushed PlanDay (`garmin_workout_id` set, non-rest); else unscored (free/ambiguous → Phase 3 prompt). Score source: `directWorkoutComplianceScore` present ? PULL (source=garmin) : COMPUTE (source=idaten). Compute path: coach runs derive per-lap bands from `intensity` + TE label + Garmin zones (`_coach_segments`); Idaten-pushed runs use our own `PlanDay.steps`/simple targets (`_idaten_segments`); coach path preferred whenever `trainingPlanId` present (real per-step structure).
- **Wired into `enrich_activity`** — the `get_activity` payload fetched for RPE/feel is reused (summaryDTO + metadataDTO); scoring runs after series/splits populate, best-effort (never fails enrich).
- **Backfill (120d, both users)** — Will 19 scored (18 pulled from his 255 = his real 86/34/60/91, 1 computed; 40 free runs correctly unscored); Julianne 43 scored (all computed on her 165, all per-segment; 4 free unscored). Re-fetched splits so historical runs gained `intensity` → true per-segment.
- **Bug caught + fixed live:** laps cached before the `intensity` field were all judged as "work", zeroing warmups/cooldowns. Fixed `_coach_segments` to require real `intensity` (else whole-run fallback) + backfill re-fetches splits. Verified: Julianne's 7/16 Threshold now reads WARMUP 71 / intervals 66-78 / recoveries 35-47 / COOLDOWN 0 (ran it at 172 bpm) → overall 65 — a real, legible coaching story.
- **Tests:** `test_execution_ingest.py` (9: attribution incl. free-run/rest-day guards, pull-vs-compute, segment builders, no-intensity fallback) + `test_phase2` split-fields. Suite 243 green.
- **Still open:** tier-2 shape-match + tier-3 prompt (Phase 3); historical per-segment needs the re-fetch (done for the 120d window; older runs stay unscored/whole-run). Next: Phase 3 (ambiguous-run prompt) or Phase 4 (feed scores into the daily review).

**BUILD LOG — Phases 3 (attribution prompt) + 4 (review feedback) DONE + DEPLOYED 2026-07-19 (254 tests green; tsc + next build clean):**
- **Phase 4 — execution scores feed the daily review.** `metrics.execution_signals(db, uid, today, n=6)` — deterministic summary of the last N scored runs `{recent[newest-first {date,score,source,type}], count, avg_score, low_streak}` (`low_streak` = consecutive most-recent runs below `EXEC_LOW=50`). Added to `build_review_snapshot` alongside `structural_signals`; new `REVIEW_SYSTEM_PROMPT` bullet (a run of low scores → ease the next hard session / bank recovery, name it warmly; consistently high + good readiness → green-light progression; don't over-react to one off day; a low score can be over-cooking an easy run as much as under-hitting a hard one). LIVE-verified in the snapshot (no LLM spend): Will 6 scores avg 68 (garmin), Julianne 6 avg 65 (idaten).
- **Phase 3 — the ambiguous-run prompt (tier 3).** New `Activity.execution_attributed` (bool|None: None=undecided, True=confirmed→scored, False="just a run", never re-asked). `execution.prompt_label(db, a)` — eligible iff a run, unscored, undecided, a planned NON-rest workout exists that day (Idaten PlanDay or coach task), and no sibling run that day already covers it. `execution.score_confirmed(db, a, zones)` scores a confirmed run against that day's prescription (Idaten steps, or coach TE-label→derived band). `POST /activities/{id}/attribution {attempted}` — Yes attributes+scores, No declines. `/dashboard/today` gains `attribution_prompt {activity_id, workout_label}`. Tier 1 still auto-scores silently; tier 4 (free/rest) never asks. (Tier-2 auto-shape-match still deferred — for the live editor-mode users everything is tier-1 coach runs, so the prompt rarely fires.)
- **UI** — `AttributionCard` ("Was this your {Threshold} session?" · Yes score it / No just a run), folded into the Today RPE moment (not a new nag), optimistic-hide, toasts the score. Wired after `RpeCard` on Today.
- **Tests** — `test_execution_review.py` (11: signal summary + low-streak, prompt eligibility incl. scored/declined/no-plan/sibling guards, confirm-scoring coach+idaten, endpoint yes-scores/no-declines). Suite 254 green.
- **DEPLOYED** — backend (auto-migrated `execution_attributed`) + frontend live; review-signal change verified in-snapshot without LLM spend.
- **Still open:** Phase 5 (analysis LLM narrative + UI surface: score + per-segment breakdown on activity detail / Today / trends); tier-2 auto-shape-match; live browser eyeball of the AttributionCard (fires only on an ambiguous run — none in current live data).

**FIX — score against the FINAL (Idaten) plan, not Garmin's original (Will caught it 2026-07-19, DEPLOYED):**
Bug: `score_run` used the coach path whenever `trainingPlanId` was present, so an editor-mode day the athlete had accepted an Idaten EDIT on (Garmin still tags the run with `trainingPlanId` inside the coach-plan window) was scored against Garmin's structure — violating the documented load-bearing rule. Fix: `is_idaten_plan = non-rest PlanDay AND planner._is_override(...)` (an accepted `chat_edit`/`manual` edit, or author-mode day) now takes precedence — such a day scores against Idaten's prescription even when `trainingPlanId` is present. Garmin's compliance score is pulled ONLY when the structured workout on the watch WAS the plan being scored (a plain coach run, or an Idaten day we actually pushed); a non-pushed Idaten edit computes ours instead (the watch still holds Garmin's workout, so its score is against the wrong target). Also clarifies the prompt story: author-mode + not-pushed → no watch link → the AttributionCard fires (its primary path); author/edit + pushed → auto-scored vs Idaten's plan. Tests: `test_idaten_override_scores_against_idaten_not_coach`, `test_idaten_override_ignores_garmin_compliance_when_not_pushed`. Suite 256 green.

**BUILD LOG — Phase 5 (analysis narrative + UI surface) DONE + DEPLOYED 2026-07-19 (265 tests green; tsc + next build clean). FEATURE COMPLETE.**
- **Lazy analysis, bounded to recent runs (Will's rule).** New `Activity.execution_analysis` (text, null until generated). `planner.write_execution_analysis(db, a)` — one persona-voiced LLM call (`EXECUTION_ANALYSIS_SYSTEM_PROMPT` + `style_prompt`, schema `{analysis}`) from the score + per-segment breakdown; invents no numbers. `POST /activities/{id}/analysis` generates once + caches; **hard-gated to runs ≤2 days old** (`ANALYSIS_MAX_AGE_DAYS`) so browsing old history can NEVER spend a call — a guard, not just a caller convention. The Today page load is the ONLY trigger; the activity-detail page displays cached text but never generates. Net: ~2 lazy calls on an active running day (morning review + post-run analysis), zero on an unopened/no-run day. Deterministic SCORES exist for all runs (old + new); the LLM NARRATIVE is today-onward only.
- **Today: plan-card → result-card swap.** `/dashboard/today` gains `completed_workout` (today's plan-attributed scored run). Frontend `ResultCard` replaces `TodayWorkoutCard` once the run is scored — shows the score at a glance, fires the lazy analysis on mount, links to the breakdown. `_activity_dict` now carries `execution_score`/`source`/`breakdown`/`analysis` everywhere a run appears.
- **Activity detail: receipts.** `ExecutionScore` component (score badge + source tag + per-segment target-vs-actual breakdown, HR in bpm / pace in min-km) on the detail page; shows cached analysis, never generates.
- **Live-verified prose** (real LLM on Julianne's 7/16 Threshold, score 65): correctly read the breakdown — "handled the threshold reps fairly well… recoveries were the main miss, they stayed too hard… cooldown was cut very short" + a specific forward nudge; never quoted the raw score. Old run → not persisted (stays analysis-less by design).
- **Tests:** `test_execution_analysis.py` (4: generate-once-then-cache, refuse old run w/ zero spend, refuse unscored, Today surfaces completed_workout). Suite 265 green.

**BONUS — Trends default filter (Will, 2026-07-19, DEPLOYED):** Trends no longer hard-defaults to 90d. Added a **7d** option; the range is persisted in `localStorage` (`trends_range_days`) and restored on return; first-ever visit defaults to **7d**. Resolved on mount (null until then) to avoid a hydration mismatch + a wasted fetch at the wrong range.

**BONUS — Trends 7-day view renders by DAY (Will, 2026-07-19, DEPLOYED):** on the 7d filter the two "weekly" charts collapsed to one or two fat bars. Now: "Weekly distance" → "Daily distance" (per-day bars from `TrendPoint.distance_km`); "Time in zones" → daily via a new `zones_daily` on `/analytics` (same shape as `zones_weekly` but keyed by `date`). `ZonesWeeklyChart` generalized to a `start`-keyed bucket (week_start or date); `easySharePct` reflects the shown range. 30/90/180 stay weekly. Also fixed a stray em-dash in the static "80/20 easy vs hard" footer (frontend text, not LLM, so the strip didn't cover it).

**BONUS — About page hidden from nav (Will, 2026-07-19, DEPLOYED):** removed the `/about` links from the desktop sidebar + mobile More (dropped the now-unused `Info` import). Route + page code KEPT; restore by re-adding the two `{ href: "/about" }` nav entries.

**REFINEMENT — forward-looking + coach-attributed analysis (Julianne's feedback 2026-07-19, DEPLOYED):**
Julianne wanted the analysis to (1) look forward — is she on track to her race goal, kept HONEST — and (2) read/look like her coach (Koa) wrote it, remembering the coach even after a switch.
- **Forward-looking + honest.** `planner._execution_context(db, uid, date)` feeds the analysis the primary race's goal vs current prediction (`vs_goal_s`: <0 ahead / >0 behind, + confidence) and the recent execution trend. `EXECUTION_ANALYSIS_SYSTEM_PROMPT` now connects the run to the race-goal trajectory but grounds every "on track" claim in `vs_goal_s`/`recent_execution` — no goal or low confidence → it SAYS so rather than fabricating. Live-verified on Julianne's 7/19 long run (score 80): "…118 days to the half and a low-confidence prediction, there isn't enough race data to claim a clear trajectory yet" — exactly the honesty asked for.
- **Coach-attributed + remembered.** New `Activity.execution_analysis_coach` stamps the `coach_style` at generation time; `write_execution_analysis` returns `(text, coach)`; the endpoint returns `{analysis, coach}`. Frontend renders the analysis via the shared `CoachNote` (avatar + name) using `personaForStyle(stored_key)` — so it shows Coach Koa's face/voice, and a later coach switch never re-labels who wrote it. The SCORE keeps its own provenance ("scored by your watch" / "by Idaten"); the ANALYSIS is the coach's note — two distinct attributions.
- **Bug fixed inline:** `_execution_context` first called `races.latest_predictions` (a dict) where `race_dict` needs a `PredictionContext` → switched to `races.prediction_context`. Suite 278 green.

**HOUSE STYLE — no em-dashes in any LLM text (Will, 2026-07-19, DEPLOYED):** em-dashes read as "an AI wrote this". Belt-and-braces: (1) `style_prompt` now appends a `_HOUSE_STYLE` line forbidding em-dashes, appended to EVERY athlete-facing system prompt (plan, review, execution note, chat); (2) deterministic `planner.strip_em_dashes()` (— ― and long bars → spaced hyphen, en-dashes/ranges left intact) folded into `clean_llm_text` (covers coach_note, execution analysis, plan title/description/rationale, edit summaries) AND applied per-delta in the chat stream (so live + persisted chat are clean). Both live analyses regenerated clean. Tests in `test_clean_llm_text.py`. Suite 280 green.

**COMPLETED-DAY LOCK + Week indicator (Will, 2026-07-19, DEPLOYED):** a matched run now flips its `PlanDay.status` planned→completed (in enrich after scoring, and in the attribution endpoint on Yes) via `execution.mark_day_completed` (only planned→completed; leaves skipped/override alone). This LOCKS the day — `apply_plan_days`, `materialize_coach_plan`, and `revert_to_garmin` already skip non-planned days, so "Ask Koa to adjust", "Replace with Garmin", and the daily re-materialize never touch a finished session. `/plan/week` days[] gain `execution {score, source, activity_id}`; the Week card shows a green "✓ Done" badge + an "Execution N" chip linking to the run, and hides Revert/Other-sport on completed days. One-time backfill flipped the 3 existing scored days (Will 7/16 + 7/19, Julianne 7/19). Test `test_mark_day_completed_only_flips_planned`. Suite 282 green.

**FEATURE STATUS: execution score + analysis is COMPLETE (Phases 1-5 + fixes + forward-looking/coach-attribution refinement, all deployed).** Remaining nice-to-haves (not built): tier-2 auto-shape-match; a Trends line for execution score over time; live browser eyeball of the Today result-card swap + AttributionCard (fire only on a fresh run / ambiguous run — none in current live data).

## DECIDED — Plan preview / detail page (BUILT + DEPLOYED 2026-07-19, Will)

Every Plan card on Today and Week is selectable and opens `/plan/[date]` — a preview of what that run actually looks like before running or pushing it. See `API_CONTRACT.md` v1.19.

**URL key = `date`, not an id (DECIDED).** `PlanDay`'s PK is `(user_id, date)`; there is no numeric plan id (`garmin_workout_id` only exists once pushed). Route `/plan/[date]` — the one stable, shareable, deep-linkable key. Backend: one new `GET /api/plan/day?date=` → `{ mode, day, intent, hr_zones }` (same `PlanDay` shape as `week.days[]`; `null` day when nothing's materialized; 422 on bad date). No `PlanDay` shape change.

**THE LOAD-BEARING FINDING — Garmin's API does NOT expose step breakdowns for coach workouts (live spike 2026-07-19, both accounts).** The motivating idea was "show warmup / main / cooldown stages". The daily plan for BOTH live users is a Garmin Coach **adaptive** workout (`itemType: fbtAdaptiveWorkout`, `tpType: FBT_ADAPTIVE`), and it carries NO fetchable steps:
- `taskWorkout.workoutId` is `null`; a recursive search of the whole `get_adaptive_training_plan_by_id` payload finds ZERO step/segment/target fields. Only a compact `workoutDescription` string exists (e.g. `"15:00@172bpm"`, `"2x3x0:15@All Out"`) — which encodes the MAIN set only, not the warmup/cooldown/recoveries.
- The only other handle is a `workoutUuid`; `get_workout_by_id` rejects it (wants an int), `get_scheduled_workouts(year,month)` calendar item is `workoutId: null` too, and ~10 guessed adaptive/FBT endpoints 404/empty.
- The pretty step view in the Garmin Connect app (暖身/跑步/緩和 with HR bands) is rendered **client-side by Garmin's app** — it wraps standard WU/CD around the compact main-set and colors it with the athlete's zones. It is NOT an API field.
- Steps ARE retrievable via `get_workout_by_id(workoutId)` → `workoutSegments[].workoutSteps[]` for any workout with a real `workoutId` — i.e. saved-library workouts and **Idaten-pushed** workouts. Confirmed live. So the gap is ONLY the Garmin-authored adaptive days.
- This overturns the earlier execution-score spike's aside ("coach `taskWorkout` has nothing fetchable") only in framing: correct that the ADAPTIVE plan detail has no steps, and now proven that the workout-service DOES return steps whenever a real `workoutId` exists.

**DECIDED (Will, 2026-07-19) — do NOT synthesize stages onto Garmin days.** Since Garmin's API gives no stages for adaptive coach days, generating WU/main/CD (LLM or template) would be **fabricating structure Garmin never specified** — in a coaching app that's worse than showing nothing (the athlete could run invented intervals thinking they're the plan). So: stages render ONLY when a day genuinely IS structured (`steps` present) — which today means **Idaten-authored/pushed** days. Garmin whole-run days show the real target + zone, honestly, and no invented steps. (Verified end-to-end that an Idaten-authored structured day renders the full timeline + step list.)

**What actually SHIPPED on `/plan/[date]`** (reframed away from the original steps-first spec, because the live data is whole-run HR targets, not structured steps):
- **Stat tiles** — Duration / Distance / Target (pace or HR) / Effort — client-derived from the whole-run fields. Works for every run.
- **Purpose explainer** — a sentence per `workout_type` (`WORKOUT_PURPOSE` in `lib/workout.ts`): the "what type of run" answer for a plain target.
- **HR zone bar** (`components/hr-zone-bar.tsx`) — locates the whole-run HR target on the athlete's Z1–Z5 scale (bands proportional to bpm, target highlighted, primary zone named). This is the real "what kind of run" signal for HR-targeted coach days. Needs the athlete's zones, so the endpoint returns `hr_zones` (from `settings_store.hr_zones`).
- **Structured section (only when `steps` present)** — order: **Steps** (`WorkoutSteps`, redesigned: color-accented rows, duration/target pills, repeat sets grouped in a card with an `N×` badge + set total) → **Effort profile** (`WorkoutTimeline`, proportional kind-colored bar + work/recovery/warmup/cooldown time totals) → **HR zone bar**.
- **Time-in-zone (Z1–Z5) DEFERRED** — bucketing needs server-side zone boundaries; not faked client-side. The work/recovery/warmup/cooldown breakdown ships instead. A true zone breakdown, if built, is server-computed.
- Consolidated actions: `PushButton`, `RevertButton` (when `revertible`), `OtherSportButton`, "Ask about this workout" → chat. Graceful loading / error / rest / "nothing planned" states.
- Per-day source is shown by `PlanSourceChip` only (⌚ Garmin Coach vs Coach {persona}); the account-level `CoachModeBadge` ("Following Garmin Coach") is NOT repeated on the single-day page — it was contradictory next to a "Coach Koa" day. The mode badge stays on the Week/Today headers.

**Client math (`workoutBreakdown` in `lib/workout.ts`):** per-step time = `duration_min` if set; else `distance_km` × pace (step pace, else workout pace); else distance-only at a nominal pace (flagged approximate); else equal-weight. Repeats expanded before summing. Returns `{ totalMin, workMin, recoveryMin, warmupMin, cooldownMin, segments[] }`.

**Card wiring.** Today card title/meta links to `/plan/[date]`. Week rows are FULLY clickable via a stretched-link overlay (`absolute inset-0 z-10`), with the action bar, coach-note "More" toggle, and intent chip raised to `z-20` so they stay interactive while the rest of the card navigates. Rest days are not linked. Week header actions moved to a dedicated left-aligned toolbar (were staggering in the right-aligned header slot); per-card actions are a bottom action bar (order: Send to watch → Replace with Garmin Coach → Other sport).

**New surface:** `app/plan/[date]/page.tsx`, `components/workout-timeline.tsx`, `components/hr-zone-bar.tsx`, `workoutBreakdown`/`WORKOUT_PURPOSE`/`WORKOUT_EFFORT_LABEL`/`ZONE_LABELS`/`ZONE_COLORS`/`zoneForHr`/`primaryZoneForHr` in `lib/workout.ts`, `api.planDay(date)`. Backend `GET /api/plan/day` + `tests/test_plan_day_endpoint.py` (5). `WorkoutSteps` redesign flows through to the Today card too.

**Open follow-ups (NOT built):** an explicit opt-in "structure this run for me" action on a Garmin day (Idaten authors real steps the athlete CHOOSES — never passed off as Garmin's plan), which would also make the day pushable with fetchable steps; pushing Idaten's structured workouts to the watch; a server-computed time-in-zone breakdown; intensity-height on the timeline bar.

## DECIDED — Menstrual cycle tracking as a coach signal (BUILT + DEPLOYED 2026-07-18, incl. all fast-follows + Today card)

Design agreed with Will in conversation on 2026-07-18.
Source of truth for the build.

**BUILD LOG — DONE + DEPLOYED 2026-07-18 (full suite 196 green, tsc + next build clean, images rebuilt & live):**
- **Data model — settings key, NOT a new table.** Stored as a per-user `cycle` settings blob (`{enabled, last_start_date, cycle_length_days, period_length_days}`) in `settings_store.DEFAULTS` — reuses the existing JSON prefs store like `athlete`, so ZERO migration. `normalize_cycle()` coerces/rejects bad input (malformed anchor → None, out-of-range lengths → defaults, `enabled` must be a real bool); applied on both GET and PUT. The single-anchor-row model is enough for set-once projection; a `cycle_events` history table stays deferred.
- **`metrics.cycle_phase(cycle, date)`** — pure arithmetic forward/backward projection, no Garmin call, no cold start. Returns `{phase (menstrual|premenstrual|follicular|luteal), day_of_cycle (1-idx), cycle_length_days, period_length_days, days_to_next_period, next_period_date, ease_recommended}` or None when off/no-anchor. `ease_recommended` = the 2-3 days pre-start (premenstrual) or first 1-2 days of flow — the deterministic coaching flag.
- **Review integration** — `build_snapshot` carries `menstrual_cycle`; `REVIEW_SYSTEM_PROMPT` gained a gentle-ease bullet (soften a hard session / consider rest on a low-readiness early-flow day; mention warmly in coach_note; never churn a sound plan). Fed as a model bias, NOT a deterministic gate — consistent with the "suggest, don't churn" posture.
- **API** — `PlanDay` gains `cycle?: CyclePhase|null` on `/dashboard/today` (`workout`) and `/plan/week` (`days[]`); `/settings` gains the `cycle` object + read-only `cycle_status` (today's phase, one source of truth for the UI summary). Contract bumped to **v1.17** (v1.16 was already taken on disk by the RPE-all-activity batch).
- **UI** — `CyclePhaseChip` (rose "Menstrual · day N" / amber "Premenstrual") next to the workout badge on Today + Week, shown ONLY in the ease window so it stays meaningful. `CycleTrackingCard` in Settings (off-by-default toggle, optimistic-save like the persona pick, prediction summary + "Manage cycle →"). Dedicated `/settings/cycle` page: enable toggle + anchor inputs (last start date / cycle length / period length) + today's-phase preview. No standalone period calendar (would duplicate Flo/Clue and isn't our value). Phase-explicit-on-workout per Will's call.
- **Tests** — `test_cycle.py` (8: phase boundaries, ease flags, forward/backward projection, garbage-length fallback, normalize) + `test_cycle_api.py` (2: settings roundtrip + status, week payload carries phase / clears when off). Full suite 196 green.
- **Deploy** — backend force-recreated + frontend recreated on the new images; settings-key model = no migration; live smoke confirmed (`GET /api/settings` 401 unauth; in-container `get_settings(1)` returns the default cycle blob). `/settings/cycle` route built.
- **Deliberately NOT done — no live seeding of Julianne's real cycle.** Setting a real anchor is entering her personal health data on her behalf; per the sensitivity decision, confirm with Julianne first. HTTP wiring was E2E-verified via the TestClient against real endpoints instead, so no live-data mutation. STILL OPEN: eyeball the chip + Manage-cycle page in a logged-in browser through the tunnel (unit + HTTP covered, not yet visually verified); Julianne opts in and enters her own anchor.
- **Import stays DEAD for phase 1** — the 2026-07-18 spike (below) found both accounts hold zero Garmin cycle data. Manual anchor is the primary path; the API shape is known if she ever logs on the watch.

**FOLLOW-UPS — DONE + DEPLOYED 2026-07-18 (all three fast-follows + a Today indicator; suite 199 green, tsc + next build clean, images live):**
- **Today cycle indicator (Will's ask — "show it on Today if she's in her cycle")**: `CycleTodayCard` on Today, below readiness. Shows during the period ("Your period · day N"), the premenstrual lead-up ("Period expected in N days"), or the drift window; renders NOTHING on ordinary follicular/luteal days so it's not a permanent widget. Backend added top-level `cycle` to `/dashboard/today`.
- **Fast follow 1 — follicular green-light**: `REVIEW_SYSTEM_PROMPT` now also tells the coach to green-light a plan's quality session in the follicular phase when readiness is good (remove hesitation, don't invent hard work). Surfaced visually as an emerald "Follicular · strong" chip.
- **Fast follow 2 — non-nagging drift self-correction**: `cycle_phase` gained `in_drift_window` (tight band: 2 days before .. 1 day after the predicted start). In that window ONLY, `CycleTodayCard` offers a one-tap "did your period start today?" confirm → `POST /cycle/started` re-anchors `last_start_date` and gently blends `cycle_length_days` toward the observed gap (2:1, so one odd month doesn't whipsaw but a real drift is absorbed over a couple cycles). Dismissable ("Not yet"); never shown outside the window → not a monthly nag. `settings_store.reanchor_cycle()` is the shared helper.
- **Fast follow 3 — read-only month strip (UI C)**: `GET /cycle/calendar?months=N` (per-day phase from the 1st of this month) feeds `CycleMonthStrip` on the Manage-cycle page — a 3-month grid shading period (rose) and premenstrual (amber) days, today ringed. Read-only, refetches after a save. No tap-to-log.
- **Contract**: v1.17 section extended (new endpoints + `in_drift_window` + top-level Today `cycle`).
- **Tests**: +3 (drift-window band, re-anchor length learning + future-date reject, calendar shading). Suite 199 green. Live smoke: both new endpoints 401 unauth; in-container `cycle_phase` confirms day-1 menstrual+drift+ease, day-8 follicular, day-27 premenstrual+drift+ease.
- **STILL OPEN (unchanged)**: browser eyeball through the tunnel; Julianne opts in with her own anchor (no live seeding of her personal data).

**FIXES (Will's live feedback 2026-07-18, DEPLOYED):**
- **Drift prompt was nagging** — it reappeared after Yes/Another-day/Not-yet and on every refresh. Root cause: "Yes" re-anchors to day 1, which is STILL inside `in_drift_window`, and "Not yet" was client-only state lost on reload. Fix: server-owned confirm/snooze state (internal settings keys `cycle_confirmed_start` / `cycle_snooze_date`, NOT in the writable `cycle` blob so a settings PUT can't wipe them). New `metrics.show_started_prompt()` gates the prompt: only in-window AND not-confirmed-this-cycle AND not-snoozed-today. `/dashboard/today` `cycle` now carries `show_started_prompt` (+ `current_start_date`). `POST /cycle/started` marks confirmed + clears snooze; new `POST /cycle/snooze` records a "Not yet" for today only. Frontend uses the server flag (optimistic hide for snappiness). Verified: after confirm, day=1 & in_drift=True but prompt=False; snoozed → prompt=False; a new day re-shows only if unconfirmed. Test `test_drift_prompt_stops_after_confirm_and_snooze`.
- **Manage cycle now in the nav** — when tracking is on, a "Cycle" item (droplet) appears in the sidebar + mobile More (via `useCycleEnabled()` on `CoachProvider`), not buried in Settings. Suite 200 green.
Motivated by Julianne (user 2, the only woman on the app today): give the coach visibility into cycle phase so it eases intensity in the premenstrual and early-menstrual window.

### Why this belongs here (strategic fit)

This is a third deterministic signal feeding the SAME review pipeline we already built, alongside `readiness()` (acute state) and `structural_signals()` (hard-day spacing).
Cycle phase is exactly the multi-day, predictable pattern a greedy daily optimizer (Garmin's DSW) structurally cannot see: the premenstrual dip reads all-green on HRV/sleep/body-battery right up until it doesn't.
Same shape as the founding "three thresholds in one week" case — Idaten's global multi-day review layer is precisely where it belongs.
It reuses everything downstream: computed in `metrics.py`, handed to `evaluate_today`'s single `complete_structured` call as grounding, model proposes an ease-off via the existing `PendingEdit` / supersession / accept-dismiss machinery.
ZERO new plumbing downstream.

### Coaching behavior (Will's ask)

- **2-3 days before predicted period start** (late luteal / premenstrual window) → dial DOWN intensity.
- **First 1-2 days of flow** → easy or consider rest.
- Follicular-phase UPSIDE (often the strongest window → green-light harder efforts) is noted as a FAST FOLLOW, NOT phase 1.
- Model must SUGGEST, not churn — same "propose only on a clear reason" posture as the rest of editor mode; cite confidence when the cycle is irregular.

### Input model — set-once anchor + forward projection (DECIDED, Julianne's explicit preference)

Julianne finds Garmin's per-month re-logging annoying and her cycle is regular, so she wants to set it ONCE and have the app predict forward, with minor edits when it drifts.
This is the classic "calendar/rhythm method" model (also a mode inside Apple Health Cycle Tracking) — legitimate and common for regular cycles; the log-every-month nag in Flo/Clue exists to serve IRREGULAR cycles and buys little for a regular one.
Consequence: this is SIMPLER than a tap-each-day period calendar — deterministic forward projection, NO cold-start problem, works from day one.

Anchor inputs (set once, editable): **last period start date** + **cycle length** (default 28, editable) + **period length** (default 5, editable).
Everything else is DERIVED, never stored: predicted next start = last start + cycle length; phase for any date computed arithmetically.

**Drift caveat — load-bearing.** Open-loop projection drifts a few days even for regular cycles.
Our easing window is only 2-3 days wide, so a 3-day-off prediction makes the feature misfire.
Mitigation, OPTIONAL and NON-nagging (the opposite of what annoyed her): a small dismissable "Period started today?" confirmation shown ONLY on the ~2 days around a predicted start; one tap re-anchors and self-corrects.
If the Garmin import spike (step 0) works, silently re-anchor from any real logged start instead.

### Data model

```
class MenstrualCycle(Base):   # or a single anchor row per user — see note
    user_id (PK)
    last_start_date: date      # the anchor
    cycle_length_days: int     # default 28
    period_length_days: int    # default 5
    source: "garmin" | "manual"
    updated_at
```

Simplest viable: ONE anchor row per user (not a table of logged cycles), since the model is set-once projection.
If we later want logged history / self-correction averaging, add a `cycle_events` table of actual start dates and compute median length from it — deferred, not phase 1.
Gate the whole feature behind an opt-in Setting (`cycle_tracking` = on/off, default off) — NOT a gender flag; the toggle is the gate.

### `metrics.py` — `cycle_phase(anchor, date)`

Pure arithmetic, no Garmin call, no DB dependency beyond the anchor row.
Returns e.g. `{phase: "menstrual" | "follicular" | "late_luteal" | ..., days_to_next_period: int, day_of_cycle: int, confidence: "high" | "low"}`.
`confidence` is `low` until/unless we have variance data (phase 1 with a single anchor → treat as high given her stated regularity; wire real variance only when a `cycle_events` history exists).
Feed the phase dict into `evaluate_today` grounding alongside `readiness()` and `structural_signals()`; extend `REVIEW_SYSTEM_PROMPT` to reason from it (ease 2-3 days pre-start and days 1-2 of flow; cite the phase; suggest don't churn).

### UI (DECIDED)

**A — phase explicit ON the workout (Today + Week).** Will chose EXPLICIT labeling, not quiet.
A thin phase tag/band on affected days, e.g. `Tempo → Easy  ● premenstrual — kept light`, so the athlete sees WHY the day changed next to the workout the coach eased.
Reuse the existing row/`CoachNote` surfaces; no new screen for this.

**B — Settings card + dedicated "Manage cycle" page.** Front door in Settings, the room is its own page (matches Apple Health: reached THROUGH settings, not a top-level nav item — a gendered top-level menu is the wrong altitude and outs the feature).
Settings gets ONE "Cycle tracking" card: an off-by-default toggle; when on, an inline summary line (`Next period ~Jul 24 · day 13`) + a `Manage cycle →` link.
The Manage-cycle page holds the anchor inputs, the optional "started early/late?" correction, and (later) the read-only month strip.
Do NOT inline the anchor fields loose in the Settings list, and do NOT build a standalone period calendar as a primary surface — that duplicates Flo/Clue and isn't our value.

**C — read-only month strip (DEFERRED).** A minimal 1-3 month mini-calendar with predicted periods shaded, purely to eyeball the projection; lives inside the Manage-cycle page. Build only if she asks.

### Step 0 — Garmin import spike (do FIRST, read-only)

Same pattern as the RPE/feel import: don't ask when Garmin already has it.
`garminconnect` exposes `get_menstrual_data_for_date(cdate)` and `get_menstrual_calendar_data(start, end)`.
Run READ-ONLY in-container against both live accounts to see whether Julianne's cycle data is already reachable; if it is, sync becomes the primary path and manual anchor input is the fallback (and gives us free self-correction for the drift caveat).
This spike decides how much input UI we actually build — run before B.

**SPIKE RESULT (2026-07-18, ran read-only in-container against both live accounts).** Both endpoints WORK and return well-formed payloads, but BOTH accounts hold ZERO cycle data across ~180 days.
`get_menstrual_calendar_data(start, end)` caps at a **92-day** window (400 "Exceeded max date difference" beyond that — query in ≤90-day chunks) and returns `{cycleSummaries: [], loggedSymptomDays: [], loggedOvulationDays: [], loggedNoteDays: []}` — all empty for both users over two stacked 90-day windows.
`get_menstrual_data_for_date(date)` returns `{}` for every probed date (today, −7, −14, −28) for both.
Conclusion: **Julianne is not logging her cycle in Garmin → nothing to import today.** Manual anchor input is the **PRIMARY** path, not a fallback; the drift self-correction cannot lean on Garmin either.
The API shape is now known (`cycleSummaries[]` is where logged cycle starts would appear), so IF she ever starts logging on the watch we can wire sync later — but do NOT build import for phase 1. Proceed straight to the manual anchor model + `cycle_phase()` + UI A/B.

### Sensitivity

Intimate health data: strictly opt-in, per-user, kept out of any shared/aggregate view.
Coach notes word it with care ("let's keep today easy") rather than clinically naming the phase every time — even though the workout TAG names the phase, the prose note need not.
Given exactly one real user is affected, confirm surfacing preferences with Julianne directly.

### Contract

New/extended: a `cycle` object on the Settings payload (anchor fields + toggle) with GET/PUT; the phase dict surfaced on the Today/Week/dashboard payload for the workout tag; opt-in Setting `cycle_tracking`.
Bump API_CONTRACT.md to **v1.16**.

### Sequencing (recommended)

1. Step 0 Garmin spike (cheap, could shrink the input UI).
2. `MenstrualCycle` anchor model + `cycle_phase()` in `metrics.py` + feed into `evaluate_today` (the actual coaching value; reuses everything).
3. UI A (phase-on-workout) + UI B (Settings card + Manage-cycle page).
4. Fast follows: follicular green-light; optional drift self-correction; UI C month strip.


## DECIDED — Garmin RPE/feel/body-battery import + coach-mode label + revert-to-Garmin (BUILT 2026-07-18, NOT yet deployed)

Design agreed with Will in conversation on 2026-07-18.
Three independent features; source of truth for the build. Feasibility was verified live against Will's real Garmin account (fields confirmed present on his latest run) and traced through the data model — see per-feature notes.

**BUILD LOG — DONE 2026-07-18 (built + full suite 184 green + tsc/next build clean; NOT yet deployed, no live E2E yet):**
- **Feature 1**: `Activity` gained `garmin_rpe`/`feel`/`body_battery_change` (additive → auto-migrates via `_auto_migrate`). `sync_activities` captures `differenceBodyBattery` free from the summary; `enrich_activity` adds one `get_activity()` call for RPE/feel (`get_activity_details` confirmed to LACK `summaryDTO`, so the extra call is required) via `_rpe_feel()` (RPE÷10, feel = round(v/25)+1). Today gate (`api.py`) treats a Garmin-logged RPE as rated → no in-app prompt. New fields flow into `_activity_dict` + the two LLM DTOs (`planner.py`, `chat/tools.py`, RPE falls back to garmin_rpe). Backfill: `enrich.backfill_rpe_feel_bb(db, uid, garmin, days=30)` — RUN THIS in-container per user after deploy (BB from stored raw, RPE/feel one call each; ~30 calls/user).
- **Feature 2**: `mode` added to `/dashboard/today` + `/plan/week`. `components/coach-mode-badge.tsx` (hover/tap tooltip modeled on `MetricInfo`) on both headers. Labels: editor "Following Garmin Coach" / author "Following {persona.name}".
- **Feature 3**: `planner.revert_to_garmin(db, uid, dates, today)` (force-overwrites overrides, preserves intent/completed days, clears Idaten's push via `push.unpush_day`, no re-push) + `edited_days_in_window()`. Refactored materialize's day-build into shared `_coach_day_fields`/`_write_coach_day`. `POST /dashboard/revert-to-garmin {scope, date?, start?}` (400 in author mode). `revertible` flag on today/week PlanDay payloads. `components/revert-button.tsx` per-day on Today + Week; week-level "Replace with Garmin Coach plan" button + confirm dialog on the Week header.
- **Tests**: `test_rpe_feel_import.py` (4), `test_revert_to_garmin.py` (7), `test_revert_endpoint.py` (6). Contract bumped to **v1.15**.
- **Still open**: deploy (backend needs rebuild for the new columns/migration; run the 30-day backfill in-container per user); live browser E2E of the mode badge tooltip + revert buttons through the tunnel; confirm Will's real runs actually carry `directWorkoutRpe`/`directWorkoutFeel` (they will only be populated on runs where he logged them in the Garmin app).

### Feature 1 — Import RPE, feel, and body-battery change from Garmin; stop asking for RPE in-app when Garmin already has it

**Feasibility — CONFIRMED live (2026-07-18).** Queried Will's latest run through `get_activity(id)`. All three fields present:
- **Body-battery change** = `differenceBodyBattery` (e.g. `-5`) — **already in the summary payload** we store in `Activity.raw` (from `get_activities_by_date`). NO extra Garmin call needed for this one.
- **RPE (effort we gave)** = `summaryDTO.directWorkoutRpe` (e.g. `30`) — Garmin stores **RPE ×10**, so divide by 10 → 3/10.
- **Feel (how we felt)** = `summaryDTO.directWorkoutFeel` (e.g. `50`) — enum **0/25/50/75/100 = Very Weak / Weak / Normal / Strong / Very Strong** (50 = Normal). Map to a 1-5 or label on ingest.

**Storage — separate columns, keep provenance (DECIDED).** Do NOT overwrite the existing app-set `Activity.rpe`/`rpe_note` (set via `POST /activities/{id}/rpe`, `api.py:732`). Add new columns: `garmin_rpe` (int 1-10), `feel` (int 1-5 or label), `body_battery_change` (float). Provenance stays clear (human-in-app vs watch). Prefer Garmin's value when present.

**Behavior — Today page stops asking when Garmin already logged it (DECIDED, Will's explicit ask).** The Today "unrated" gate is `api.py:320`: `unrated = latest_run if latest_run.rpe is None else None`. Change the condition so a run with a Garmin RPE (`garmin_rpe is not None`) is ALSO treated as rated → the `<RpeCard>` on Today does not appear. Only prompt when BOTH `rpe` (app) and `garmin_rpe` are absent. (Manual re-rating from the activity detail page stays available.)

**Where to ingest.** `enrich.py:107 enrich_activity` already makes per-activity calls (`get_activity_details`, splits) — add the RPE/feel read there. CHEAP-CHECK FIRST: see whether the `get_activity_details` payload we already fetch carries `summaryDTO` (if so, zero extra calls; otherwise one `get_activity(id)` per activity). `differenceBodyBattery` needs no call — read it from `Activity.raw` (or capture it in `sync_activities`, `sync.py:31`, alongside the other summary fields).

**Backfill — 30 days only (DECIDED).** One pass over the last ~30 days of activities per user (~30 calls/user, trivial). No 300-day backfill.

**Caveat to honor in UX.** Fields are populated ONLY if the athlete logged RPE/feel in the Garmin app; unlogged runs return `null`. So the in-app RPE prompt must not vanish globally — it hides per-run only when a Garmin value exists.

### Feature 2 — Show which coach mode is active (with a hover tooltip)

**Feasibility — CHEAP, mostly frontend.** The mode already exists server-side (`plan_mode()` in `planner.py`; persisted on `DailyReview.mode`; already returned by the review endpoint, `api.py:340`). Today + Week just render it next to the existing `Base · Week 8 of 25` chip.

**Labels (DECIDED, Will picked these).**
- Editor mode (Garmin Coach plan active) → **"Following Garmin Coach"**.
- Author mode (Idaten writes the plan) → **"Following {persona.name}"** = "Following Coach Sam / Koa / Viktoria" (from `useCoach()` → `persona.name`, already available in the frontend; personas map default→Sam, chill→Koa, strict→Viktoria).

**Tooltip on hover (DECIDED, Will's ask).** Explain the difference in one or two lines and point to where to change it (Settings → "Plan source"). E.g. editor: "Garmin Coach writes your plan; {persona} reviews it and suggests tweaks. Change under Settings → Plan source." Author: "{persona} writes your whole plan. Change under Settings → Plan source." Note: editor mode is NOT pure Garmin — Idaten still layers edits — so the tooltip should say "reviews and tweaks," not imply Idaten is absent.

### Feature 3 — "Replace with Original Garmin Coach Plan / Workout" (revert an Idaten edit)

**Feasibility — CLEAN, the original is never lost.** `TrainingPlan.upcoming_tasks` mirrors Garmin's coach `taskList` read-only on every sync within a **±14-day window** (`TASK_WINDOW_DAYS = 14`, `training_plan.py:37`) — always covers Today and the 7-day Week. An Idaten edit only overwrote the materialized copy in `plan_days` (`source="chat_edit"`); the Garmin original still sits in `upcoming_tasks`.

**Implementation.** Reuse `materialize_coach_plan()` (`planner.py:680`), which already turns a Garmin task into a `PlanDay`. It currently SKIPS overridden days (`_is_override`, `planner.py:672`); add an explicit `force`/revert path that re-stamps the day back to `source="garmin_mirror"`, clears the Idaten `rationale`, and re-materializes that day (or week) from `upcoming_tasks`.

**Watch sync on revert (DECIDED, Will).** Just CLEAR Idaten's pushed workout for that day and let the native Garmin Coach workout stand (it already lives on the watch). Do NOT re-push a Garmin copy.

**Scope (DECIDED, Will agreed).** Both: a per-day "Replace with Garmin Coach" button (surgical) AND a top-level week-level "Replace with Original Garmin Coach plan" (resets the whole visible week).

**Visibility rules.** Show ONLY in editor mode, and per-day only on days that actually differ from Garmin (`source ∈ {chat_edit, manual}`). Hide on untouched Garmin days and entirely for author-mode users (no Garmin base to revert to). Days outside the ±14-day window have no mirror — not shown in Today/Week anyway, so not a concern.

**Contract.** Will need a new/extended endpoint (e.g. `POST /dashboard/revert-to-garmin {date | week}`), the `mode` surfaced on the dashboard/Today payload, and the three new Activity fields in the activity DTO. Bump API_CONTRACT.md.

## DECIDED — Idaten as editor above the DSW (resolves mirror-as-base-plan; NOT YET BUILT)

Design agreed with Will in conversation on 2026-07-17.
This resolves the open "mirror-as-base-plan" decision (see Grounding & phases batch below) and folds three requested features into one morning routine.
This section is the source of truth for the build.

**BUILD LOG**
- **Phase A — DONE (2026-07-17, not yet deployed)** — foundation, no behavior/UX change. New `DailyReview` table (`daily_reviews`, PK `(user_id, date)`: `state` ∈ `pending_data|done_full|done_structural`, `mode`, `coach_note`, `proposal_id`→`pending_edits`, timestamps) — this RESOLVES the "where does coach_note live" open item: its own per-day table, NOT `PlanVersion` (a review often changes nothing yet still owes a note) and NOT `PlanDay` (needs the eval state machine). `plan_authoring` setting (`auto|author`, default `auto`) with validation. `has_active_plan()` in `garmin/training_plan.py` + `plan_mode()` in `planner.py` (editor when a Garmin plan is active on the day, unless override → author; no plan → author). 11 new tests in `test_evaluate_foundation.py`; full suite 145 green; migration rehearsed on a consistent backup-API snapshot of the live DB (new table created, all real rows intact). The readiness/strain signal needed no new code — `metrics.readiness()` already computes the HRV-vs-baseline + sleep + body-battery + TSB blend.
- **Phase B — DONE (2026-07-17, not yet wired/deployed)** — the review brain, built + tested but deliberately NOT wired into the scheduler yet (generate_plan still runs nightly, so the app keeps working at every deploy). `evaluate_today(db, user_id, today, allow_structural_fallback=False)` in `planner.py`: computes `plan_mode`, gates on today's `DailyHealth` (absent + no fallback → `pending_data`, ZERO LLM calls), else one `complete_structured` call against `REVIEW_SCHEMA` → `{coach_note (always), should_propose, proposal}`; persists the `DailyReview` (`done_full`/`done_structural`) and, when proposing, creates a superseding `PendingEdit` and links `proposal_id`. `metrics.structural_signals()` (max_consecutive_hard_days / min_gap_between_hard_days / hard_day_count over an ordered day list) + `training_plan.task_is_hard()` (coach TE-label → hard/rest) are the deterministic multi-day facts the model reasons from — the founding "3 threshold in a row" case is unit-tested. `create_pending_edit()` extracted into `planner.py` as the ONE proposal path (pace guard + supersession), now shared by the chat tool (`chat/tools.py` refactored to call it — `test_tools` still green) and the review. Editor prompt: Garmin plan is authoritative base, propose only on a clear reason, most days `should_propose=false`. 12 new tests in `test_daily_review.py`; full suite 155 green.
**Materialization vs accepted-diff (DECIDED 2026-07-17, Will agreed):** editor mode copies Garmin's coach `taskList` into `plan_days` as the base (so Today/Week/push/proposal machinery all read one table), and this copy re-runs daily. The collision — a daily re-copy would silently revert a diff the athlete already accepted — is resolved by TAGGING ORIGIN via the existing `PlanVersion.source`: materialization writes days under `source="garmin_mirror"`; accepted edits already write `source="chat_edit"` (and hand-edits `"manual"`). Rule: materialization overwrites a day ONLY if it's still base/auto-authored (`source ∈ {garmin_mirror, daily_job, onboarding}` or legacy null) and `status="planned"`; it NEVER overwrites a user override (`chat_edit`/`manual`) or a completed/skipped day. Edge case deferred: if Garmin itself materially moves a task the athlete had overridden, clear the stale override (detect + drop) — not built yet.

- **Phase C base — DONE (2026-07-17, not yet wired/deployed)** — `materialize_coach_plan()` in `planner.py`: copies the mirrored coach `taskList` into `plan_days` as the editor base, override-safe per the decision above (`_is_override` reads `PlanVersion.source`; `_OVERWRITABLE_SOURCES = {garmin_mirror, daily_job, onboarding}`). Deterministic TE-label→workout_type map (`LACTATE_THRESHOLD→tempo`, `VO2MAX/SPEED→intervals`, `AEROBIC_BASE→easy_run`, name "Long"→long_run, rest_day→rest) + `_parse_hr` pulls the single bpm from '…@172bpm'; base days carry empty rationale by design. 6 tests in `test_materialize.py` (fresh copy, idempotent, override preserved, completed-day skipped, legacy-authored overwritten, no-plan→[]); full suite 161 green.
- **Phase C wiring (backend) — DONE (2026-07-17, NOT deployed — behavior-changing, needs live E2E before deploy)**: `scheduler._job_for_user` no longer calls the LLM — it does `run_sync` then, for editor users only, `materialize_coach_plan` + auto-push (author users just sync; their week is written lazily). `evaluate_today` gained the author branch (delegates to `generate_plan`, one LLM call, auto-applies + pushes, `coach_note` from the plan's adjustment summary; `daily_review` added to `_OVERWRITABLE_SOURCES`). Two lazy endpoints in `api.py`: `GET /dashboard/review` (cheap, no-LLM: `{review, data_ready}` for polling) and `POST /dashboard/evaluate {allow_structural}` (idempotent per day via `DailyReview.state` — a completed review returns cached with NO new call; `pending_data` when data absent spends nothing; `allow_structural=true` is the degraded button). 8 wiring tests in `test_review_wiring.py` (+ updated the now-stale `generate_plan` patch in `test_phase56` and the author-mode test in `test_daily_review`); full suite 166 green.
  - Deferred to the frontend pass: progressive SSE streaming of the coach_note (current endpoint is synchronous — Today shows a spinner; SSE via a route handler, NOT a rewrites proxy — [[next-rewrites-sse-buffering]]); true concurrency dedup across simultaneous first-loads (state check covers the common case; worst case is one duplicate LLM call, harmless).
  - Behavior note (not a regression, but changed): onboarding (`daily_job(source="onboarding")`) now only authors a first plan for EDITOR users (materialize); a brand-new AUTHOR user gets their first plan on first Today load instead of during the onboarding minute — the "first plan in ~a minute" banner copy should be revisited for author users.
  - **DO NOT DEPLOY the scheduler change alone**: without the frontend calling `/dashboard/evaluate`, editor users would get a materialized base but never a review. Deploy Phases C+D together after live E2E.
- **Phase D — DONE (2026-07-17, built + tsc/build clean, NOT deployed — needs live browser E2E)**: shared `components/coach-note.tsx` (`CoachNote`: avatar + name + message, `collapsible` variant) extracted from `TodayWorkoutCard` and reused there + on the Week rows (replacing the `Lightbulb`) + the daily note. `components/daily-coach-note.tsx` (`DailyCoachNote`) on Today: polls `GET /dashboard/review`, fires `POST /dashboard/evaluate` once data is ready, progressive-renders the coach_note; three states (waiting-for-data honest line → degraded "Review with recent training instead" button after 25s, evaluating shimmer, done); a surfaced proposal calls `load()` so the existing `EditProposalCard` shows. Deliberately a plain JSON POST, NOT SSE — sidesteps the tunnel/gzip-buffering trap; the note appears when the POST resolves (base plan already painted, so it reads as liveness). `api.dashboardReview()`/`dashboardEvaluate()`, `DailyReview`/`DashboardReview` types, `plan_authoring` added to `Settings`. Contract bumped to **v1.14**. Deferred: a Settings UI control for `plan_authoring` (defaults to `auto`, works without it); revisit onboarding "first plan in a minute" copy for author users.
- **DEPLOYED (2026-07-17)**: backend + frontend images rebuilt and live; migration ran clean on the production DB (`daily_reviews` created, existing rows intact); new endpoints wired (401 unauth); tunnel untouched. Julianne (user 2) materialized to the Garmin coach base live via in-container `materialize_coach_plan` — 5 `onboarding` days flipped to `garmin_mirror` (Sun Long/Mon-Tue Base/Wed Rest/Thu Sprint), her two `chat_edit` days (Fri easy, Sat freediving) preserved. NB those 5 changed days are not yet pushed to her watch.
- **Intent-guard fix (field question from Will, real gap)**: `materialize_coach_plan` did NOT honor `day_intents` — a committed other-sport day sitting on an overwritable base would have gotten a Garmin run stamped over it. Ported the `apply_plan_days` guard: an intent day is coerced to `cross_train` (titled by sport), never a run. Test `test_materialize_honors_day_intent_over_garmin_run`; suite 167 green; backend redeployed. (The freediving days in live data were already safe — they were `chat_edit`/`phase6_e2e` overrides — but the guard closes the general hole.)
- **Encouragement (feature 3) — ALREADY DELIVERED, not a separate build**: the `coach_note` IS the daily encouragement, grounded + persona-voiced, verified live (Will's real review cited HRV-vs-baseline, recent paces, days-to-race, and his freediving intent). `REVIEW_SYSTEM_PROMPT` already asks for grounded "you're on track" notes citing VO2max/race-predictor direction.
- **Phase E — DONE (2026-07-17, evals built, opt-in)**: 4 new review evals in `test_evals.py` (real-LLM, `-m eval`, collect-clean): `test_review_catches_three_hard_days_clustered` (founding case — proposal OR note flags it; deterministic `structural_signals` assert too), `test_review_eases_hard_day_on_suppressed_readiness` (low-HRV/poor-sleep → proposal easing today), `test_review_leaves_a_sound_plan_alone` (anti-churn: no proposal on a sound green week + grounded no-fabrication note), `test_author_mode_writes_a_week_with_a_note`. Not yet RUN against the key (Will's call — ~8 real calls). Run: `ANTHROPIC_API_KEY=sk-... .venv/bin/python -m pytest tests/test_evals.py -m eval -v`.
- **Evals RUN (2026-07-17) — 4/4 pass** against the live model (provider is **OpenAI**, not Anthropic — the `requires_real_key` gate still checks `ANTHROPIC_API_KEY` but `make_client` uses the configured provider, so pass BOTH `ANTHROPIC_API_KEY` (gate) and `OPENAI_API_KEY`/`OPENAI_MODEL`/`LLM_PROVIDER` (calls) to run: extract from the container env — the runtime image has no pytest/tests). One eval was redesigned: `test_review_leaves_a_sound_plan_alone` originally asserted "no fabricated metrics" via LLM-judge, which is UNRELIABLE (the judge fails any number-dense note, even fully-correct ones — its own prompt says "fail when in doubt"); the coach_note under test was verifiably correct. Now it hard-asserts anti-churn (`proposal_id is None`, deterministic) + judges only tone/relevance; coach_note grounding is enforced by the prompt + the deterministic pace guard on proposals, not by a judge.
- **plan_authoring Settings toggle + onboarding copy — DONE + DEPLOYED**: "Plan source" select in the Your-coach card (auto = follow Garmin Coach / author = Idaten writes it); onboarding copy in `app/page.tsx` + `connect-garmin-card.tsx` no longer promises "first plan in a minute" (now "your plan is ready the next time you open Today" — accurate for author users whose plan is authored lazily). Frontend rebuilt + redeployed (tsc + build clean).
- **Julianne watch push REVERTED per Will (2026-07-17)**: I materialized her plan to the Garmin base (persists) and pushed the 4 pushable days to her watch, then Will asked to undo the push so she chooses from the UI herself — unpushed 7/19–7/23; her watch is back to just today's pre-existing easy run. Her `plan_days` still hold the Garmin base; she'll push what she wants from the Week page.
- **Still open**: live E2E of the Today review UI in a logged-in browser (unit+eval-covered, not yet eyeballed through the tunnel).

**Core reframe — one plan, and Idaten is demoted from author to editor.**
Two plan authors (Idaten's `generate_plan` and Garmin Coach, mirrored in `training_plans`) compete today; that is the root problem.
Decision: when a Garmin Coach plan is present, Garmin is the base plan and Idaten never authors a competing week — it only produces a *diff* against Garmin's plan when the evidence warrants, using the existing `PendingEdit` proposal + supersession + accept/dismiss machinery.

**Division of labor — Idaten sits ABOVE Garmin's DSW, it does not re-do it.**
Garmin's Daily Suggested Workout already does acute daily adaptation (ease off after poor sleep) and does it well — re-building that adds no value and would not make the app smarter than the watch.
Garmin's DSW is a greedy, *local* optimizer: it picks a good *next* workout but has no view of multi-day structure.
Idaten's value is the global, multi-day review a greedy optimizer structurally cannot do: hard/easy spacing, threshold density, phase-appropriate progression.
This is the founding use case — Julianne's watch prescribed three threshold sessions in one week; that is a structural error no acute-readiness check catches, and it is exactly what Idaten's review layer is for.

**No deterministic gate — run the model every day.**
Cost is a non-reason at this scale (2 users × 1 call/day ≈ 60 calls/month, cents).
A gate that only invokes the model when an acute-readiness threshold (sleep/HRV/load) trips is by construction blind to structural errors — the three-threshold week reads all-green on those metrics — so gating would defeat the product's whole purpose and would also silence the daily coach note on calm, on-track days (feature 3).
Determinism keeps a role, but as *grounding and validation*, never as an on/off switch for intelligence: compute ACWR, hard-day spacing, threshold-count-this-week, phase load as signals fed to the model, and validate its output the way `pace_violations` already does.

**Base plan = the structured coach taskList; the live same-day DSW is NOT mirrorable (checked 2026-07-17).**
Traced sync → `training_plan.py` → the `garminconnect` library: we mirror `get_adaptive_training_plan_by_id`'s `taskList` (the periodized `fbt-adaptive` plan; adapts at plan level via `adaptiveCoachingWorkoutStatus`, not same-day for sleep).
The watch's readiness-driven same-day workout swap ("slept poorly → ease off") is computed on-device and is **not exposed by any library endpoint** — there is no today's-suggested-workout object to pull, so the original "re-pull the live DSW" plan is impossible.
Consequence (cleaner, not worse): Idaten anchors on the structured taskList as base and consumes the same *input* Garmin uses rather than mirroring its opaque output — apply our own structural + readiness logic on top.
SPIKE RESULT (Step 0, 2026-07-17 — ran read-only in-container against both live accounts): `get_morning_training_readiness` returns `None` and raw `get_training_readiness` returns `[]` for BOTH Will and Julianne — their devices/firmware do not populate Garmin's Training Readiness at all, so the originally-planned "add the readiness pull" is DEAD (nothing to fetch).
REVISED — compute our own acute signal from data we already sync: `daily_health` already holds `sleep_score`, `sleep_seconds`, `hrv`, `hrv_baseline`, `resting_hr`, `body_battery`, `stress_avg`, `vo2max`, `race_predictions`, populated daily for both users (verified same-day: Julianne 2026-07-17 hrv=36 vs her ~48-60 baseline — a real recovery-down flag landing on a Threshold day). So Idaten computes a deterministic readiness/strain score in `metrics.py` from HRV-vs-`hrv_baseline` + sleep_score + RHR trend + stress + body_battery — NO new Garmin call, no device dependency, works today. This is strictly better than mirroring Garmin's (unavailable) composite.
Both live users are EDITOR mode (both on the same "2026 SUPERACE 半程馬拉松" adaptive coach plan; neither is DSW-only). Author mode still ships for generality but will NOT be exercised by either live user → cover author mode with a seeded eval, not live testing.
Coach tasks are HR-target ('172bpm','154bpm','145bpm','196bpm'), matching training_mode — `coach_note` grounding and editor-mode diffs must speak HR, and the `pace_violations` guard needs an HR-sanity analog (or lean on existing `hr_zones`) since coach workouts aren't pace-based.
Rest days arrive as blank tasks (`name=''`, `training_effect='INVALID'`, `duration=None`, `rest_day=True`) — `evaluate_today` and the base-plan render must read `rest_day=True` as "rest", never as missing/unknown data.
Reality check on value: the current week is actually well-formed for both (Julianne: Threshold/rest/Long/Base/Base/rest/Sprint; Will: mostly Base + one VO2max) — Garmin's adaptive plan is reasonable here, so structural review will correctly say "looks good" most days. The everyday value right now is the ACUTE flag (hard session prescribed on a low-HRV/poor-sleep day, e.g. Julianne's hrv=36 Threshold today) + encouragement; the "3 hard days clustered" structural catch is the tail-case guard, not the daily driver. Be honest about this in copy and expectations.
Note: users with no structured coach plan (DSW-only) mirror nothing → fall to derived-from-race; author mode covers them.

**Author vs editor is a mode — auto-detected, with override.**
Garmin Coach plan present (`training_plans` populated) → default **editor** (review + diff).
No Garmin plan → default **author** (Idaten writes the week, as `generate_plan` does today) so one code path stays meaningful for users without a Garmin Coach plan.
Power-user override: "let Idaten author even though I have a Garmin plan."

**`generate_plan` → `evaluate_today` (the review routine, one call, two payloads).**
Inputs: today's structured coach `taskList` workout (base; `rest_day=True` means rest, not missing), a deterministic internal readiness/strain score (HRV-vs-`hrv_baseline` + sleep_score + RHR + stress + body_battery — Garmin's own readiness is unavailable on these devices, see spike result below), 3-7 day load/ACWR, VO2max/race_predictions, Garmin phase/week (ground truth), and the structural signals above.
Outputs: (a) an always-present persona-voiced `coach_note` grounded in real metric deltas (VO2max/Riegel/HRV direction vs race goal); (b) optionally a single-day *or* structural proposal via `PendingEdit` when the plan should change.

**Timing — lazy first-login LLM, scheduled data, progressive render (decided 2026-07-17).**
The LLM call is the only thing that costs tokens, so split the layers: keep the Garmin *data* sync on its schedule + 30-min `catch_up` (no LLM, no tokens, keeps sleep/readiness fresh), and make only `evaluate_today` (the LLM call) lazy — it runs on first authenticated Today load of the day, deduped by a per-user per-day state field. No fixed `plan_hour` LLM cron; drop `generate_plan` from the nightly job.
Cost = exactly one LLM call per *active-user-day*, zero on days the app isn't opened.
Progressive render kills the login-latency worry: because the base plan is Garmin's mirrored `taskList`, Today paints the real plan instantly with no LLM; the coach note + any proposal stream into the `<CoachNote>` slot via the existing chat SSE infra a moment later (reads as liveness, not lag).
LLM only ever runs while a live client is on Today — no background token spend, ever.
Principle: **automatic when confident, ask when degrading, silence is acceptable.** Per-day state is one of three, never more than one LLM call:
- `pending_data`: today's readiness/sleep not yet synced → NO LLM call. Show base plan + honest "Getting last night's sleep & recovery from Garmin…" (not "reviewing" — that's a lie while we're only waiting). Page polls the cheap no-LLM readiness check while `catch_up` pulls in the background.
- `done_full`: data present (on load, or it lands during a short ~20-30s poll window) → auto-run full eval, stream it, show "Coach is reviewing today…" only once the call is actually in flight.
- `done_structural`: data still absent after the poll window → swap the shimmer for an explicit button "Last night's sleep hasn't synced from Garmin yet · [Review with recent training instead]"; on click, one structural-only call runs, flagged honestly ("based on your recent training, not last night's data"). No wall-clock auto-cutoff (that would imply a background fire and break the no-background-spend guarantee); if the user leaves without clicking, nothing fires and Today just shows Garmin's base plan (a day with no coach note is fine).
Dedup: the per-day state + the existing `rate_limit` stream lock so multiple tabs/devices don't double-fire; the good paths (`done_full`) are automatic, only the degraded path asks — matching the honest-shortcut principle (user presses the button).

**Schema — split `rationale` from `coach_note`.**
Today every `PlanDay` carries a `rationale` because Idaten authored every day, which is what made the Week page text-heavy.
Split into per-day `rationale` (set only on days Idaten diffed) and a single daily `coach_note` (the relationship/encouragement message, attached to the day-of or the `PlanVersion`).

**Frontend — one shared `<CoachNote>`, drop the lightbulb.**
Extract the coach-note block from `TodayWorkoutCard` (`workout-card.tsx:173-199`: `persona.headSrc` + name + text in a `bg-muted/50` box, persona from `useCoach()`) into a shared `<CoachNote>` and use it on the Week page in place of the `Lightbulb` + `day.rationale` line (`week/page.tsx:85-90`).
In editor mode most `DayRow`s carry no rationale (Garmin authored them, Idaten didn't touch them), so the week is clean by construction, not merely collapsed.
Make `<CoachNote>` collapsible (one-line summary → expand for physiology/jargon); this covers both editor mode (little text) and author mode (rationale on every day) without a separate global "nerd mode" config — defer that config until author-mode telemetry shows people always expanding.

**Tone** flows through the existing `style_prompt(settings)` seam (`planner.py:569`, default/chill/strict → Sam/Koa/Viktoria) so the daily note is voiced consistently with plans and chat.

**Deferred (not now):** proactive push notifications — lazy eval means the coach can't ping an absent user ("I adjusted today's plan"); acceptable for the current 2-user deployment. Re-add later as a scheduled pre-run of `evaluate_today` for *recently-active* users only, so it never computes plans nobody opens.

**Open sub-items to settle at build time:** exact structural signal thresholds and how they're echoed to the model; the poll-window length before the degraded button appears; whether structural proposals can span multiple days in one `PendingEdit` or stay single-day; encouragement-fatigue guard (vary register, let strict/chill modulate praise frequency). (RESOLVED: coach_note persistence → dedicated `daily_reviews` table, see Build Log Phase A.)

## Chat SSE proxy buffering + tool-round cap — DONE (2026-07-17, deployed) — long/tool replies now stream to the browser

- **Chat replies never appeared (field bug, root-caused E2E by comparing transport layers)**: model ran and billed, tool chips rendered, then the spinner hung forever on both localhost and the tunnel. Backend was innocent — hitting `POST /api/chat` directly on `:8000` streamed session/tool/text/done incrementally (text 1s after tools); the same request through the Next dev/prod server on `:3000` delivered the early tool events then **buffered the text deltas** until the upstream closed (~71s for a long reply), so nobody waited long enough to see it. Cause: Next's `rewrites()` proxy buffers streamed response bodies. `compress:false` (the earlier gzip fix) was intact and unrelated. Fix: dedicated App-Router route handler `frontend/app/api/chat/route.ts` (runtime nodejs, force-dynamic) that proxies only `POST /api/chat`, forwards the `gb_session` cookie, and returns `upstream.body` untouched with `text/event-stream` + `X-Accel-Buffering: no`; filesystem routes outrank the afterFiles rewrite so every other `/api/*` still uses next.config's proxy. Verified through `:3000`: text now lands 1s after the tool events.
- **Tool-round cap**: `MAX_TOOL_ROUNDS` 8 → 6 (a real turn uses ~3, ~5 with a pace-guard retry). Note: this only bounds runaway loops — normal turns already stop at `is_final`, so it does not cut per-turn cost.
- **Prompt caching (the real cost lever)**: `AnthropicClient._params` now marks the system prompt block with `cache_control: ephemeral`. The system prompt (~7.5k tokens: pace profile, Garmin plan, readiness, HR zones as JSON) is byte-identical across the 3+ model calls in a chat turn, and tools render before it so the tool schemas cache under the same prefix. Verified live on `claude-sonnet-5`: call 1 wrote 7515 cache tokens, an identical call 2 read all 7515 (`cache_read_input_tokens`) at ~10% cost. Cuts system-prompt input ~50% within a turn (write 1.25× once, read 0.1× thereafter) plus cross-turn hits inside the 5-min TTL. No console/account setting — caching is request-level. `complete_structured` (daily plan generation, `planner.py:560`) is deliberately NOT cached: it's a single structured call once/day per user, so a cache write (1.25×) has no second read to amortize — strictly net-negative in the common case. The only shared prefix is the pace-guard corrective retry (`planner.py:588`, reuses system+snapshot), but that only pays off if the retry fires >~28% of the time, which for grounded athletes it shouldn't. Cross-user sharing is negligible at 2 users. Revisit only if user count grows or the guard fires often in practice.

## Dismiss re-propose + Today phase chip — DONE (2026-07-17, deployed) — coach re-proposes after a dismiss; race/phase context on Today

135 pytest tests green (1 new in `test_phase7.py`), `tsc` clean; backend + frontend images rebuilt.

- **Dismissed proposals never came back (field bug, root-caused from real session data)**: after a user dismissed a proposal and asked for a new plan, the coach narrated a stale/fabricated card instead of issuing a fresh `propose_plan_edit`. Root cause was NOT in the backend tables (default status is `pending`, `_pending_edit` already filters to newest pending) — it was the model's context: `_load_history` replayed proposal markers as bare `[Proposed plan edit #N: ...]` text with NO status, so the model couldn't tell a dead (dismissed/superseded) proposal from a live one and assumed it already had one up. Fix: `_load_history` now stamps each marker with the edit's live status (`[status: DISMISSED ... re-propose if still wanted]` / `SUPERSEDED` / `ACCEPTED` / `PENDING`), and the system prompt gains an explicit rule that every plan change must go through `propose_plan_edit` and a proposal card must never be described/reprinted as prose. Verified against real session `84adc403` (edit #6 SUPERSEDED, #7 DISMISSED now correctly stamped). Model-decision confirmation (LLM call) still owed by a live UI retest.
- **Race + phase context on Today** (agreed with Will: keep the name "Today", compact the race cards rather than duplicate them): the `PhaseChip` ("Base · Week 8 of 25") now sits in the Today header title exactly as on the Week page, reusing the shared component and `usePlanInfo`; the existing race badge (name · days-to-race · predicted vs goal) stays below. Full Training-phases bar, Races list, and Race-outlook detail stay on the Races page — no card duplication, single source of truth.

## Grounding & phases batch — DONE (2026-07-17, deployed) — grounded paces, proposal supersession, real streaming, /replan button, Garmin Coach phases

Contract v1.13; 134 pytest tests green (14 new in `test_grounding_and_phases.py`), `tsc` clean.

- **Pace grounding (field incident: Julianne's first week prescribed 5:20-6:00/km vs actual 7:15-8:30/km)**: new `metrics.pace_profile` (90-day whole-run pace medians) feeds the planner snapshot and chat prompt; snapshot races now carry goal_pace + Riegel predicted_pace; deterministic `pace_violations` guard (easy days no more than 7% under typical pace, any day no more than 10% under fastest recent avg) — daily generation gets one corrective retry, chat proposals violating it are rejected before creation with the profile echoed back to the model.
  Her live bounds now: easy no faster than ~7:13/km, nothing faster than ~5:56/km.
- **Proposal supersession**: new proposals mark older pending edits `superseded` (new status); accept/dismiss on a non-pending edit is a 409 with a human sentence; live thread cards flip to "Superseded by a newer proposal" when the new proposal's SSE event arrives — nobody is ever forced to accept a stale plan first.
- **Streaming fix (root cause found E2E)**: backend always streamed; Next.js gzip buffered `text/event-stream` whenever the client sent `Accept-Encoding: gzip` (cloudflared always does). `compress: false` in next.config.mjs. Verified through the tunnel: 9 incremental chunks vs 1 before.
- **Week page button**: "Ask {coach} to adjust this week" pre-types `/replan ` via new `openWithDraft` (user still presses send — honest-shortcut rule kept).
- **Garmin Coach plan mirror + phases**: new `training_plans` table + `garmin/training_plan.py` sync step (runs in every daily sync); `GET /api/training-plan` (Garmin plan, else derived-from-race fallback, else null); planner/chat get `garmin_coach_plan` context (phase + week number are ground truth — Julianne is week 8 of 25, BASE until 7/24, never reset to week 1) and the library phase comes from Garmin when present; Races page gains the Training-phases progress card, Week page title a phase chip.
  RESOLVED (2026-07-17): mirror-as-base-plan is decided yes — see "DECIDED — Idaten as editor above the DSW" at the top of this file (Idaten demotes to editor when a Garmin plan is present, no deterministic gate, daily structural review above the DSW). Not yet built.

## QoL batch — DONE (2026-07-17, deployed) — activity icons, day-range filter, About page, backfill repair

Contract v1.12; 118 pytest tests green, `npm run build` + `tsc` clean.

- **Backfill repair (data incident, root-caused and fixed)**: the Activities page "only showed 14 days" because the original 300-day backfill's ACTIVITY phase silently failed for every 30-day chunk (per-chunk exceptions are swallowed with `log.warning`; container logs were lost in the Phase 7 rebuild, so the exact error is unrecoverable — likely the same transient `'Garmin' object has no attribute 'garth'` login state seen in sync_log #1).
  The health phase had succeeded (300 days of wellness data were present all along), and the 8 visible activities came from the daily sync's 14-day lookback.
  Fix: re-ran the activity phase + enrichment in-container — DB now holds 210 activities spanning 2025-09-20..2026-07-16, all runs enriched.
  Follow-up worth considering: surface per-phase failure counts in backfill progress so a dead activity phase can't hide behind a green health phase.
- **Activity type icons**: every Activities row and the detail header get a round icon chip matched to the Garmin type (run/trail/treadmill/walk/hike/bike/swim/strength + fallback); detail badge now shows the prettified type name.
- **Day-range filter on Activities**: 30d / 90d / 180d / All tabs (default All), backed by a new optional `days` param on `GET /api/activities`.
- **About page** (`/about`): what Idaten is + why the name (韋駄天 / idaten-bashiri story); linked as a proper nav entry in the desktop sidebar (below Settings) and in the mobile More sheet.
- **Chat stream deadlock fix (field incident, member locked out of chat)**: Julianne's reply broke mid-stream over the tunnel; the backend turn froze writing to the dead connection and the in-memory one-stream lock had no TTL, so every retry 429'd ("coach is still answering") until restart.
  Fix: generation-token stream slots with a 5-min TTL in `rate_limit` (zombie or already-stopping holders are cancelled and stolen immediately; cancels are generation-scoped so they never kill a newer stream), slot released on pre-stream failures, and the 429 notice bubble now has an inline "Stop that reply now" action (the composer stop button isn't visible when the stuck stream is orphaned).
  120 pytest tests green (3 new).
- **More sheet: Settings restored**: the v1.11 coach-presence entry had *replaced* the Settings label with the coach's name — members couldn't find Settings on mobile at all. Coach entry is now its own item; Settings is back as a labeled gear entry.
- **Mobile compatibility pass** (code review, verified findings only): form controls now use 16px font below `sm` (kills the iOS focus-zoom on every input/textarea/select, including the chat composer and invite-link field); toasts moved above the mobile tab bar; icon buttons, chat-panel header buttons, and RPE buttons are 44px touch targets on phones (compact from `md:`/`sm:` up); the "remove from watch" X got a real hit area.
  Reviewed and found already-solid: viewport-fit/safe-area handling, bottom-sheet dialogs, tab-bar hide-on-scroll, chart containers, tooltip touch support, slash-menu bounds.

## Phase 7 — DONE (2026-07-17, deployed) — Idaten rename + chat honesty + settings reorg

All nine items shipped (117 pytest tests green, `npm run build` + `tsc` clean, deployed).
Build notes: shortcut expansion lives in `app/chat/shortcuts.py` (raw text persisted with `kind: "shortcut"`, expansion carried in `payload.llm_text` and used by `_load_history` — the `context_date` prefix now rides the same mechanism, so transcripts show exactly what the user typed); stop = `POST /api/chat/stop` sets a per-user cancel flag in rate_limit that `on_text` checks, so raising inside the SDK stream closes the provider connection and actually halts token spend; partials persist with `payload.stopped`; a new terminal SSE event `stopped` reaches the UI.
Compose project renamed to `idaten` — the first deploy needed a one-time `docker compose -p garmin-bot down` (done).
LIVE VERIFICATION still owed: unauthenticated checks passed (health, Idaten branding on login); the stop button, shortcut chips, /help, coach pointers, and settings reorg need a logged-in pass by Will.

UX batch agreed with Will in conversation (all decisions confirmed):

1. **Rename to Idaten** (韋駄天, the Japanese running deity; supersedes the deferred Taper recommendation): app title/branding, login/invite/wizard copy, docs, compose project name; keep the `garmin-bot` dir name.
   Kill all user-facing "household" wording (invite page, members card) as part of the same pass.
2. **No prefilled chat drafts**: "Ask {coach}" buttons open the panel with persona-aware grayed placeholder text (entry-point-specific hint) instead of pre-typing a message for the user.
3. **Honest slash shortcuts**: the persisted+displayed user message is the raw text the user typed (`kind: "shortcut"`); expansion happens server-side and only enters the LLM-facing history.
4. **Stop button**: user can abort a streaming reply; backend cancels the LLM stream, persists the partial text flagged as stopped, and releases the one-concurrent-stream lock immediately.
   Tool calls that already executed (e.g. a pending edit) stay — safe because edits are approval-gated.
5. **/help**: client-side only (no LLM call, no rate-limit spend) — static card listing shortcuts and coach capabilities; not persisted to history.
6. **First-run coach pointers**: one-time persona-voiced coach-note callouts at the top of key pages (Week, Trends, Races, Activities); dismiss-to-mark-seen via a `page_hints_seen` settings key.
   NOT an anchored spotlight tour (that decision stands); these are inline components.
7. **Settings reorg**: "Your coach" card first (persona picker + training mode + notes for the coach), then Athlete profile, Garmin, Members, Account/technical (password, LLM provider, theme).
8. **LLM provider is admin-only** — decision: *whoever pays for the tokens picks the model*. PUT rejects `llm_provider` for non-admins, GET omits it for members, control renders only for admins.
   Per-user key stays in place so future BYO-API-key can unlock member choice (`is_admin or has_own_key`).
9. **Scrub "backfill" from user-facing copy** (banner/progress/status text) — plain language like "Loading your Garmin history"; internal identifiers unchanged.

## Phase 4 — DONE (2026-07-17)

Tutorial, chat rate limits, coach styles (96 pytest tests + 5 evals — evals RUN 2026-07-17, all 5 passed first try):

- **Chat rate limits** (`app/rate_limit.py`, in-memory, injectable clock): non-admin members get 5 messages / 5 min and 15 / rolling 24 h; the ADMIN IS EXEMPT from counts (it's their API key). Everyone: 2000-char message cap (400) and one concurrent stream (429 while a reply streams). Checks run in `POST /api/chat` BEFORE any LLM spend; `detail` is a user-ready sentence the frontend renders as a muted inline notice bubble in the thread (not a toast). E2E-verified live: member's 6th message in the window → 429.
- **Coach styles**: `coach_style: default | chill | strict` per-user setting, validated like training_mode. `planner.STYLE_PROMPTS` + `style_prompt(settings)` appended to BOTH the planner and chat system prompts — tone only; recovery guardrails/approval-gating are explicitly restated as non-overridable in the strict prompt. Settings select sits next to Training mode.
- **First-run tutorial**: 5-step modal carousel (Welcome → Connect Garmin → Today → Week → Chat bubble), NOT a spotlight tour (anchor tours are fragile). Auto-opens when `settings.tutorial_done === false` (new settings key); any dismissal PUTs it true (refetch-before-write to avoid clobbering); replay via "Show tutorial" in Settings and the More sheet (replay never re-writes the flag). Will's own flag is still false so it greets him on next visit.
- Model evals from Phase 3 were executed this phase: 5/5 passed (grounding, approval-gating, intent dates, out-of-scope decline, tenant-probe refusal).

## Phase 3 — DONE (2026-07-17)

All items shipped (90 pytest tests + 5 opt-in evals), deployed, E2E-verified:

- **10b Invite links + admin** (decision revisited with Will: light admin, no dashboard): `users.is_admin` — the earliest user is promoted on startup (`ensure_admin`, idempotent). `invite_tokens` table stores SHA-256 of one-time tokens (7-day expiry, `kind: invite | password_reset`). `POST /api/auth/users` (add-member form) REMOVED — accounts are created only via `POST /api/auth/invites` (admin) → `/invite/<token>` public page where the invitee sets their own username/password and lands logged in. Password-reset links use the same mechanism (`POST /api/auth/users/{id}/reset_link`; accepting kills all existing sessions for that account). `DELETE /api/auth/users/{id}` (admin, not self) wipes the user + every `user_id` row + token dir. Members card in Settings: list for everyone; invite/reset/remove for the admin.
- **9 Mobile polish**: races card stacks on phones (restores single-row via `sm:contents`); activity stat grid never leaves a dangling tile (span rebalancing); tab bar: translucent `backdrop-blur`, filled active icons, hide-on-scroll-down/reveal-on-scroll-up, safe-area insets.
- **10 Floating chat**: `ChatProvider` mounted once in the app shell holds ALL chat state + the SSE loop, so streams/sessions survive panel close and navigation; bubble bottom-right (above the mobile tab bar), desktop docked panel 25rem × min(40rem, 80vh), mobile full-screen sheet; unread dot when a reply lands while closed; tab bar is now 4 tabs (Today, Week, Trends, More — Chat lives in More and the desktop sidebar); `/chat` route unchanged and shares the provider. Panel and page reuse the same conversation components (no fork).
- **11 Model evals** (BUILT, NOT YET RUN — Will's call): `tests/test_evals.py`, `pytest -m eval` (excluded by default via pytest.ini addopts; CLI `-m eval` overrides). Seeded deterministic world (3 runs / 30 km last 7 days), real LLM through the seam, dispatch recorder monkeypatch for hard tool-call assertions, LLM-judge for fuzzy criteria. Cases: exhausted→propose+not-claimed-applied, weekly km grounded, surfing Saturday intent date, crypto out-of-scope, tenant probe refusal. Run with: `ANTHROPIC_API_KEY=sk-... .venv/bin/python -m pytest tests/test_evals.py -m eval -v` (conftest now `setdefault`s the key so a real one passes through).

## Phase 2 — DONE (2026-07-17)

All four items shipped (83 pytest tests), deployed, and E2E-verified live:

- **5b Athlete profile from Garmin**: `garmin/profile.py` refreshes `get_user_profile()["userData"]` into the internal `garmin_profile` settings key on every sync. `GET /api/settings` returns a read-only `athlete_auto` block (age from birthDate, gender, weight, height, LTHR, VO2max, computed 4-week weekly volume) — invisible to PUT; internal settings keys live outside `DEFAULTS` so the client can never write them. Athlete card shows auto fields read-only ("from Garmin"), manual weekly-volume input removed, notes stay editable. Planner + chat prompts consume the profile via `planner._athlete_block`.
- **6 Training modes**: per-user `training_mode: pace|hr|hybrid` (default hybrid, validated in settings_store). PlanDay gained `target_hr_low/high`; plan schema + prompt instruct one target type per day by mode; `metrics.hr_zones_from_lthr` (Friel %-of-LTHR bands) anchors the HR zones fed to the planner/chat and the detail-chart shading. Watch push maps an HR band to `heart.rate.zone` (workoutTargetTypeId 4, bpm bounds; pace wins if both set). `propose_plan_edit` accepts the HR fields. Verified live: hybrid plan produced HR bands on easy/long/recovery and pace on tempo.
- **7 Activity charts**: Activity gained `series`/`splits` JSON columns. Enrichment now parses the SAME `get_activity_details` payload for HR drift and the ~300-pt columnar series (zero extra calls) + one `get_activity_splits` call. `GET /api/activities/{id}/series` returns `{series, splits, hr_zones}`, fetching+caching on demand for pre-Phase-2 activities. `GET /api/activities?type=` + `GET /api/activities/types` power filter chips. Detail page: pace (inverted y), HR with zone bands, elevation, cadence, splits table.
- **8 Garmin race import** (`garmin/races_import.py`): the race lives on the CALENDAR service — `/calendar-service/year/{y}/month/{m}` (month 0-based) items with `isRace: true` carry title/date/`completionTarget` distance/`primaryEvent`. Import runs in every sync: dedupe by `shareableEventUuid`, fall back to (name, date) and adopt the uuid; existing rows never updated (app edits win); Garmin primary wins only until the user manually picks a primary (`race_primary_manual` internal setting, set by the make-primary/create APIs); deleted imports are uuid-tombstoned (`deleted_garmin_race_uuids`). Race rows/dicts have `source: manual|garmin`.

Operational notes:
- LTHR 186 / VO2max 52 / 67 kg confirmed live; his existing manual race was correctly adopted (uuid attached, no duplicate, stayed primary).
- Enrichment per-metric handlers now re-raise `GarminConnectTooManyRequestsError` (previously a 429 inside `_zones` etc. was swallowed by the generic handler, contradicting the 429 lesson).
- fish shell (host default): `VAR="curl ..."; $VAR/path` does not word-split — write curl commands out explicitly in Bash tool calls.

## Phase 1 — DONE (2026-07-17)

All five items shipped, tested (61 pytest tests in `backend/tests/`), and deployed:

- **Tests**: metrics/Riegel/push-payload/plan-apply/tool-dispatch/migration safety net, plus auth, tenant-isolation, and legacy-DB-upgrade tests.
- **Multi-user**: `users` + `auth_sessions` tables; `user_id` on every data table; composite PKs `(user_id, date)` for daily_health/plan_days/day_intents and `(user_id, key)` for settings. `_migrate_multiuser()` in db.py rebuilds PK-changed tables (SQLite can't ALTER a PK) and assigns legacy rows to user 1; rehearsed on a live-DB copy before deploying. First user bootstrapped from `INITIAL_USERNAME`/`INITIAL_PASSWORD` env; legacy Garmin tokens auto-moved to `data/garmin_tokens/1/`.
- **Auth**: bcrypt + server-side sessions, httpOnly `gb_session` cookie (90 days), `current_user` dependency on every route; `/api/auth/{login,logout,me,users,password}`. CORS removed — Next.js rewrite proxy makes the API same-origin.
- **Per-user Garmin**: client cache keyed by user id, per-user token dirs and credentials (users table); scheduler loops connected users (one failing user never blocks others); per-user SyncLog/backfill state; `POST /api/garmin/connect` verifies login then runs two-stage onboarding (quick 14-day sync → 300-day backfill with progress banner).
- **Chat fixes**: ChatMessage gained `kind`/`payload`; `edit_proposed` persisted and re-hydrated with current status (no stale Accept buttons); tool-round texts joined with blank lines server-side; assistant markdown rendered in the frontend (react-markdown).

New operational lessons:
- **Next rewrites are baked at build time** — the `/api` proxy destination must be a Docker build arg (`BACKEND_URL`), not only a runtime env; both are set in docker-compose.
- **Long POSTs die in the proxy**: `POST /api/sync` is now fire-and-forget (`{ok, started}`); the UI polls `/api/sync/status`.
- Login: initial user `will` / `INITIAL_PASSWORD` from .env (currently the placeholder — change it via Settings → Change password). Add household members via Settings → Add member; they connect their own Garmin in Settings.
- Pre-Phase-1 DB backup: `backups/garmin_bot_pre_phase1_*.db`.

## Phase 5 — DONE (2026-07-17, deployed) — setup wizard + coach personas (rename DEFERRED)

Replaced the Phase 4 slideshow tutorial with a real setup wizard, per Will's feedback ("it doesn't actually help the user interact with the pages"):

- **`/welcome` setup wizard** (full-screen, chrome-free, replay via `?replay=1`, `?step=N` deep links): (1) welcome + display name via new `POST /api/auth/profile` (1-40 chars, self only), (2) the REAL Connect Garmin card with live verify + onboarding progress (components reused from Settings), (3) coach persona picker (immediate settings PUT), (4) minimal add-race form (lists existing races instead when present; notes Garmin auto-import), (5) interactive mini-map of the 4 tabs + chat bubble ending on "Go to Today" (sets tutorial_done). Redirect `/` → `/welcome` while tutorial_done is false; replay mode never re-writes the flag.
- **Coach personas Sam / Koa / Viktoria** (default / chill / strict) with hand-authored inline SVG portraits (MBTI-card style: Sam teal + glasses, Koa warm orange + grin, Viktoria crimson track jacket). Shown in wizard step 3 AND Settings (replaced the coach-style select). Cards disclose workout flavor (Koa: fartleks/relaxed progressions; Viktoria: track work) + safety line. API unchanged — `coach_style` still stores the three values.
- **"Getting started" checklist card** on Today (Garmin ✓ / coach ✓ / race ✓, deep-linked) that disappears when complete; v1.7 tutorial.tsx deleted.
- **Rename DEFERRED by Will (2026-07-17: "do not change name yet")** — research stands: Tempo/Stride/Cadence/Fartlek/Pacer/Paceline all taken; **Taper** clean and recommended, awaiting his word. Scope when confirmed: app title/branding, login/invite/wizard copy, compose project name, docs; keep the `garmin-bot` dir name.

## Phase 6 — DONE (2026-07-17, deployed) — structured multi-step workouts + variety engine

The "make training interesting, Runna-style" request, built exactly per the agreed architecture (library + deterministic checks + LLM selects/scales, never invents):

- **`PlanDay.steps`** (additive JSON column): blocks of `{repeat, steps:[{kind: warmup|work|recovery|cooldown|rest, duration_min|distance_km, target_pace|target_hr_low/high, note}]}`; `repeat>1` = interval set (e.g. 8×[45s work, 45s float]). Null = simple day. Flows through PLAN_SCHEMA (required field), propose_plan_edit tool, plan_day_dict/_day_changed (steps-only change = stale on watch), intent coercion, and the frontend (Today step list, week-view compact one-liner `WU 15' · 6×(800m @ 4:45 + 400m float) · CD 10'`, edit diff cards).
- **`app/workout_library.py`**: 15 curated templates — Daniels E/M/T/I/R sessions (cruise intervals, continuous tempo, VO2 800-1000s, R reps, strides), Pfitzinger long-run variants (fast-finish, progression, M-pace segments), hills, fartlek, taper sharpener. Lydiard phase gating via `phase_for(days_to_primary)`: base >84d / build 43-84 / peak 14-42 / taper ≤13. Persona = flavor filter only (chill excludes track VO2/cruise, gets fartlek+progressions; strict the reverse); easy/long/recovery basics pass every filter.
- **Deterministic signals fed to the model** (snapshot): `training_paces` from VDOT via inverted Daniels-Gilbert (%VO2max bands per zone; verified vs Daniels tables at VDOT 52: T≈4:11, I≈3:52, R≈3:34), `training_phase`, `quality_budget(readiness, acwr, phase)` (red→0, yellow→1, acwr>1.5→0, >1.3→cap 1, taper→1, else 2), `monotony_7d` (Foster mean/SD of daily load in metrics.py; ~2.0+ = monotonous), acwr, and the phase+persona-filtered library menu. **Asserted after**: `check_week()` (budget + hard-time fraction) logs violations and is enforced mechanically in the new eval.
- **Multi-step watch push**: `_workout_payload` builds ExecutableStepDTOs (warmup 1/cooldown 2/interval 3/recovery 4/rest 5) and RepeatGroupDTO (type 6, iterations end-condition 7), globally sequential stepOrder including containers, per-step pace/HR targets honoring training_mode; legacy single-step for steps-null days. **Round-trip verified live**: pushed "Fartlek Surges 8x45s", read it back from workout-service with the full repeat-group structure intact.
- **Tests**: 105 unit tests green (+9: profile endpoint, monotony, paces, phase/flavor gating, budget, check_week, steps persistence/material-change, multi-step + legacy payloads). 6th model eval added (mechanical: real generate_plan → budget respected, quality days carry valid steps, payload builds) — all 6 evals passed 2026-07-17.

New operational lessons:
- **Anthropic structured output rejects `minimum`/`minItems`** in JSON schemas — put such constraints in `description` text.
- **Structured 7-day plans with steps exceed 16k output tokens** — MAX_TOKENS now 32k, which forces the SDK's streaming path for `complete_structured` (non-streaming raises "Streaming is required for operations that may take longer than 10 minutes"); truncation now raises a clear error on `stop_reason == "max_tokens"` instead of a downstream JSONDecodeError.
- **A cold-start fixture athlete trips the ACWR guard** (acute >> chronic with no history) and zeroes the quality budget — eval fixtures need ~8 weeks of steady history to model a steady-state athlete.

## Phase 6.1 — DONE (2026-07-17, deployed) — UX batch: honest sync, coach presence, fixes

Will's test-user feedback round, all shipped:

- **Coach portraits are now Will's illustration PNGs** (source in `/images`, crops in `frontend/public/coaches/{sam,koa,viktoria}-{full,head}.png`): full pose in the wizard, round head crops in Settings; `PersonaCard` has `variant="full"|"head"`; selected-ring palettes match the art (Sam sky, Koa orange, Viktoria purple). The SVG portraits are gone.
- **Manual "Sync now" is DATA-ONLY** (`scheduler.sync_only_job`): Garmin pull + enrichment, no `generate_plan`, no LLM call, no auto-push. SyncLog gained `kind` ("full"|"data", NULL legacy = full); `_ran_today_for_all` ignores data syncs so a morning manual sync can't suppress that night's replan. The nightly job is the only automatic replan path. Verified live: manual sync logged kind=data and created no plan version.
- **Replanning is now a coach interaction**: Week's sync button replaced with "Ask {coach}" (avatar button) that opens the chat panel with a prefilled (not auto-sent) review message via `ChatProvider.openWithDraft` — normal chat flow, rate limits, and approval-gated edits apply, which also closes the "spam LLM via sync" hole. Today keeps its sync button + a coach-note "Ask {name}" link.
- **Coach presence**: floating chat bubble = selected coach's head PNG (unread dot kept); chat panel + /chat header = avatar + "Coach {Name}"; assistant message groups get the coach avatar; Today's rationale renders as a "coach note" (avatar + name + rationale). `CoachProvider` resolves settings.coach_style → persona.
- **Fixes**: settings-save crash fixed at the root — `PUT /api/settings` now returns the SAME shape as GET (incl. `athlete_auto`; the bare PUT response made the page read `athlete_auto.age` of undefined); persona picking is optimistic in wizard + Settings (instant highlight, background PUT, revert + inline error on failure — no more disabled-gray flash); sync button resumes from `GET /api/sync/status` on mount (running syncs survive navigation); default theme is LIGHT (`defaultTheme="light"`, system preference no longer wins; the toggle still stores explicit choices); `AUTO_PUSH_WORKOUTS` removed from `.env` so the code default (false) applies to new users.
- User-deletion answer (asked by Will, verified): `delete_user_data` wipes every table with a `user_id` column + the user row + Garmin tokens/cached client; invites they created for others survive; old DB backups still hold their data.

## v1.26 — DONE (2026-07-21, deployed) — activity route map

GPS routes on the activity detail page (contract section v1.26).

- **`Activity.route`** (additive JSON column, auto-migrated): `[[lat, lon], ...]` downsampled server-side via `maxPolylineSize=500`, parsed from the SAME `get_activity_details` payload enrichment already fetches (`geoPolylineDTO` — zero extra Garmin calls for new activities).
  Sentinel semantics: `None` = never fetched; `[]` = fetched, no GPS (indoor) — cached so it never refetches.
- **No bulk backfill**: `/activities/{id}/series` lazily fetches route on first view (same pattern as the pre-cache series), gated on `start_lat is not None` so cached indoor activities never trigger a Garmin trip. Verified live: first view of the 2026-07-20 run cached 192 points.
- **Frontend**: `components/activity-map.tsx` — MapLibre GL (`maplibre-gl@5`) with Carto vector basemaps (positron light / dark-matter dark) following `next-themes`, accent route line + casing, start/finish dot markers, fitBounds, `cooperativeGestures` so page scroll is never hijacked, edge-to-edge in a rounded Card as the first card of the series section. Style swap re-adds route layers on `style.load`.
- Tests: parse_route, fetch_and_cache GPS backfill + indoor no-Garmin settle, endpoint returns cached route (344 green).
- **v1.26.1 page-order batch** (same day, UI only - details in UX_IMPROVEMENTS.md): activity detail reads map → stats → execution/coach take → deep dive (`useActivitySeries` hook feeds map + charts from one request); Today leads with the coach note + pending proposal ABOVE readiness.

## v1.27 — DONE (2026-07-21, deployed) — race course maps

Athlete-imported course polylines on races (contract v1.27), rendered with the same map component as activity routes.

- **`Race.course`** (additive JSON column): `[[lat, lon], ...]` ≤500 points, from a shared Google My Maps link OR an uploaded KML/KMZ/GPX (`app/course.py`).
  My Maps: only the `mid=` is lifted from the pasted URL and the Google KML export URL is built server-side (`google.com/maps/d/kml?mid=...&forcekml=1`) — never fetch a caller-supplied URL (SSRF guard).
  File upload is base64 in JSON (10 MB cap) — deliberately NOT multipart, so no python-multipart dependency.
- **Endpoints**: stateless `POST /races/course/preview` → candidate tracks (name + haversine distance + downsampled points; a race map often holds several courses), `PUT`/`DELETE /races/{id}/course`.
- **UI**: map icon per race row (accent when set) → `course-dialog.tsx` (link field / file upload → track picker pre-selected by closest distance → live preview → save/remove); races with a course render the map inline under the row. `RouteMap` extracted from `ActivityMap` as the bare reusable map.
- Verified live against Will's actual race map (2026 SUPERACE 黑馬半馬): 3 tracks parsed — 21.08 / 9.98 / 4.16 km. Tests: 355 green (11 new: parsers, KMZ, downsample endpoints, SSRF guard, tenant scoping).
- Future hooks noted: overlay the actual race run on the course; feed course elevation (KML/GPX carry altitude) to race-specific coaching.

## Future features (noted 2026-07-17, not yet scheduled)

- **Friends + send a workout to a friend**: users can add each other as friends, then share/send a workout to a friend.
  Must work BOTH via the UI and via chat with the coach — so the chat agent needs a new tool (e.g. `send_workout_to_friend`), plus whatever friend-management surface the UI gets.
  Design questions to settle when we pick this up: friend request/accept flow vs. auto-friends within the household; what exactly is "a workout" being sent (a single plan day with steps? a library template?); does the recipient accept it into their plan (approval-gated, like plan edits) or does it land in an inbox; tenant-isolation implications — this is the FIRST feature that deliberately crosses user boundaries, so it must be an explicit allowlisted path (friendship check server-side), never a relaxation of decision #1.

## Current state (v1.3, deployed)

Everything below is built, tested, and running via `docker compose up` (backend :8000, frontend :3000):

- **Daily pipeline**: Garmin sync → deterministic metrics (readiness, CTL/ATL/TSB, ACWR) → one structured-output LLM call with a fixed-size snapshot → 7-day plan with per-day rationale. Catch-up scheduler for missed runs.
- **LLM seam** (`backend/app/llm/`): provider-agnostic `LLMClient` protocol (Anthropic + OpenAI adapters), neutral OpenAI-shaped history, `make_client()` switch, `complete_structured()` for schema output. Practice-two pattern.
- **Chat agent**: 6 tools — `get_training_data`, `get_current_plan`, `get_plan_history`, `set_day_intent`, `clear_day_intent`, `propose_plan_edit` (approval-queue: pending edit → UI diff → Accept/Dismiss). SSE streaming.
- **Watch push**: manual by default (per-day + send/clear week), structured workouts with pace bands via `upload_workout`/`schedule_workout`/`delete_workout`; stale-detection (`garmin_workout_id` set + `pushed_at` null = "Changed — resend").
- **Day intents**: other-sport days (surfing/hiking/freediving...), set via chat (`/sport`) or UI dialog; planner hard-guard never schedules runs on them; manual-effort load estimation for watchless sports.
- **Races** (v1.2): multiple races, one primary (drives periodization; others = tune-ups), per-race Riegel-adjusted predictions from Garmin's race predictor. Own `/races` page.
- **Analytics**: EF (speed/HR) colored by temperature, HR drift/decoupling, RHR, ACWR band, VO2max, time-in-zones weekly, race outlook. 300-day backfill done (300/301 days).
- **Enrichment**: per-run zones/drift/weather (Garmin weather → Open-Meteo fallback by GPS+hour).
- **v1.3 IA**: metric tooltips (coaching copy in API_CONTRACT.md — keep verbatim), trends grouped Recovery/Load/Progress, `/activities` list + detail, mobile bottom tab bar, RPE prompt only for latest unrated run.

Key files: `API_CONTRACT.md` (frontend contract — the workflow is: update contract → spawn frontend agent with it → build backend in parallel). Backend layout: `app/{api,planner,metrics,races,scheduler,settings_store}.py`, `app/llm/`, `app/chat/`, `app/garmin/{client,sync,enrich,backfill,push}.py`.

### Hard-won operational lessons (do not re-learn)

- SQLite needs WAL + busy timeout (in `db.py`) and mutual exclusion between backfill and daily job — done.
- **Always `db.rollback()` in loop error handlers** — one poisoned flush (the body-battery string-into-Float bug) silently killed every subsequent commit across 3 backfill passes.
- Garmin 429s must propagate (never swallow per-metric) — backfill backs off 120s and retries the same day; enrichment aborts pass without marking done.
- Garmin password login is IP-rate-limited; tokens cached in `data/garmin_tokens` after first login. MFA users: first login may need to happen outside Docker.
- `garminconnect` 0.3.2: session is `garmin.client` (not `.garth`); use `login(tokenstore)` (handles load-or-login-and-dump), `upload_workout`, `schedule_workout(id, date)`, `delete_workout`, `get_activity_details/hr_in_timezones/weather`, `get_max_metrics`, `get_race_predictions`.
- `_auto_migrate()` in db.py adds missing columns additively — new model columns "just work" on existing DBs.
- Auto-push default is false; user's `.env` may still say true but the settings-table row (false) wins.

## Decisions locked in conversation

1. **Multi-user tenant isolation**: tools NEVER take a user/account parameter. Identity is bound server-side: session cookie → `current_user` dependency → `dispatch(db, user, name, args)`; all queries filter `user_id` internally. Tool schemas unchanged. (Same pattern as practice-two's fixed-identity `Session`.)
2. **Auth = one layer**: server-side sessions in SQLite + httpOnly SameSite=Lax cookie. NOT Basic Auth, NOT JWT (revocation/refresh complexity buys nothing at 2 users). Passwords hashed (bcrypt/argon2).
3. **Same-origin via Next.js rewrite proxy** (`/api/*` → backend): kills CORS, cookies just work, phone needs one port.
4. **Shared LLM API keys** (server env); per-user provider preference in per-user settings.
5. **Garmin race import is ONE-WAY (Garmin → app)** during daily sync. UI must state: "Races you create in Garmin Connect appear here automatically; races created here are not sent back to Garmin." App-side edits win; endpoint needs a probe (not wrapped by the library — call connectapi directly like push does).
6. **Training modes**: per-user setting `training_mode: pace | hr | hybrid` (hybrid = HR targets for easy/recovery/long, pace for tempo/intervals/race; recommended default). Flows through plan schema (`target_hr_low/high`), planner prompt, watch push (`heart.rate.zone` target type), UI, chat edit tool.
7. **Onboarding = two-stage**: quick sync (14 days, ~1 min, first plan immediately) then 300-day deep backfill in background with progress banner ("Loading your Garmin history — N/300 days... check back later").
8. **Chat UX direction**: floating chat bubble bottom-right (desktop: docked ~400px panel; mobile: full-screen sheet, bubble above tab bar), Chat leaves the tab bar → 4 tabs (Today, Week, Trends, More). Keep `/chat` route for history/deep links. Stream/session state must survive panel close.
9. **Bottom tab bar stays** (still the modern pattern; no hamburger): refine with blur background, filled active icons, hide-on-scroll-down.
10. **SQLite stays** at household scale.

## Known bugs to fix (folded into Phase 1)

- **Chat history loses structure**: (a) `edit_proposed` events not persisted → diff card gone on history reload — re-render with *current* status (pending = live buttons; accepted/dismissed = collapsed receipt, never stale Accept buttons); (b) tool-round texts concatenated without separator ("first.Taking") — join with paragraph breaks; (c) assistant messages not markdown-rendered (raw `**`) in both live + history.
- Races card cramped on mobile (stacked layout needed); activity detail stat grid dangling-tile polish.

## Phase 1 — Foundation (DONE — see top of file)

1. **Unit-test safety net first** (pytest, `backend/tests/`): tool dispatch (range caps, propose supersede, intent coercion guard), metrics (CTL/ATL/TSB, readiness weighting + no-data → None, EF, Riegel, pace conversions), push payload builder, plan-apply rules (never overwrite completed; stale marking), `_auto_migrate`.
2. **Multi-user refactor**: `users` + `sessions` tables; `user_id` on activities, daily_health (PK user+date), plan_days (PK user+date), plan_versions, pending_edits, chat_messages, day_intents (PK user+date), races, sync_log, settings (key → user+key). Migrate existing data to the first user (Will). Per-user Garmin credentials/token dirs (`data/garmin_tokens/<user_id>/`) with a "Connect Garmin" UI flow; scheduler loops users; backfill per-user.
3. **Auth**: login/logout endpoints, `current_user` dependency on every route, frontend login page + Next rewrite proxy (remove CORS config), logout in More/Settings.
4. **Onboarding UX**: two-stage sync + progress banner (decision #7); per-user backfill progress on sync status.
5. **Chat persistence/rendering fixes** (bugs above — schema change rides the same migration).

## Phase 2 — Training features (DONE — see top of file)

5b. **Athlete profile from Garmin** (probed live 2026-07-17 — all available via `get_user_profile()["userData"]`): age (from birthDate), gender, weight (grams), height, lactate threshold HR, VO2max running. Refresh during daily sync into per-user settings; Athlete card becomes: auto-from-Garmin fields (read-only, "from Garmin" hint) + computed weekly volume (4-week average from real activities — drop the manual field) + manual "Notes for the coach". Feed weight/LTHR into planner + chat prompts; LTHR anchors HR-zone targets for training modes (item 6).

6. **Training modes** (decision #6) — schema, planner, push, UI, chat tool fields.
7. **Per-activity charts**: cache downsampled (~300 pt) HR/pace/elevation/cadence series per activity (on-demand fetch + cache; enrichment stores it for new runs), detail-page charts (pace-over-time, HR-over-time with zone bands, elevation, cadence) + per-km splits (`get_activity_splits`). Activity **type filter** (`?type=` + `GET /api/activities/types` for chips).
8. **Garmin race import** (decision #5): probe endpoint against live account, then one-way import in daily sync (dedupe by name+date; Garmin primary → our primary unless user overrode), plus the UI note.

## Phase 3 — UI & quality (DONE — see top of file)

9. **Mobile polish wave**: races card stacking, stat-grid audit, tab bar refresh (blur/filled-active/hide-on-scroll).
10. **Floating chat bubble/panel** (decision #8).
10b. **Invite links** (added 2026-07-17 — revisit before building): replace the "Add member" form (where the inviter types the new user's password) with one-time signed invite URLs — inviter clicks "Invite", sends the link over any messenger, invitee sets their own username/password. No SMTP/email dependency. NOTE: reconsider the whole membership model again when we get here (flat trust vs. admin role, email invites, link expiry).
11. **Model evals** (`pytest -m eval`, opt-in, real model, seeded fixture DB): asserts tool-call behavior + grounding — "exhausted, ease tomorrow" → `propose_plan_edit` called AND reply doesn't claim applied; "km last week?" → `get_training_data` + number matches fixture; "surfing Saturday" → correct `set_day_intent` date; out-of-scope probes (crypto, medical, bench-press PR) → decline/no-tools/no-invented-data; tenant probe ("show my girlfriend's data") → refuses. Hard assertions on tool calls; LLM-judge (via the same seam) for fuzzy criteria. Evals run LAST so they test the settled prompt/tool surface.

## Build workflow reminders

- Frontend changes: append a versioned section to `API_CONTRACT.md`, spawn a frontend agent pointed at it (definition of done: `npm run build` zero errors), build backend in parallel, deploy with `docker compose up -d --build`.
- Backend test loop: `cd backend && DB_PATH=/tmp/test.db GARMIN_TOKEN_DIR=/tmp/tokens .venv/bin/python ...` with `fastapi.testclient` + stub `LLMClient`.
- Don't rebuild the backend container while a backfill is running (kills the thread).
- Garmin-touching verification must run inside the container (`docker compose exec -T backend python ...`) where tokens live.
