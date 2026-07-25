"""Instance-level settings - operator policy for the whole deployment.

First use: the coach call-site toggles (docs/adr/0003, .scratch/coach-toggles).
A self-hosting operator decides which system-initiated coach artifacts their
instance generates and pays for; the switch applies to every member equally,
admin included. Absent = enabled, so existing deployments see no change and
the member-facing settings API (which reads the per-user table) can never see
or write these rows.

A toggle governs LLM generation only - never sync, scoring, plan
materialization, or the serving of artifacts that already exist.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .models import InstanceSetting

# The call sites an operator may turn off. The daily review is deliberately
# absent in v1: it is load-bearing (plan proposals, Garmin plan refresh, the
# Today page anchor) - see the spec's open decision before adding it here.
TOGGLEABLE_CALL_SITES = ("weekly_summary", "execution_analysis")


def toggle_key(call_site: str) -> str:
    return f"coach_{call_site}_enabled"


def put_value(db: Session, key: str, value) -> None:
    db.merge(InstanceSetting(key=key, value=value))
    db.commit()


def call_site_enabled(db: Session, call_site: str) -> bool:
    """Absent = enabled; any falsy stored value (False, 0, "", None) reads as
    disabled, so no writer can accidentally store a value this reads as on."""
    if call_site not in TOGGLEABLE_CALL_SITES:
        raise ValueError(f"not a toggleable call site: {call_site}")
    row = db.get(InstanceSetting, toggle_key(call_site))
    return row is None or bool(row.value)


def set_call_site_enabled(db: Session, call_site: str, enabled: bool) -> None:
    if call_site not in TOGGLEABLE_CALL_SITES:
        raise ValueError(f"not a toggleable call site: {call_site}")
    put_value(db, toggle_key(call_site), bool(enabled))


def coach_toggles(db: Session) -> dict[str, bool]:
    """The full toggle state, for the admin page."""
    return {site: call_site_enabled(db, site) for site in TOGGLEABLE_CALL_SITES}
