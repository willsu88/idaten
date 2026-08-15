# Sleep data queried across days becomes daily_health columns; the per-night payload is archived verbatim

Garmin's `get_sleep_data` returns one large payload per night: stage seconds, a hypnogram, a per-component score breakdown, naps, sleep need, and five overnight time series (HR, HRV, stress, body battery, respiration).
Until v1.43 the sync kept two fields of it (`sleep_seconds`, `sleep_score`) and threw the rest away.
The sleep page and the coach both want more, and the question this ADR settles is where that data lives.

The rule: **anything aggregated or filtered across days is a real column on `daily_health`; anything only ever rendered within one night stays in the payload, archived verbatim.**

Concretely:

- `daily_health` gains nullable scalar columns (stage seconds, nap totals, sleep-need minutes, awake/restless counts, bed/wake local timestamps, body-battery change), parsed in `sync_health_day` (`app/garmin/sync.py`).
  Trend charts (`GET /api/sleep`), readiness, and the coach snapshot (`metrics.coach_health_dict`) read these with plain SQL, same as `hrv` and `resting_hr` always have.
- A new `sleep_detail` table (`user_id`, `date`, `raw` JSON) stores the whole payload unmodified, upserted in the same sync pass.
  `GET /api/sleep/{date}` parses it down on read through `app/sleep.py::detail_from_raw`; nothing else reads the blob.

This is the same judgment `Activity.raw` already embodies for activity summaries: keep the source of truth, project what you need.

The archive is what makes the rule cheap to apply.
Deciding which scalars deserve columns is a judgment call made per feature, and the archive makes wrong calls recoverable: promoting a field later is a re-parse loop over `sleep_detail.raw` - no Garmin API calls, no rate limits, and it works for dates in the past, which a re-sync cannot reach reliably (Garmin's per-day endpoints throttle hard, and old data occasionally disappears upstream).

## Considered options

- **All columns, no archive** - rejected: the payload has ~15 nested structures whose shapes Garmin changes without notice; modeling them relationally is a large, brittle schema for data with exactly one reader (the detail endpoint), and any field not modeled is lost forever once the night has passed.
- **Raw only, no columns** - rejected: every cross-day read (trends, coach context, readiness) becomes `json_extract` over ninety blobs per query; SQLite can do it, but it is slower, unindexable, and every consumer re-implements the parse instead of reading a named column.
- **Epoch rows** (a `sleep_epochs` table, one row per hypnogram segment / series point) - rejected: nothing filters or aggregates *inside* a night, so thousands of rows per night buy query power nobody uses and make writes and backfills far heavier.
- **`raw` column on `daily_health` itself** - rejected: the payload is hundreds of KB per night and `daily_health` rows are hot (readiness, trends, and coach snapshot queries touch them constantly); a separate table keeps the blob out of every hot read. This is why `sleep_detail` exists as a table rather than a column, unlike `Activity.raw` where the row is already only read for detail views.
- **Chosen: hybrid with the across-days/within-a-night rule** - columns stay small and queryable, the archive keeps everything, and the rule tells the next feature exactly where its field goes.

## Consequences

- Promotion is deliberate work: a scalar we later want to trend requires adding the column, extending the parse, and running a one-shot re-parse over `sleep_detail` to backfill it. The re-parse is free of Garmin calls, but it must be remembered - a column added without it silently reads null for history.
- Storage grows by the payload size per user per night indefinitely; at current sizes this is a few hundred MB per user per decade, acceptable for a self-hosted SQLite deployment (ADR 0012), but a hosted multi-tenant future would need a retention or compression decision.
- The raw blob is Garmin's schema, not ours: `detail_from_raw` is the single seam that absorbs upstream shape changes, and it must stay null-tolerant (it is tested against partial payloads in `tests/test_sleep_api.py`).
- Nights synced before v1.43 have no archive and cannot get one retroactively beyond Garmin's own history window; the detail endpoint answers `available: false` for them and the UI says why.
- The rule generalizes: the next wellness payload (e.g. all-day stress detail, SpO2 once pulse ox is on) should follow it - scalars to `daily_health`, payload to its own `<domain>_detail` table - rather than inventing a third pattern.
