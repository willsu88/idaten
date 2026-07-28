# Ticket: BYOB - per-user LLM API keys

Filed 2026-07-27 (deferred repeatedly since 2026-07-20, ROADMAP - dissolved into tickets, see git history). Status: parked - phase 2 of the open-source route.

## The shape (decided direction)

WHO PAYS is a different axis from authorization.
Today one shared instance key funds everyone - correct for the private household (the admin wants to pay for a few friends; usage accounting + the message rate limiter give visibility and a cap).
For open-source, the right eventual shape is hybrid: instance default key (admin's) with an optional per-user override, resolved per-user-with-instance-fallback.

## Constraints

- A stored user key is one more secret: reuse the `app/crypto.py` encrypt-at-rest path (ADR 0013).
- Member model choice unlocks with it: the provider control's gate becomes `is_admin or has_own_key`.
