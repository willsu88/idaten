# The coach-quality feedback loop is a flight recorder, not an autopilot

Coach quality improves through a loop where capture is fully automated and improvement is always a deliberate human act.
Every thumbs rating freezes a complete reproducible example - the rated output, the exact inputs that produced it, and the producing prompt's version hash - so a thumbs-down is a ready-made regression test case, not an anecdote.
The system prompt never changes on its own.
The full design, stages, and implementation map live in `COACH_QUALITY.md`; this ADR records the decision and its rejected alternatives for the index.

## Considered Options

- **Pipe ratings into the live context** ("she disliked yesterday's note") - rejected: invites approval-chasing and churn, the exact failure the anti-churn posture guards against.
- **Auto-regenerate on a thumbs-down** - rejected: the rating is captured, not acted on in-session.
- **Let the system edit its own prompts** - rejected: unsupervised drift in the coach's voice is a real risk taken to save a minutes-per-month human task.
- **Fine-tune on the labelled set** - rejected: at household volume the set can test prompts; it cannot train weights.
- **Automated capture + human-initiated improvement** - chosen: at household scale, human-in-the-loop is the feature, not the compromise.

## Consequences

- Frozen provenance makes prompt editing red-green: replay the accumulated negative cases through a candidate prompt (`pytest -m eval`), hold thumbs-up anchors as anti-regression, ship only when both pass.
- Dismiss reasons on proposals split preference from quality bugs (see ADR 0006), keeping the eval-case stream clean.
- Personalization has exactly one path to the live prompt: a recurring preference distilled into one human-reviewed line of the athlete's `style_prompt`.
- The automation question gets revisited only if manual review becomes impractical (~50+ users of daily feedback).
