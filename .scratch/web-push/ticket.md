# Ticket: web push for the morning coach note

Filed 2026-07-27 (decision from 2026-07-21, ROADMAP Idea C - ROADMAP dissolved into tickets, see git history). Status: parked - explicit revival triggers below.

## The decision (Will, 2026-07-21)

No push channel; eager generation was built instead (the note exists by ~plan_hour+5, Today opens with it ready).
Running before opening the app is very rare for both athletes, which killed the substantive case; engagement alone doesn't justify the infra (service worker + PWA manifest + VAPID keys + subscription lifecycle + iOS add-to-home-screen - all new machinery).

## Revival triggers

Build only if we catch ourselves missing morning notes in practice, or a third user joins who isn't a daily-open user.

## Constraints if revived

- Channel is web push (beat email/Telegram: keeps the app as the only surface).
- One push per day hard cap (the cycle-drift nagging lesson).
- Data-gated with a plan_hour+3h cutoff falling back to a structural-review push.
- Opt-in per user.
