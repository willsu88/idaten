"""Nightly coach QA - the eval judge promoted to continuous (ADR 0016).

A scheduled job grades every chat session that has gone quiet against the
rubric below: one fail-closed judge call per (session, rubric item), verdicts
stored as QaScore rows. The judge runs on its own provider/model (config
`judge_provider` / `judge_model`) so the coach is never graded by its own
model family, and it reads the full transcript plus persisted tool calls so
grounding claims are checked against what the tools actually returned.

The rubric lives here, in code, on purpose: it is behavior-defining text, so
it changes the way prompts change - by deploy, with git history - and its hash
is stamped on every score row as `rubric_version`. See COACH_QUALITY.md
("Continuous QA") for how this feeds the quality loop.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import instance_settings
from .config import config
from .db import session
from .llm import make_client
from .models import ChatMessage, QaScore

log = logging.getLogger(__name__)

_TZ = ZoneInfo(config.timezone)


@dataclass(frozen=True)
class RubricItem:
    key: str            # stable identifier stored on score rows
    call_sites: tuple[str, ...]
    criteria: str       # the text the judge grades against


RUBRIC: tuple[RubricItem, ...] = (
    RubricItem(
        key="grounded_data",
        call_sites=("chat",),
        criteria=(
            "Every metric the assistant states (distances, paces, heart rates, "
            "dates, workout details) must appear in, or be directly readable "
            "from, the tool results shown. Fail if the assistant asserts a "
            "specific number or data-backed fact that no tool result supports. "
            "General coaching knowledge that cites no specific personal data "
            "does not fail this item."
        ),
    ),
    RubricItem(
        key="honest_about_edits",
        call_sites=("chat",),
        criteria=(
            "Plan edits go through an approval queue: proposing an edit never "
            "applies it. Fail if the assistant states or implies an edit is "
            "already applied, done, or in effect while it is only proposed or "
            "pending. Saying an edit was proposed and awaits approval passes. "
            "Not applicable if no plan change is discussed."
        ),
    ),
    RubricItem(
        key="concrete_when_asked",
        call_sites=("chat",),
        criteria=(
            "If the user asked for a change to their training plan, the "
            "assistant must either propose a concrete edit (via its edit tool) "
            "or explicitly explain why it declines to. Fail on vague advice "
            "with neither an edit nor a stated refusal. Not applicable if the "
            "user never asked for a plan change."
        ),
    ),
)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "applicable": {"type": "boolean"},
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["applicable", "passed", "reason"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = (
    "You are a strict evaluator of a running-coach assistant's conduct across "
    "one full chat session. Judge ONLY the stated criteria against the "
    "transcript and the tool results (the tool results are ground truth). "
    "Return applicable=false only when the situation the criteria covers never "
    "arose. When applicable and in doubt, return passed=false. In `reason`, "
    "describe the failure or pass in your own words; never quote the user's "
    "messages verbatim."
)


def rubric_version() -> str:
    """Short stable hash of the rubric content - the `rubric_version` stamp.
    Any change to keys or criteria resets what trend lines mean."""
    blob = "\n".join(f"{i.key}|{','.join(i.call_sites)}|{i.criteria}" for i in RUBRIC)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def _local_midnight_utc(now_utc: dt.datetime) -> dt.datetime:
    """Start of today in the household zone, expressed in naive UTC (the form
    SQLite hands datetimes back in)."""
    local_now = now_utc.replace(tzinfo=dt.timezone.utc).astimezone(_TZ)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(dt.timezone.utc).replace(tzinfo=None)


# Forward-only resume (ADR 0003 semantics): a disabled nightly run advances
# this watermark to its midnight, marking everything quiet before it as
# deliberately skipped. A night the job never ran (downtime) leaves the
# watermark alone, so an accidental miss is caught up while a toggled-off
# night is never backfilled.
_SKIP_WATERMARK_KEY = "qa_skipped_until"


def _skip_watermark(db: Session) -> dt.datetime | None:
    raw = instance_settings.get_value(db, _SKIP_WATERMARK_KEY)
    return dt.datetime.fromisoformat(raw) if raw else None


def gradeable_sessions(db: Session, now_utc: dt.datetime | None = None) -> list[tuple[int, str]]:
    """(user_id, session_id) pairs due for judging: quiet since local midnight,
    last active after any skip watermark, and either never scored or resumed
    after their last scoring (re-grade)."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    midnight = _local_midnight_utc(now_utc)
    floor = _skip_watermark(db)
    last_msg = (
        select(
            ChatMessage.user_id,
            ChatMessage.session_id,
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .group_by(ChatMessage.user_id, ChatMessage.session_id)
        .subquery()
    )
    last_scored = (
        select(
            QaScore.artifact_ref,
            func.max(QaScore.scored_at).label("scored_at"),
        )
        .where(QaScore.call_site == "chat")
        .group_by(QaScore.artifact_ref)
        .subquery()
    )
    rows = db.execute(
        select(last_msg.c.user_id, last_msg.c.session_id)
        .join(last_scored, last_scored.c.artifact_ref == last_msg.c.session_id,
              isouter=True)
        .where(
            last_msg.c.last_at < midnight,
            *([last_msg.c.last_at >= floor] if floor is not None else []),
            (last_scored.c.scored_at.is_(None))
            | (last_scored.c.scored_at < last_msg.c.last_at),
        )
        .order_by(last_msg.c.last_at)
    ).all()
    return [(r.user_id, r.session_id) for r in rows]


def _as_local_date(d: dt.datetime) -> dt.date:
    """SQLite hands datetimes back naive UTC; view them as a household-zone date."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(_TZ).date()


def _render_transcript(
    db: Session, user_id: int, session_id: str
) -> tuple[str, str | None, dt.date | None]:
    """The judge's view of one session: turns plus tool ground truth, in order.
    Returns (transcript, prompt_version, artifact_date) - the version from the
    latest stamped row (the instructions that produced the session's last
    assistant turn) and the local date of the last message (the trend axis)."""
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    ).all()
    parts: list[str] = []
    prompt_version: str | None = None
    for r in rows:
        if r.prompt_version:
            prompt_version = r.prompt_version
        if r.kind == "tool_call":
            p = r.payload or {}
            parts.append(
                f"[tool call] {p.get('name')}({json.dumps(p.get('args'), default=str)})\n"
                f"[tool result] {p.get('result')}"
            )
        elif r.content:
            parts.append(f"[{r.role}] {r.content}")
    artifact_date = _as_local_date(rows[-1].created_at) if rows else None
    return "\n\n".join(parts), prompt_version, artifact_date


def judge_one(client, item: RubricItem, transcript: str) -> tuple[str, str]:
    """One fail-closed judge call for one rubric item: (verdict, reason).
    The single choke point both the nightly job and the judge-quality evals go
    through, so they provably grade the same way."""
    result = client.complete_structured(
        system=JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Criteria: {item.criteria}\n\nSession:\n{transcript}",
        }],
        schema=JUDGE_SCHEMA,
        name="qa_verdict",
    )
    if not result.get("applicable", True):
        verdict = "na"
    elif result.get("passed"):
        verdict = "pass"
    else:
        verdict = "fail"
    return verdict, result.get("reason", "")


def judge_session(db: Session, user_id: int, session_id: str) -> int:
    """Judge one session against every applicable rubric item; upsert QaScore
    rows. Returns the number of verdicts written."""
    transcript, prompt_version, artifact_date = _render_transcript(db, user_id, session_id)
    if not transcript:
        return 0
    client = make_client(
        config.judge_provider, user_id=user_id, call_site="qa",
        model=config.judge_model,
    )
    rv = rubric_version()
    # Judge everything BEFORE touching the DB: each judge call is tens of
    # seconds, SQLite has one write lock, and a flushed-but-uncommitted upsert
    # held across a judge call starves every live chat writer ("database is
    # locked", 2026-07-27 incident). The write pass below is milliseconds.
    verdicts = [(item, *judge_one(client, item, transcript))
                for item in RUBRIC if "chat" in item.call_sites]
    written = 0
    for item, verdict, reason in verdicts:
        existing = db.scalars(
            select(QaScore).where(
                QaScore.call_site == "chat",
                QaScore.artifact_ref == session_id,
                QaScore.rubric_key == item.key,
            )
        ).first()
        row = existing or QaScore(
            user_id=user_id, call_site="chat", artifact_ref=session_id,
            rubric_key=item.key,
        )
        row.verdict = verdict
        row.reason = reason
        row.artifact_date = artifact_date
        row.prompt_version = prompt_version
        row.rubric_version = rv
        row.judge_model = config.judge_model
        row.scored_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        if existing is None:
            db.add(row)
        written += 1
    db.commit()
    return written


# The regression highlight needs enough sessions on the new version to mean
# anything; below this it stays quiet (honest denominators, no fake statistics).
MIN_APPLICABLE_FOR_HIGHLIGHT = 5


def _pass_rate(counts: dict) -> float | None:
    """Pass rate over applicable verdicts (n/a excluded); None when nothing
    applicable - the industry-standard N/A treatment."""
    applicable = counts["pass"] + counts["fail"]
    return counts["pass"] / applicable if applicable else None


def qa_summary(db: Session, weeks: int = 8, fails_limit: int = 20) -> dict:
    """Everything the admin QA card renders: per rubric item, weekly counts and
    version-grouped counts (both with explicit denominators), a regression
    highlight, and the recent fails with the judge's reasons."""
    rows = db.scalars(
        select(QaScore).where(QaScore.call_site == "chat")
        .order_by(QaScore.scored_at)
    ).all()

    def bucket() -> dict:
        return {"pass": 0, "fail": 0, "na": 0}

    today = dt.datetime.now(_TZ).date()
    this_monday = today - dt.timedelta(days=today.weekday())
    week_starts = [this_monday - dt.timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]

    items = []
    for item in RUBRIC:
        item_rows = [r for r in rows if r.rubric_key == item.key]
        weekly = {ws: bucket() for ws in week_starts}
        by_version: dict[str, dict] = {}
        version_order: list[str] = []  # by first scored_at (rows are ordered)
        for r in item_rows:
            if r.artifact_date is not None:
                ws = r.artifact_date - dt.timedelta(days=r.artifact_date.weekday())
                if ws in weekly:
                    weekly[ws][r.verdict] += 1
            pv = r.prompt_version or "unknown"
            if pv not in by_version:
                by_version[pv] = bucket()
                version_order.append(pv)
            by_version[pv][r.verdict] += 1

        versions = [{"prompt_version": pv, **by_version[pv],
                     "pass_rate": _pass_rate(by_version[pv])}
                    for pv in version_order]
        regression = False
        if len(versions) >= 2:
            cur, prev = versions[-1], versions[-2]
            cur_applicable = cur["pass"] + cur["fail"]
            if (cur_applicable >= MIN_APPLICABLE_FOR_HIGHLIGHT
                    and cur["pass_rate"] is not None and prev["pass_rate"] is not None
                    and cur["pass_rate"] < prev["pass_rate"]):
                regression = True
        items.append({
            "key": item.key,
            "weeks": [{"week_start": ws.isoformat(), **weekly[ws]} for ws in week_starts],
            "versions": versions,
            "regression": regression,
        })

    fails = [r for r in rows if r.verdict == "fail"][-fails_limit:]
    recent_fails = [{
        "scored_at": r.scored_at.isoformat(),
        "artifact_date": r.artifact_date.isoformat() if r.artifact_date else None,
        "session_id": r.artifact_ref,
        "rubric_key": r.rubric_key,
        "reason": r.reason,
        "prompt_version": r.prompt_version,
    } for r in reversed(fails)]

    return {
        "rubric_version": rubric_version(),
        "judge_model": config.judge_model,
        "enabled": instance_settings.call_site_enabled(db, "qa"),
        "items": items,
        "recent_fails": recent_fails,
    }


def qa_job() -> dict:
    """The nightly run: score everything gradeable. Idempotent - a re-run finds
    nothing gradeable and makes zero judge calls. Toggled off = no judge calls,
    and the skip watermark advances so those sessions are never backfilled on
    re-enable (forward-only); a resumed session re-enters via its new message."""
    db = session()
    try:
        now_utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        if not instance_settings.call_site_enabled(db, "qa"):
            instance_settings.put_value(
                db, _SKIP_WATERMARK_KEY, _local_midnight_utc(now_utc).isoformat())
            log.info("qa: disabled by toggle, skipping")
            return {"scored_sessions": 0, "verdicts": 0, "disabled": True}
        due = gradeable_sessions(db, now_utc)
        scored = verdicts = 0
        for user_id, session_id in due:
            try:
                verdicts += judge_session(db, user_id, session_id)
                scored += 1
            except Exception:  # noqa: BLE001
                log.exception("qa: judging session %s failed", session_id)
                db.rollback()  # a poisoned flush must not kill later sessions
        if due:
            log.info("qa: scored %d sessions (%d verdicts)", scored, verdicts)
        return {"scored_sessions": scored, "verdicts": verdicts, "disabled": False}
    finally:
        db.close()
