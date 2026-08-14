# A shared workout is a cross-tenant snapshot, adapted deterministically and accepted as an override

Sharing a workout with another household member is the first feature that deliberately moves data across the ADR 0008 tenant boundary.
This ADR fixes how that crossing works: what crosses, where it lives, how targets translate to the recipient, and what an accepted share is to the rest of the system.

The `shared_workouts` table is the only place two user_ids ever share a row (`from_user_id`, `to_user_id`).
Every read is scoped by the authenticated side (`to_user_id` for the inbox, `from_user_id` for sending), and the chat tool addresses the recipient by display name, resolved server-side - the tools-never-take-a-user-parameter rule stands.

What crosses is a **snapshot**, not a reference: a whitelisted projection of the sender's PlanDay (type, title, description, duration, distance, targets, steps - never the rationale, which is written against the sender's private readiness context) plus the sender's fitness parameters (HR zones, VDOT) frozen at send time.
A snapshot because the sender's plan keeps moving after the send - the daily job regenerates, chat edits land - and the thing the recipient reviewed must be the thing they accept.
The frozen sender parameters matter for the same reason: zones drift, and translation must run against the zones the targets were authored under, not whatever the sender's zones are on accept day.

**Translation is deterministic code, not an LLM call.**
The system already owns both directions of the mapping: HR bands are resolved from per-user zones (ADR 0017) and paces derive from VDOT via the Daniels cost curve (`metrics.training_paces`).
So "accept with my zones" is a round trip - de-personalize against the sender's frozen parameters, re-personalize against the recipient's current ones:

- An HR bound maps by zone position: find the sender zone containing it and its fraction within that zone, emit the same fraction of the recipient's corresponding zone, then repair through `ensure_hr_band` (ADR 0017's invariants hold on the output).
- A pace bound maps by %vVO2max: pace -> velocity -> VO2 cost -> fraction of sender VDOT, then the recipient's velocity at that same fraction, grounded afterwards against the recipient's observed pace profile (the planner's own grounding floors).
- A recipient in `hr` training mode gets pace targets converted to the equivalent zone band; HR is never converted to pace (no reliable inverse).
- ADR 0020's grammar and ADR 0021's no-uphill-pace rule are enforced on the adapted output.

When either athlete lacks the needed parameters (no Garmin VDOT or zones), adaptation is not offered and the reason is shown - the system does not guess a translation.

**An accepted share writes directly to PlanDay** through `apply_plan_days` with `PlanVersion.source = "shared"`, which is not in `_OVERWRITABLE_SOURCES`.
That one tag does all the integration work: the daily job treats the day as user-owned and plans around it, materialization never re-copies over it, and execution scoring attributes to it exactly as it does an accepted chat edit (ADR 0018 mismatch handling included).
Accept also auto-pushes when `auto_push_workouts` is on, same as edit accept.

## Considered Options

- **Route acceptance through the PendingEdit queue** - rejected: the queue exists so a human reviews an LLM's proposal (ADR 0006); here the human is reviewing a human's send, and the inbox card *is* that review. Accepting a pending edit just calls `apply_plan_days` anyway, so the queue would add a second approval of the same decision and change nothing downstream.
- **Share a live reference to the sender's PlanDay** - rejected: the sender's plan mutates daily; the recipient would accept something other than what they saw, and deleting/regenerating the sender's day would dangle the share.
- **Adapt via the coach LLM** - rejected: the conversions are arithmetic over data both sides already have; deterministic code is testable in layers 1-2 for free, costs nothing per share, and cannot hallucinate a target. The LLM keeps its existing role (effort -> concrete happens at plan authoring, not at sharing).
- **A friendship graph with requests** - rejected: the instance roster is the household (ADR 0008); a friend model would duplicate membership with extra state and no new information.
- **Cross-instance sharing / federation** - out of scope: the deployment model is one instance, outbound tunnel only (ADR 0012). The upgrade path is a portable export of the de-personalized form, which reuses this ADR's translation seam without touching auth or networking.

## Consequences

- `test_tenant_isolation.py` gains share-specific cases; the isolation claim weakens from "no row crosses users" to "only `shared_workouts` crosses users, and only through the share endpoints".
- The snapshot is a projection, so a field added to PlanDay later does not automatically cross the boundary - additions must opt in, which is the safe default direction.
- A pending share expires when its target date passes; expiry is evaluated lazily on inbox reads, so no scheduler work is added.
- The de-personalize half (workout + frozen sender parameters -> relative intensities) is exactly the future portable-export format; building export later is serialization only.
- Sender-side status ("did they accept?") is deliberately absent in v1; adding it later is a read of existing rows, not a schema change.
