"""The chat agent loop — provider-blind, streaming, event-emitting.

Same loop as practice-two: neutral (OpenAI-shaped) history, `client.stream()`
per round, dispatch tool calls, feed results back, repeat until the model stops
asking for tools. Instead of printing, each step yields an event dict that the
API layer serializes as SSE:

    {"type": "text", "delta": ...}
    {"type": "tool", "name": ..., "status": "running" | "done"}
    {"type": "edit_proposed", "edit": {...}}
    {"type": "done"} / {"type": "error", "message": ...}
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import queue
import threading
import uuid
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import metrics, rate_limit
from .. import niggles as niggles_mod
from ..llm import make_client
from ..models import ChatMessage, PendingEdit, User
from ..settings_store import get_settings
from .tools import TOOL_SCHEMAS, dispatch, edit_dict

log = logging.getLogger(__name__)


class ChatStopped(Exception):
    """The athlete pressed stop — end the turn, keep the partial reply."""

MAX_TOOL_ROUNDS = 6  # a real turn uses ~3 (data tools -> propose -> reply), or
                     # ~5 with a pace-guard retry; 6 caps runaway loops with margin
HISTORY_LIMIT = 30  # most recent messages replayed into context

# How a proposal's stored status reads to the model when its marker is replayed.
# Without this the model can't tell a live proposal from a dead one, so it treats
# dismissed/superseded proposals as still pending — refusing to re-propose, or
# narrating a proposal it never actually created.
_EDIT_STATUS_NOTE = {
    "pending": "PENDING — awaiting the athlete's approval in the app",
    "accepted": "ACCEPTED and applied to the plan",
    "dismissed": "DISMISSED by the athlete — no longer live; re-propose if the "
                 "change is still wanted",
    "superseded": "SUPERSEDED by a newer proposal — no longer live",
}

SYSTEM_TEMPLATE = """\
You are {name}'s personal running coach inside their training app, which syncs
their Garmin data (activities, sleep, HRV, body battery) and maintains a rolling
7-day training plan toward their race goal.

You are coaching {name}, and {name} alone. Every tool result and every number
below is {name}'s own data — address them as {name}. If they refer to themselves
by another name, or ask you for another person's plan or data, do NOT adopt that
name or role-play as that person: you only have access to {name}'s data, so
answer with {name}'s data and, if helpful, note that you can only see their own.

Today is {today}.
Upcoming races (primary is the plan's target; others are tune-ups): {races}
Each race carries the athlete's goal and `garmin_predicted_time_s` (Garmin's own
race predictor). If asked about a likely finish time, you may reference Garmin's
predicted time (call it Garmin's estimate) or the athlete's goal — do NOT invent
or state a separate app/Idaten prediction.
Athlete: {athlete}
Training mode: {training_mode} (pace = pace targets only; hr = HR bands only;
hybrid = HR bands for easy/recovery/long, pace for tempo/intervals/race).
HR zones (bpm, anchored on lactate threshold HR; null if unknown): {hr_zones}
Recent actual paces (computed from synced runs; authoritative): {pace_profile}
Active Garmin Coach plan (null if none; its phase and week number are ground
truth — never treat the athlete as being on week 1 of a plan they're weeks
into): {garmin_plan}
Today's readiness: {readiness}
Active niggles (pain/injury the athlete has reported, still open; none if clear):
{niggles}

Rules:
- Ground every claim about training, recovery, or the plan in tool results — call
  get_training_data / get_current_plan rather than guessing. Never invent numbers.
- When the athlete asks to change their plan (or clearly needs a change, e.g. "I'm
  exhausted", "I'm sick this week"), use propose_plan_edit with specific day-level
  changes. The edit shows up as a diff they must approve — tell them it's waiting
  for their approval; NEVER say the plan is already updated. EVERY plan change goes
  through propose_plan_edit — never describe, summarize, or reprint a proposal card
  as plain text; typing one out does NOT create a real proposal. Proposal markers in
  the history carry a live status: one marked DISMISSED or SUPERSEDED is dead, so if
  the athlete still wants that change (or asks to see the proposal again), call
  propose_plan_edit again to create a fresh one.
- When they mention doing another sport on a day (surfing, hiking, freediving...)
  or being unavailable, use set_day_intent for that day (this applies immediately),
  then propose_plan_edit to rebalance the surrounding days — e.g. move a long run
  away from the morning after a hard hike, and account for the sport's load.
- When the athlete mentions pain, soreness, or an injury ("my knee hurts", "my
  achilles has been tight since Tuesday"), call log_niggle so it persists — the
  daily review will protect it until it clears. When they say a logged issue is
  better ("the knee's fine now"), call resolve_niggle with its id from the
  active-niggles list above. While anything is open, coach around it: ease or
  move hard work off a painful area (propose_plan_edit), and never green-light
  pushing through real pain. You are a coach, not a clinician — for severity-3
  or persistent pain, advise seeing a professional rather than diagnosing.
- Plan days can carry structured `steps` (blocks of warmup/work/recovery/cooldown;
  repeat blocks for interval sets, e.g. 6 x [800m work, 400m float]). When you
  propose a tempo/interval/long session, include concrete steps consistent with the
  day-level summary and the athlete's training mode; simple easy/rest days use null.
- Every pace you prescribe or discuss must be grounded in the athlete's actual
  recent paces above and their race goal pace — never in generic tables. Easy
  runs go at or SLOWER than their typical pace; quality work progresses gradually
  from recent actual paces toward goal pace. Ungrounded-fast proposals are
  rejected automatically by a pace guard.
- Be a good coach: explain the why behind workouts, reference their actual data,
  push back when a request would hurt them (e.g. cramming intensity before a race),
  and keep answers concise and concrete.
"""


def _chat_race(r_dict: dict) -> dict:
    """Race view for the coach. Garmin's own predicted time is allowed context,
    but Idaten's generated prediction (the calibrated `likely_s` range) is
    WITHHELD — the coach must not cite a number the app deliberately hides (see
    frontend lib/flags SHOW_RACE_PREDICTION). Only the goal and Garmin's predictor
    survive; the coach grounds pacing in the goal + recent actual paces."""
    p = r_dict.get("prediction") or {}
    out = {k: v for k, v in r_dict.items() if k != "prediction"}
    out["goal_time_s"] = p.get("goal_time_s")
    out["goal_pace"] = p.get("goal_pace")
    out["garmin_predicted_time_s"] = p.get("garmin_time_s")  # Garmin's race predictor, not ours
    return out


def _system_prompt(db: Session, user: User) -> str:
    from ..garmin.training_plan import garmin_plan_context
    from ..planner import _athlete_block, _hr_zones, style_prompt
    from ..races import prediction_context, race_dict, upcoming_races

    today = dt.date.today()
    settings = get_settings(db, user.id)
    readiness = metrics.readiness(db, user.id, today)
    ctx = prediction_context(db, user.id, today)
    races = [_chat_race(race_dict(r, ctx)) for r in upcoming_races(db, user.id)]
    return SYSTEM_TEMPLATE.format(
        name=user.display_name or "the athlete",
        today=today.isoformat(),
        races=json.dumps(races) if races else "none set",
        athlete=json.dumps(_athlete_block(db, user.id, settings)),
        training_mode=settings.get("training_mode"),
        hr_zones=json.dumps(_hr_zones(db, user.id)),
        pace_profile=json.dumps(metrics.pace_profile(db, user.id, today)),
        garmin_plan=json.dumps(garmin_plan_context(db, user.id, today)),
        readiness=json.dumps(readiness) if readiness else "no data yet",
        niggles=json.dumps(niggles_mod.active_niggles(db, user.id, today) or "none"),
    ) + style_prompt(settings)


def _load_history(db: Session, user_id: int, session_id: str) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user_id, ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_LIMIT)
    ).all()
    # edit_proposed rows carry a plain-text fallback in content, so replaying
    # them as ordinary messages keeps the model's view of the conversation sane.
    # Shortcut/context messages store what the model should see in payload
    # ("llm_text"); content stays the raw text the user typed.
    out = []
    for r in reversed(rows):
        content = (r.payload or {}).get("llm_text") or r.content
        if not content:
            continue
        # Stamp proposal markers with the edit's CURRENT status so the model knows
        # which proposals are still live and which are dead (dismissed/superseded).
        if r.kind == "edit_proposed" and (r.payload or {}).get("edit_id"):
            edit = db.get(PendingEdit, r.payload["edit_id"])
            if edit is not None:
                note = _EDIT_STATUS_NOTE.get(edit.status, edit.status)
                content += f" [status: {note}]"
        out.append({"role": r.role, "content": content})
    return out


def run_chat(db: Session, user: User, session_id: str | None, user_message: str,
             llm_text: str | None = None, kind: str = "text",
             stream_gen: int = 0) -> Iterator[dict]:
    """Run one chat turn; yields SSE-ready event dicts.

    `user_message` is persisted and displayed verbatim; `llm_text` (shortcut
    expansion / context-date prefix) is what enters the model-facing history.
    `stream_gen` is this stream's rate_limit generation token — cancel checks
    are scoped to it so a stale stop never kills a newer stream.
    """
    from ..planner import strip_em_dashes

    session_id = session_id or uuid.uuid4().hex
    yield {"type": "session", "session_id": session_id}

    llm_text = llm_text or user_message
    settings = get_settings(db, user.id)
    client = make_client(settings.get("llm_provider"), user_id=user.id, call_site="chat")
    system = _system_prompt(db, user)
    messages = _load_history(db, user.id, session_id)
    messages.append({"role": "user", "content": llm_text})
    db.add(ChatMessage(user_id=user.id, session_id=session_id, role="user",
                       content=user_message, kind=kind,
                       payload={"llm_text": llm_text} if llm_text != user_message else None))
    db.commit()

    round_texts: list[str] = []  # one entry per LLM round, joined with blank lines
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            if rate_limit.cancel_requested(user.id, stream_gen):
                raise ChatStopped()
            # Separate this round's text from the previous round's, live and in
            # the persisted transcript (fixes "first.Taking" run-together text).
            if round_texts and round_texts[-1].strip():
                yield {"type": "text", "delta": "\n\n"}
            round_texts.append("")
            # Bridge the client's on_text callback into this generator via a queue:
            # a worker thread runs the LLM round, deltas stream out as events.
            # Raising ChatStopped inside on_text aborts the provider stream at the
            # next delta (the SDK context manager closes the connection), so a
            # stop actually halts token spend, not just the UI.
            q: queue.Queue = queue.Queue()
            result: dict[str, Any] = {}

            def on_text(t: str) -> None:
                if rate_limit.cancel_requested(user.id, stream_gen):
                    raise ChatStopped()
                q.put(t)

            def worker() -> None:
                try:
                    result["response"] = client.stream(
                        system, messages, TOOL_SCHEMAS, on_text=on_text
                    )
                except Exception as e:  # noqa: BLE001
                    result["error"] = e
                finally:
                    q.put(None)  # sentinel

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            while (delta := q.get()) is not None:
                # Strip em-dashes live so the streamed text (and the history built
                # from round_texts) never shows an AI tell.
                delta = strip_em_dashes(delta)
                round_texts[-1] += delta
                yield {"type": "text", "delta": delta}
            t.join()

            if "error" in result:
                raise result["error"]
            resp = result["response"]

            # Append the assistant turn in neutral shape
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": resp.content}
            if resp.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                    }
                    for tc in resp.tool_calls
                ]
            messages.append(assistant_msg)

            if resp.is_final:
                break

            for tc in resp.tool_calls:
                if rate_limit.cancel_requested(user.id, stream_gen):
                    raise ChatStopped()
                yield {"type": "tool", "name": tc.name, "status": "running"}
                tool_result, pending_edit = dispatch(db, user.id, tc.name, tc.args)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": tool_result}
                )
                yield {"type": "tool", "name": tc.name, "status": "done"}
                if pending_edit is not None:
                    # Persist the proposal marker so history reloads re-render the
                    # diff card (with its *current* status) instead of losing it.
                    db.add(ChatMessage(
                        user_id=user.id, session_id=session_id, role="assistant",
                        kind="edit_proposed", payload={"edit_id": pending_edit.id},
                        content=f"[Proposed plan edit #{pending_edit.id}: {pending_edit.summary}]",
                    ))
                    db.commit()
                    yield {"type": "edit_proposed", "edit": edit_dict(pending_edit)}
        else:
            log.warning("chat hit MAX_TOOL_ROUNDS for session %s", session_id)

        final = "\n\n".join(t.strip() for t in round_texts if t.strip())
        db.add(ChatMessage(user_id=user.id, session_id=session_id, role="assistant",
                           content=final))
        db.commit()
        yield {"type": "done"}
    except ChatStopped:
        # Keep whatever the coach already said; tools that already ran stand
        # (safe: plan edits are approval-gated anyway).
        partial = "\n\n".join(t.strip() for t in round_texts if t.strip())
        if partial:
            db.add(ChatMessage(user_id=user.id, session_id=session_id, role="assistant",
                               content=partial, payload={"stopped": True}))
            db.commit()
        yield {"type": "stopped"}
    except Exception as e:  # noqa: BLE001
        log.exception("chat turn failed")
        db.rollback()  # a poisoned flush must not kill later commits (hard-won lesson)
        yield {"type": "error", "message": str(e)}
