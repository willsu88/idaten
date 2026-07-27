---
name: diagnose-qa-fail
description: Diagnose a failed nightly QA verdict from the admin Coach QA card - use when given a session id (or its 8-char prefix) and asked why the judge failed it, whether the fail is real, or what to do about it.
---

# Diagnose a QA fail

The admin card shows the verdict and the judge's reason; this skill reconstructs the evidence behind them.
Everything runs inside the container (`docker compose exec -T backend ...`) - never touch `data/garmin_bot.db` from the host.

## Step 1: Pull the verdicts

The card shows an 8-char session id prefix; resolve it and fetch every verdict for the session:

```sh
docker compose exec -T backend python3 -c "
import sqlite3
db = sqlite3.connect('/data/garmin_bot.db')
for r in db.execute('''select artifact_ref, rubric_key, verdict, reason, prompt_version,
                       rubric_version, judge_model, scored_at
                       from qa_scores where artifact_ref like ?||'%' ''', ('PREFIX',)):
    print(r)
"
```

## Step 2: Rebuild the judge's exact view

`qa.render_transcript` returns precisely what the judge graded - turns plus persisted tool results, in order:

```sh
docker compose exec -T backend python3 -c "
from app.db import session
from app import qa
db = session()
t, pv, date = qa.render_transcript(db, USER_ID, 'FULL_SESSION_ID')
print(f'prompt_version={pv} date={date}\n\n{t}')
"
```

If the session was reported by the member, the frozen copy is also in `feedback` (surface `chat_session`) with their comment.

## Step 3: Classify the fail

Check in this order; stop at the first match.

1. **Evidence gap** - the claim the judge flagged references data no `[tool call]` block contains, but the coach plausibly had it another way (system prompt context, earlier session). Real gap in what we render to the judge; fix the renderer or the rubric wording, not the coach.
2. **Judge miss** - the transcript does support the claim and the judge failed it anyway. Add the transcript (anonymized) as a must-pass case in `backend/tests/test_qa_evals.py` (see the `add-eval-case` skill), then tighten `JUDGE_SYSTEM` or the rubric item's criteria.
3. **Real coach failure** - the coach fabricated data, claimed an unapproved edit, or ducked a concrete request. This is the signal working. Fix lives in the chat system prompt (`SYSTEM_TEMPLATE`); the next nightly run scores the new `prompt_version` and the card's version table answers whether it helped.

## Step 4: Record the outcome

- Rubric/criteria change -> it deploys like code; `rubric_version` changes automatically and trend lines reset. Note the why in the commit message.
- Prompt change -> the version table is the record; nothing else to write.
- Pre-instrumentation archaeology: verdicts from before tool-call persistence were purged to `data/qa_preinstrumentation_scores.json` (on the box, not in git) - transcripts for those sessions still render fine via Step 2, but their fails were unfalsifiable; do not re-litigate them.

Never paste member transcripts, health values, or real names into anything committed - findings go in the conversation or gitignored files only.
