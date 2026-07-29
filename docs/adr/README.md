# Architecture decision records

One file per decision that shaped the system.
Each records the context, the options weighed, and why the chosen one won - so the reasoning survives after the conversation that produced it is gone.

- [0001](0001-start-sh-is-the-test-gate.md) - The deploy script is the test gate, not CI
- [0002](0002-weekly-summary-is-its-own-artifact.md) - Weekly summary is its own artifact, not part of an activity or daily review
- [0003](0003-coach-toggles-are-instance-level.md) - Coach call-site toggles are instance-level, not per-member
- [0004](0004-hand-rolled-agent-loop.md) - The chat agent loop is hand-rolled, not a framework
- [0005](0005-llmclient-provider-seam.md) - Provider access goes through a hand-written LLMClient seam
- [0006](0006-pending-edit-approval-queue.md) - Plan changes go through a stateful approval queue, not a confirm dialog
- [0007](0007-sqlite-not-postgres.md) - SQLite, not Postgres
- [0008](0008-single-db-user-id-tenancy.md) - Multi-tenancy is one shared DB with user_id on every row
- [0009](0009-constant-cost-daily-plan-generation.md) - System-initiated coach calls are curated one-shots, not agent loops
- [0010](0010-editor-above-the-garmin-plan.md) - Idaten is an editor above the Garmin plan, not a competing author
- [0011](0011-in-process-scheduler-selfheal.md) - The daily job runs on an in-process scheduler that self-heals, not cron
- [0012](0012-outbound-tunnel-owned-by-start-sh.md) - Public access is an outbound Cloudflare tunnel, owned by start.sh
- [0013](0013-garmin-credentials-encrypted-at-rest.md) - Third-party credentials are encrypted at rest, with the key outside the DB
- [0014](0014-feedback-loop-is-a-flight-recorder.md) - The coach-quality feedback loop is a flight recorder, not an autopilot
- [0015](0015-garmin-token-cache-accepted-plaintext.md) - The Garmin OAuth token cache stays plaintext; revocation, not encryption, is the mitigation
- [0016](0016-nightly-qa-judge-scores-every-chat-session.md) - Production QA is the eval judge run nightly over every chat session
- [0017](0017-hr-targets-are-resolved-zone-bands.md) - HR targets are stored as resolved zone bands, never point values
- [0018](0018-scores-pinned-to-executed-prescription.md) - An execution score is pinned to the prescription the run actually executed
- [0019](0019-judge-grades-persisted-context-snapshot.md) - The QA judge grades a persisted snapshot of the context the coach actually saw
