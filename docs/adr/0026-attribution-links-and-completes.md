# Attribution links and completes; a score is optional

A run is linked to its plan day by attribution, not by scoring.
When attribution succeeds - definitive evidence at sync (an Idaten-pushed or Idaten-owned day), the athlete's confirmation on the prompt, or an explicit manual link - the attempted prescription is stamped onto the activity and the day flips to `completed`, whether or not a score could be computed.
The stamped prescription (renamed `attempted_prescription` from `scored_prescription`) is the durable run-to-plan link every surface renders from; the score, when one exists, rides on top of it.
A self-paced day - zero target axes: no pace band, no HR band, no steps - is a legitimate prescription that links and completes unscored, extending ADR 0025's "exactly one axis" down to "at most one; zero means intentionally unscored".

The forces begin with a live defect.
A chat edit replaced a rest day with a self-paced 10K at the athlete's explicit request ("no heart-rate or pace targets"), the workout was pushed, and the athlete executed exactly that workout - the activity even carried the pushed workout's name.
Attribution succeeded twice: automatically at enrichment (`is_idaten_pushed`), and again when the athlete tapped "Yes, score it" on the attribution prompt.
Both times, nothing persisted: a zero-axis day produces no scoring segments, both call sites gated `mark_day_completed` on `score is not None`, the prescription stamp was score-gated too, and the analysis endpoint rejected the run for having no score.
The day stayed `planned`, the run rendered as unattached, and every step of the disappearance was silent - the ADR 0020 failure mode at day level.

The underlying flaw was architectural: the link between a run and its plan day had no representation of its own.
It was an emergent property of scoring - the Today result card filtered on `execution_score`, the Week tick read a day status only the score path wrote, the detail page association read the score-gated stamp, and the athlete's confirmed Yes survived only as a boolean nothing rendered.
Attribution was computed, used, and thrown away whenever a score did not materialize.

Completion is a fact about the world (the workout happened); scoreability is a property of the prescription (is there a band to hold?).
Coupling them meant honoring an athlete's "no targets please" silently cost them the plan linkage, the completed tick, and the coach's post-run narrative - the only feedback a self-paced day can have.
The analysis therefore gates on the link (stamp or score), not the score.

Manual links extend the same machinery: a link names a plan day (own days, within ±3 days, non-rest, not completed) and runs the full pipeline against that day's prescription - a first score for that run, so ADR 0017's no-recompute rule is untouched, and the ADR 0018 provenance freeze applies unchanged (the stamp now carries the linked day's date, since it may differ from the run's).
The coach's `link_activity` tool proposes the same operation through the ADR 0006 approval queue, revalidated at accept time.

Never silent, in three layers: the approval card flags a zero-axis day ("self-paced - will complete but won't be scored") before the human says yes; scoring logs when an attributed run meets an unscoreable prescription; and the UI renders "completed - self-paced, nothing to grade" instead of an empty score slot.
Coach-tagged-only runs (`trainingPlanId` with no Idaten day evidence) still do not link unscored: Garmin tags every run inside a coach plan's window, so that evidence alone is too weak to complete a day without either a score or a human confirmation.

## Considered Options

- **Score zero-axis days anyway (distance-completion ratio)** - rejected: the execution score means "how well you held the band"; a fabricated 100 for finishing the distance pollutes trends, the review's execution signals, and the QA ground truth. Completion and quality are different facts.
- **Forbid zero-axis days at authoring (attach an easy HR band)** - rejected: "self-paced" was the athlete's explicit request; silently strapping a band back on grades homework they were told they didn't have - the exact sin ADR 0018 exists to prevent.
- **An explicit `activity.plan_date` FK for the link** - rejected: ADR 0018 already established "freeze what the run attempted onto the activity" as the link mechanism; a parallel FK is a second source of truth for the same fact. Un-gating the existing stamp completes the existing design.
- **Direct-action coach link tool (no approval)** - rejected: every coach mutation shows a card the human approves (ADR 0006), and this one writes completion history and can trigger a paid analysis call.
- **Attribution stamps the prescription and completes the day; scoring is optional; analysis gates on the link; manual links reuse the pipeline through the endpoint and the approval queue** - chosen.
