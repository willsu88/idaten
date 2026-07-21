# Idaten — personal AI running coach

Syncs your Garmin data daily, keeps a rolling 7-day training plan toward your race adjusted for sleep / HRV / training load, pushes structured workouts to your watch, and lets you chat with a coach that can read your data and propose plan changes (with a diff you approve).

## Architecture

- **Backend** (`backend/`): FastAPI + SQLite + APScheduler.
  Daily job at `PLAN_HOUR`: sync Garmin → compute readiness + CTL/ATL/TSB in code → one structured-output LLM call with a fixed-size snapshot (cost is constant, history is only ever seen as aggregates) → store the 7-day plan with per-day rationale → auto-push changed workouts to the Garmin calendar/watch.
  If the machine was asleep at plan time, a catch-up check runs the job on the next opportunity.
- **LLM layer** (`backend/app/llm/`): provider-agnostic seam.
  The planner and chat agent depend only on the `LLMClient` protocol; `make_client()` picks Anthropic or OpenAI from settings. History and tool schemas use the neutral (OpenAI) shape; the Anthropic client translates at its own boundary.
- **Chat agent** (`backend/app/chat/`): small tool loop — `get_training_data`, `get_current_plan`, `get_plan_history`, and `propose_plan_edit`.
  Plan edits are an approval queue: the agent creates a *pending* edit, the UI shows a per-day diff, nothing changes until you accept.
- **Frontend** (`frontend/`): Next.js + Tailwind + Recharts, dark/light mode.
  Today-first dashboard (readiness traffic light, today's workout + "why", pending-edit diff card, 1-tap RPE), week view, trends charts, streaming chat with slash shortcuts, settings.

## Setup

```sh
cp .env.example .env   # fill in Garmin credentials + an LLM API key
docker compose up --build
```

- Backend: http://localhost:8000 (OpenAPI docs at `/docs`)
- App: http://localhost:3000

First run: open **Settings**, set your race (name, date, distance, goal time), then hit **Sync now** on the dashboard. That pulls the last 14 days of Garmin data and generates your first plan.

Garmin login uses the unofficial `garminconnect` library with your credentials; after the first successful login, OAuth tokens are cached in `./data/garmin_tokens` and the password is no longer needed. If your account uses MFA, do the first login outside Docker (`python -c "..."`) or temporarily disable MFA — token reuse works fine afterwards.

## Security & disclaimer

- **Self-host only.** This is a personal, single-household app. It has no multi-tenant hardening and is not meant to be exposed to the public internet - run it on your own machine or a private network.
- **Not affiliated with Garmin.** Garmin login uses the unofficial `garminconnect` library, which scrapes Garmin Connect and can break if Garmin changes their API. "Garmin" is a trademark of Garmin Ltd.; this project is independent and unendorsed. Use at your own risk, and don't put "Garmin" in any fork's name.
- **Your credentials stay local.** Garmin passwords are encrypted at rest (`SECRET_KEY`) and, after the first login, replaced by cached OAuth tokens under `data/`. Your health data and API keys never leave your machine except in the LLM calls you configure. Nothing is committed to git - `.env`, `data/`, and `backups/` are gitignored.
- **No warranty.** Provided as-is; you are responsible for your own data, backups, and API costs.

## Notes

- **Data** lives in `./data/garmin_bot.db` (SQLite). Back it up by copying the file.
- **Watch push** creates a structured running workout (duration/distance end condition + pace band) in Garmin Connect and schedules it on the plan date; your watch picks it up on its next sync. Superseded workouts are deleted and re-pushed. Rest/cross-train days are not pushed.
- **Cost**: the daily plan call sends a ~3–4k-token snapshot regardless of history length — roughly $1–2/month on Claude Opus 4.8.
- **API contract** for the frontend: `API_CONTRACT.md`.
