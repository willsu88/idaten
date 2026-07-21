"""LLM token/cost accounting (app/usage.py) + the admin usage endpoint."""

from __future__ import annotations

from app import usage
from app.models import LlmUsage, User

from conftest import make_user


def test_cost_uses_per_component_rates():
    u = usage.Usage(input_tokens=1000, output_tokens=500,
                    cache_read_tokens=200, cache_creation_tokens=100)
    # 1000*15 + 500*75 + 200*1.5 + 100*18.75 = 54675, /1e6
    assert usage.cost_usd("claude-opus-4-8", u) == round(54675 / 1_000_000, 6)


def test_rates_match_prefix_then_default():
    # A version-suffixed model still matches its family by prefix.
    assert usage._rates("claude-opus-4-8-20250101") is usage.PRICES["claude-opus-4-8"]
    # An unknown model falls back to the default rate card (cost still computed).
    assert usage._rates("mystery-model-9") is usage.PRICES["_DEFAULT"]


def test_record_writes_a_row_and_skips_unattributed(db):
    make_user(db, "will", "secret1")  # user id 1
    usage.record("anthropic", "claude-opus-4-8",
                 usage.Usage(input_tokens=100, output_tokens=50), user_id=1, call_site="chat")
    usage.record("anthropic", "claude-opus-4-8",
                 usage.Usage(input_tokens=999), user_id=None, call_site="chat")  # no-op

    db.expire_all()
    rows = db.query(LlmUsage).all()
    assert len(rows) == 1
    assert rows[0].call_site == "chat" and rows[0].input_tokens == 100
    assert rows[0].cost_usd > 0


def _admin(db, client):
    u = make_user(db, "will", "secret1")
    u.is_admin = True
    db.commit()
    client.post("/api/auth/login", json={"username": "will", "password": "secret1"})
    return u


def test_usage_endpoint_aggregates_by_user_and_call_site(db, client):
    admin = _admin(db, client)
    db.add_all([
        LlmUsage(user_id=admin.id, provider="anthropic", model="claude-opus-4-8",
                 call_site="chat", input_tokens=100, output_tokens=50,
                 cache_read_tokens=900, cost_usd=0.01),
        LlmUsage(user_id=admin.id, provider="anthropic", model="claude-opus-4-8",
                 call_site="plan", input_tokens=200, output_tokens=80, cost_usd=0.02),
    ])
    db.commit()

    body = client.get("/api/auth/usage").json()
    assert body["total"]["calls"] == 2
    assert round(body["total"]["cost_usd"], 2) == 0.03
    # cache_read 900 of (100+200 non-cached + 900 cached) input -> 900/1200 = 75%
    assert body["total"]["cache_hit_pct"] == 75.0
    assert {s["call_site"] for s in body["by_call_site"]} == {"chat", "plan"}
    assert body["by_user"][0]["name"] == "Will"


def test_usage_endpoint_is_admin_only(db, client):
    _admin(db, client)
    # A non-admin invitee (accepting logs them in) must not read usage.
    path = client.post("/api/auth/invites").json()["path"]
    token = path.rsplit("/", 1)[1]
    client.post(f"/api/auth/invites/{token}/accept",
                json={"username": "gf", "password": "secret2"})
    assert client.get("/api/auth/usage").status_code == 403
