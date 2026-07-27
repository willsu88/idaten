# Ticket: replace raw Garmin calls with upstream library wrappers

Filed 2026-07-27. Status: parked - small cleanup, ~30 min, no product change.

## Context

We audited the Garmin layer for endpoints hit directly instead of through `garminconnect`.
Only two exist, and both now have wrappers in the installed library version (upstream caught up after our workarounds were written).

Decision recorded from the same discussion: no custom SDK, no fork.
`backend/app/garmin/` already serves as our anti-corruption layer; the policy for future gaps is: unblock locally via the public `connectapi()` escape hatch, PR the wrapper upstream (cyberjunky/python-garminconnect accepts these readily), swap on the next version bump.

## The two call sites

1. `backend/app/garmin/races_import.py:55` - `garmin.connectapi(f"/calendar-service/year/{year}/month/{month - 1}")`.
   Replace with `garmin.get_scheduled_workouts(year, month)` - identical URL, and it handles the 0-indexed-month quirk itself (pass the 1-based month, drop our `- 1`).
   Despite the name it returns the full calendar payload; we keep filtering `calendarItems` for races.
2. `backend/app/garmin/gear.py:44` - `_gear_request()` doing a raw `garmin.client.request("PUT", "connectapi", ...)` for gear link/unlink.
   Replace with `garmin.add_gear_to_activity(uuid, activity_id)` / `garmin.remove_gear_from_activity(uuid, activity_id)` and delete `_gear_request`.

## Gotchas (why this is not pure find-and-replace)

- **Version floor**: `requirements.txt` pins `garminconnect>=0.2.19`; the wrappers exist in the installed version but may postdate 0.2.19.
  Find the release that introduced them (check upstream changelog/git blame) and raise the floor accordingly.
- **Behavior parity, gear**: our raw call returns the response as-is; the library methods call `.json()` and raise `GarminConnectConnectionError` on 404 (e.g. retired gear).
  Check `set_activity_gear` in `gear.py` tolerates or exploits that - a retired-shoe unlink mid-swap should not abort the whole swap.
- **Behavior parity, calendar**: `get_scheduled_workouts` validates year/month and raises on bad input where `connectapi` just fired the request.
  `fetch_race_events` already wraps calls in try/except, so this should be fine - verify the except clauses still catch what the wrapper raises (rate-limit path catches `GarminConnectTooManyRequestsError`).

## Done when

- No `connectapi(` or `client.request(` calls remain under `backend/app/garmin/` (grep is the check).
- Version floor raised; backend tests pass; a real sync + gear swap + race import still work E2E.
