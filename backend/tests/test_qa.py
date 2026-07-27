"""Nightly coach QA scorecards (ADR 0016, .scratch/coach-qa-scorecards).

Seams under test (agreed at spec time):
- the provider seam: `qa.make_client` stubbed, judge verdicts scripted
- the job functions called directly against a seeded world
- GET /api/qa/summary (admin payload) and GET /api/chat/history (no tool rows)

Everything here is deterministic; judge *quality* is layer 3-4 territory
(test_evals.py, `pytest -m eval`).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app import instance_settings, qa
from app.chat import agent as chat_agent
from app.config import config
from app.llm import Response, ToolCall
from app.models import ChatMessage, QaScore
from app.settings_store import get_settings

# A fixed "now": far enough from any midnight in the household zone that
# before/after fixtures can't straddle a boundary.
NOW = dt.datetime(2026, 7, 27, 12, 0, tzinfo=qa._TZ).astimezone(
    dt.timezone.utc).replace(tzinfo=None)
MIDNIGHT = qa._local_midnight_utc(NOW)
YESTERDAY = MIDNIGHT - dt.timedelta(hours=6)
TODAY = MIDNIGHT + dt.timedelta(hours=2)


def _msg(db, user_id: int, sid: str, role: str, content: str, at: dt.datetime,
         kind: str = "text", payload=None, pv: str | None = None) -> ChatMessage:
    m = ChatMessage(user_id=user_id, session_id=sid, role=role, content=content,
                    kind=kind, payload=payload, prompt_version=pv, created_at=at)
    db.add(m)
    db.commit()
    return m


def _seed_session(db, user_id: int, sid: str = "s1", at: dt.datetime = YESTERDAY,
                  pv: str = "abc123def456") -> None:
    _msg(db, user_id, sid, "user", "how was my week?", at - dt.timedelta(minutes=2))
    _msg(db, user_id, sid, "tool", "", at - dt.timedelta(minutes=1), kind="tool_call",
         payload={"name": "get_week", "args": {}, "result": '{"km": 42.0}'}, pv=pv)
    _msg(db, user_id, sid, "assistant", "You ran 42km.", at, pv=pv)


class StubJudge:
    """Scripted verdicts, keyed by rubric item order of arrival."""

    def __init__(self, verdicts: list[dict]):
        self.verdicts = list(verdicts)
        self.calls: list[str] = []  # criteria text per call

    def complete_structured(self, system, messages, schema, name):
        self.calls.append(messages[0]["content"])
        return self.verdicts[len(self.calls) - 1]


PASS = {"applicable": True, "passed": True, "reason": "grounded"}
FAIL = {"applicable": True, "passed": False, "reason": "stated a figure no tool returned"}
NA = {"applicable": False, "passed": False, "reason": "never arose"}


def _stub(monkeypatch, stub: StubJudge) -> None:
    monkeypatch.setattr(qa, "make_client", lambda provider=None, **_kw: stub)


# --- rubric version -------------------------------------------------------------

def test_rubric_version_is_stable_and_content_sensitive(monkeypatch):
    v1 = qa.rubric_version()
    assert v1 == qa.rubric_version() and len(v1) == 12
    changed = (qa.RubricItem(key="grounded_data", call_sites=("chat",),
                             criteria="different bar"),)
    monkeypatch.setattr(qa, "RUBRIC", changed)
    assert qa.rubric_version() != v1


# --- gradeability ---------------------------------------------------------------

def test_only_quiet_since_midnight_sessions_are_gradeable(db, user):
    _seed_session(db, user.id, "quiet", at=YESTERDAY)
    _seed_session(db, user.id, "active", at=TODAY)
    assert qa.gradeable_sessions(db, NOW) == [(user.id, "quiet")]


def test_straddling_session_waits_for_its_last_message(db, user):
    # Started yesterday, last message after midnight: not gradeable tonight.
    _seed_session(db, user.id, "straddle", at=YESTERDAY)
    _msg(db, user.id, "straddle", "user", "one more thing", TODAY)
    assert qa.gradeable_sessions(db, NOW) == []


def test_scored_session_is_done_until_it_resumes(db, user, monkeypatch):
    _seed_session(db, user.id, "s1", at=YESTERDAY)
    _stub(monkeypatch, StubJudge([PASS, PASS, NA]))
    qa.judge_session(db, user.id, "s1")
    assert qa.gradeable_sessions(db, NOW) == []
    # Pin scored_at into the fixture timeline (judge_session stamps real now).
    for r in db.scalars(select(QaScore)).all():
        r.scored_at = YESTERDAY + dt.timedelta(hours=1)
    db.commit()
    # Resumption: new message after scoring; once quiet again -> re-gradeable.
    _msg(db, user.id, "s1", "user", "actually...", TODAY)
    later = NOW + dt.timedelta(days=1)
    assert qa.gradeable_sessions(db, later) == [(user.id, "s1")]


# --- judging: verdicts, stamps, upsert ------------------------------------------

def test_judge_session_writes_stamped_three_valued_verdicts(db, user, monkeypatch):
    _seed_session(db, user.id, "s1", at=YESTERDAY, pv="abc123def456")
    stub = StubJudge([FAIL, PASS, NA])
    _stub(monkeypatch, stub)
    assert qa.judge_session(db, user.id, "s1") == 3

    rows = db.scalars(select(QaScore).order_by(QaScore.rubric_key)).all()
    by_key = {r.rubric_key: r for r in rows}
    assert by_key["grounded_data"].verdict == "fail"
    assert by_key["grounded_data"].reason == FAIL["reason"]
    assert by_key["honest_about_edits"].verdict == "pass"
    assert by_key["concrete_when_asked"].verdict == "na"
    for r in rows:
        assert r.call_site == "chat" and r.artifact_ref == "s1"
        assert r.prompt_version == "abc123def456"
        assert r.rubric_version == qa.rubric_version()
        assert r.judge_model == config.judge_model
        assert r.artifact_date == qa._as_local_date(YESTERDAY)
    # The judge saw the tool ground truth, not just the prose.
    assert '{"km": 42.0}' in stub.calls[0]


def test_judge_calls_never_run_inside_a_write_transaction(db, user, monkeypatch):
    """Each judge call is tens of seconds and SQLite has one write lock: a
    flushed-but-uncommitted upsert held across a judge call starves every live
    chat writer with "database is locked" (production incident, 2026-07-27)."""
    _seed_session(db, user.id, "s1", at=YESTERDAY)

    class TxnProbe:
        def __init__(self):
            self.in_txn: list[bool] = []

        def complete_structured(self, system, messages, schema, name):
            raw = db.connection().connection.dbapi_connection
            self.in_txn.append(raw.in_transaction)
            return PASS

    probe = TxnProbe()
    _stub(monkeypatch, probe)
    qa.judge_session(db, user.id, "s1")
    assert probe.in_txn == [False, False, False]


def test_rejudge_upserts_one_living_verdict_per_item(db, user, monkeypatch):
    _seed_session(db, user.id, "s1", at=YESTERDAY)
    _stub(monkeypatch, StubJudge([FAIL, FAIL, FAIL]))
    qa.judge_session(db, user.id, "s1")
    _stub(monkeypatch, StubJudge([PASS, PASS, PASS]))
    qa.judge_session(db, user.id, "s1")
    rows = db.scalars(select(QaScore)).all()
    assert len(rows) == 3 and all(r.verdict == "pass" for r in rows)


# --- the nightly job ------------------------------------------------------------

def _seed_job_session(db, user_id: int, sid: str = "j1") -> None:
    """A session quiet since yesterday relative to REAL now (qa_job's clock)."""
    at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=1)
    _seed_session(db, user_id, sid, at=at)


def test_qa_job_scores_everything_then_is_idempotent(db, user, monkeypatch):
    _seed_job_session(db, user.id)
    stub = StubJudge([PASS, PASS, NA])
    _stub(monkeypatch, stub)
    assert qa.qa_job() == {"scored_sessions": 1, "verdicts": 3, "disabled": False}
    assert qa.qa_job() == {"scored_sessions": 0, "verdicts": 0, "disabled": False}
    assert len(stub.calls) == 3  # the re-run made zero judge calls


def test_qa_job_toggled_off_never_calls_the_judge_or_backfills(db, user, monkeypatch):
    _seed_job_session(db, user.id)
    stub = StubJudge([PASS, PASS, PASS])
    _stub(monkeypatch, stub)
    instance_settings.set_call_site_enabled(db, "qa", False)
    assert qa.qa_job()["disabled"] is True
    assert stub.calls == []
    # Forward-only resume: the disabled run advanced the skip watermark, so
    # re-enabling never backfills the night it deliberately skipped.
    instance_settings.set_call_site_enabled(db, "qa", True)
    assert qa.qa_job()["scored_sessions"] == 0
    assert stub.calls == []


def test_skipped_session_regains_gradeability_only_by_resuming(db, user):
    _seed_session(db, user.id, "s1", at=YESTERDAY)
    # A disabled nightly run stamped tonight's midnight as the watermark.
    instance_settings.put_value(db, qa._SKIP_WATERMARK_KEY, MIDNIGHT.isoformat())
    assert qa.gradeable_sessions(db, NOW) == []
    # Resumption moves the session's last message past the watermark; once the
    # session is quiet again it is judged in full - nothing stays half-skipped.
    _msg(db, user.id, "s1", "user", "actually...", TODAY)
    assert qa.gradeable_sessions(db, NOW + dt.timedelta(days=1)) == [(user.id, "s1")]


def test_a_missed_night_is_caught_up(db, user, monkeypatch):
    # Downtime, not a toggle: the job simply never ran, so no watermark was
    # written and the two-day-old quiet session is still due.
    _seed_session(db, user.id, "old", at=YESTERDAY - dt.timedelta(days=2))
    assert qa.gradeable_sessions(db, NOW) == [(user.id, "old")]
    _stub(monkeypatch, StubJudge([PASS, PASS, NA]))
    assert qa.qa_job() == {"scored_sessions": 1, "verdicts": 3, "disabled": False}


def test_one_poisoned_session_does_not_kill_the_rest(db, user, monkeypatch):
    _seed_job_session(db, user.id, "bad")
    _seed_job_session(db, user.id, "good")

    class ExplodingThenFine:
        """First judge call (session "bad") explodes; the rest pass."""

        def __init__(self):
            self.n = 0

        def complete_structured(self, system, messages, schema, name):
            self.n += 1
            if self.n <= 1:
                raise RuntimeError("provider hiccup")
            return PASS

    shared = ExplodingThenFine()
    monkeypatch.setattr(qa, "make_client", lambda provider=None, **_kw: shared)
    out = qa.qa_job()
    assert out["scored_sessions"] == 1 and out["verdicts"] == 3


# --- summary: n/a exclusion, version grouping, regression -----------------------

def _score(db, user_id: int, sid: str, key: str, verdict: str, pv: str,
           when: dt.datetime, date: dt.date | None = None) -> None:
    db.add(QaScore(user_id=user_id, call_site="chat", artifact_ref=sid,
                   rubric_key=key, verdict=verdict, reason="r" if verdict == "fail" else "",
                   prompt_version=pv, rubric_version="rv1", judge_model="m",
                   scored_at=when, artifact_date=date or qa._as_local_date(when)))
    db.commit()


def test_pass_rate_excludes_na_from_the_denominator(db, user):
    t = NOW - dt.timedelta(days=1)
    for i, v in enumerate(["pass", "pass", "fail", "na", "na"]):
        _score(db, user.id, f"s{i}", "grounded_data", v, "v1", t + dt.timedelta(minutes=i))
    item = next(i for i in qa.qa_summary(db)["items"] if i["key"] == "grounded_data")
    (ver,) = item["versions"]
    assert ver == {"prompt_version": "v1", "pass": 2, "fail": 1, "na": 2,
                   "pass_rate": 2 / 3}


def test_regression_needs_a_drop_and_five_applicable(db, user):
    t = NOW - dt.timedelta(days=10)
    for i in range(6):  # old version: 6/6
        _score(db, user.id, f"old{i}", "grounded_data", "pass", "v1",
               t + dt.timedelta(minutes=i))
    for i, v in enumerate(["pass", "pass", "pass", "fail", "fail"]):  # new: 3/5
        _score(db, user.id, f"new{i}", "grounded_data", v, "v2",
               t + dt.timedelta(days=5, minutes=i))
    # Same drop on another item but only 4 applicable: stays quiet.
    for i, v in enumerate(["pass", "pass", "pass", "pass"]):
        _score(db, user.id, f"o{i}", "honest_about_edits", v, "v1",
               t + dt.timedelta(minutes=i))
    for i, v in enumerate(["pass", "pass", "pass", "fail"]):
        _score(db, user.id, f"n{i}", "honest_about_edits", v, "v2",
               t + dt.timedelta(days=5, minutes=i))

    items = {i["key"]: i for i in qa.qa_summary(db)["items"]}
    assert items["grounded_data"]["regression"] is True
    assert [v["prompt_version"] for v in items["grounded_data"]["versions"]] == ["v1", "v2"]
    assert items["honest_about_edits"]["regression"] is False


def test_summary_buckets_by_artifact_week_and_lists_fails_newest_first(db, user):
    monday = dt.date(2026, 7, 20)
    _score(db, user.id, "a", "grounded_data", "fail", "v1",
           NOW - dt.timedelta(days=3), date=monday + dt.timedelta(days=2))
    _score(db, user.id, "b", "grounded_data", "fail", "v1",
           NOW - dt.timedelta(days=1), date=monday + dt.timedelta(days=5))
    out = qa.qa_summary(db)
    item = next(i for i in out["items"] if i["key"] == "grounded_data")
    week = next(w for w in item["weeks"] if w["week_start"] == monday.isoformat())
    assert week["fail"] == 2
    assert [f["session_id"] for f in out["recent_fails"]] == ["b", "a"]
    assert out["recent_fails"][0]["reason"] == "r"
    assert out["rubric_version"] == qa.rubric_version()


# --- chat side: provenance stamps and tool persistence --------------------------

def test_chat_prompt_version_ignores_daily_data_but_sees_style(db, user):
    settings = get_settings(db, user.id)
    v1 = chat_agent.chat_prompt_version(settings)
    assert v1 == chat_agent.chat_prompt_version(dict(settings))
    chill = dict(settings, coach_style="chill")
    assert chat_agent.chat_prompt_version(chill) != v1


class ToolThenTextStub:
    """Round 1: one tool call. Round 2: final text."""

    def __init__(self):
        self.round = 0

    def stream(self, system, messages, tools, on_text):
        self.round += 1
        if self.round == 1:
            return Response(content=None, tool_calls=[
                ToolCall(id="t1", name="get_week", args={"n": 1})])
        on_text("You ran 42km this week.")
        return Response(content="You ran 42km this week.")


def test_run_chat_persists_tool_calls_stamped_and_replay_skips_them(db, user, monkeypatch):
    monkeypatch.setattr(chat_agent, "make_client",
                        lambda provider=None, **_kw: ToolThenTextStub())
    monkeypatch.setattr(chat_agent, "dispatch",
                        lambda db_, uid, name, args: ('{"km": 42.0}', None))
    events = list(chat_agent.run_chat(db, user, None, "how far this week?"))
    assert events[-1] == {"type": "done"}

    pv = chat_agent.chat_prompt_version(get_settings(db, user.id))
    tool_row = db.scalars(select(ChatMessage).where(ChatMessage.kind == "tool_call")).one()
    assert tool_row.payload == {"name": "get_week", "args": {"n": 1},
                                "result": '{"km": 42.0}'}
    assert tool_row.prompt_version == pv and tool_row.content == ""
    final = db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant",
                                                 ChatMessage.kind == "text")).one()
    assert final.prompt_version == pv
    # Empty content keeps tool rows out of model history replay.
    history = chat_agent._load_history(db, user.id, tool_row.session_id)
    assert all("42.0" not in m["content"] or m["role"] == "assistant" for m in history)


# --- API: admin summary, toggle key, history filtering --------------------------

def _login(client, username="will", password="secret1"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def test_qa_summary_endpoint_is_admin_only(db, user, client):
    _login(client)
    assert client.get("/api/qa/summary").status_code == 403
    user.is_admin = True
    db.commit()
    body = client.get("/api/qa/summary").json()
    assert body["judge_model"] == config.judge_model
    assert body["enabled"] is True
    assert {i["key"] for i in body["items"]} == {i.key for i in qa.RUBRIC}


def test_coach_toggles_include_qa(db, user, client):
    user.is_admin = True
    db.commit()
    _login(client)
    assert client.get("/api/auth/coach_toggles").json()["qa"] is True
    out = client.put("/api/auth/coach_toggles", json={"qa": False}).json()
    assert out["qa"] is False and out["weekly_summary"] is True


def test_chat_history_endpoint_hides_tool_rows(db, user, client):
    _seed_session(db, user.id, "s1", at=YESTERDAY)
    _login(client)
    kinds = [m["kind"] for m in client.get("/api/chat/history",
                                           params={"session_id": "s1"}).json()]
    assert "tool_call" not in kinds and len(kinds) == 2
