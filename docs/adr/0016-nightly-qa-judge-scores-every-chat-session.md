# Production QA is the eval judge run nightly over every chat session

The eval harness's fail-closed LLM judge (`backend/tests/test_evals.py`) is promoted from CI-only to continuous: a nightly scheduler job scores 100% of coach chat sessions against a behavioral rubric and stores one verdict row per (session, rubric item).
The unit of judgment is the whole session, addressed the way everything else is addressed - `(call_site, artifact_ref)` - so the same machinery later extends to reviews, plans, and summaries without a schema change.
A session is gradeable once it has been quiet since local midnight; a session that resumes is re-judged in full and its verdicts upserted, so scores always describe the complete transcript.

Three stamps make every score row interpretable forever: `prompt_version` (hash of the hand-written system template plus the athlete's style line, stamped at generation time, never the hydrated prompt - hashing pasted-in daily data would mint a unique version per user per day and make version grouping meaningless), `rubric_version` (hash of the rubric module), and `judge_model`.
Verdicts are three-valued - pass, fail, n/a - and n/a is excluded from every pass-rate denominator, matching how both human-graded and automated QM scorecards handle inapplicable criteria.
The judge runs on a different provider than the coach (`judge_provider` / `judge_model` config, default `gpt-5.4-mini` through the ADR 0005 seam) to break LLM self-preference bias: the defendant's family does not sit on the jury.
The judge reads the full transcript plus tool results - which requires production chat to start persisting tool calls as `ChatMessage` rows - because grounding claims can only be verified against what the tools actually returned.

## Considered Options

- **Sample sessions instead of scoring all** - rejected: at household volume the whole point is affordable totality; 100% coverage costs cents per month and "every conversation was checked" is the product.
- **Human thumbs in chat instead of a machine judge** - rejected: already ruled out by the flight-recorder design (ADR 0014); per-message ratings are noise, and chat would stay the least-observed surface.
- **Same-provider judge (Haiku)** - rejected: self-preference bias is documented for LLM-as-judge, and at this volume the cross-provider option costs nothing extra.
- **One judge call grading all rubric items at once** - rejected: splitting attention across criteria degrades per-item reliability and a malformed response loses the whole session; one call per (session, item) keeps the judge maximally dumb, and cost is noise.
- **Hash the rendered system prompt** - rejected: chat hydrates daily data into the prompt, so the rendered hash is unique per session and cannot group scores by prompt revision.
- **Compute prompt version at scoring time** - rejected: attributes every session to whatever is deployed tonight, i.e. wrong exactly when a deploy just happened.
- **Rubric in the database, editable from the admin UI** - rejected: no-deploy editing is an anti-feature for behavior-defining text; it forfeits git's free version history and demands hand-built scorecard versioning, which QM vendors only build because their editors are non-engineers.
- **Calendar-sliced grading of straddling sessions** - rejected: cuts conversational context at an arbitrary midnight; a claim at 23:50 contradicted at 00:10 must be judged together.
- **Fold n/a into pass** - rejected: vacuous passes dilute the denominator until real failures vanish into it; the industry norm is n/a excluded from the potential score.
- **Nightly whole-session judging with three-valued verdicts and triple version stamps** - chosen.

## Consequences

- Prompt editing gains the missing confirmation step: a deploy mints a new `prompt_version` column in the version-grouped admin view, and whether the fix held becomes visible as sessions accumulate - before this, a prompt edit shipped on hope.
- Conversation transcripts and tool results (training and health data) are sent to the judge provider under its API terms; the exposure is deliberate, documented in `COACH_QUALITY.md`, and the lever is one config key.
- Judge verdicts and member feedback stay structurally distinct (score rows vs `feedback` rows) and meet only on `artifact_ref`, so provenance can never be confused; disagreement between them is the future judge-calibration signal.
- The judge's own quality is unverified at launch: a fail-closed mini-tier model will produce some false fails, and nothing measures its recall until member reports exist to compare against.
- Changing the rubric or the judge model resets what the trend lines mean; the stamps make the discontinuity queryable but nothing makes it painless.
- Re-judging resumed sessions means yesterday's aggregate can shift in hindsight; the invariant chosen is "scores describe the full transcript", not "scores are immutable".
- At ~9 sessions a week no statistical drift detection is honest; the view is version-grouped counts with visible denominators and a minimum-sample highlight, and anything fancier waits for volume that earns it.
- The nightly job rides the ADR 0011 scheduler, its spend lands in `llm_usage` under `call_site='qa'`, and it is toggleable as a third instance-level call-site toggle (ADR 0003).
