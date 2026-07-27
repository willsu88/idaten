# Agent instructions for Idaten

Idaten is a self-hosted AI running coach: FastAPI + SQLite backend, Next.js frontend, an LLM coach behind a provider seam.
It serves real users in production, so treat main as live.

## Read first

- `CONTEXT.md` - the canonical domain glossary. Code, UI copy, and docs must use these terms with these meanings; do not invent synonyms.
- `docs/TESTING.md` - the five-layer test architecture and the decision procedure for where a new test goes. Layers 1-2 are deterministic pytest; layers 3-4 are paid evals (`pytest -m eval`); layer 5 is designed but not yet built.
- `docs/adr/README.md` - the ADR index. Before changing an architectural choice, read its ADR; if you make a new load-bearing decision, record it as the next ADR.

## Where written knowledge lives

Decisions go in ADRs; work not yet built (ideas, specs, in-flight tickets) goes in `.scratch/<ticket>/ticket.md`; shipped history lives in git log only.
Never keep a changelog or build log in a Markdown doc - that is what deleted ROADMAP.md and UX_IMPROVEMENTS.md did, and they rotted.
Frontend-facing API changes append a versioned section to `API_CONTRACT.md` first; the frontend is built against the contract.

Never write personal or machine-specific data into anything that gets committed - docs, tickets, ADRs, test fixtures, code comments.
That means no real names of household members (write "user 2"), no health values tied to a person, no real birthdates or credentials, and no local-machine details (timezones, hostnames, absolute paths outside the repo).
Gitignored files (`.env`, `data/`, `.claude/settings.local.json`) are fine - that is where real values live.
The repo is public-facing; git history is forever.

## Test gate

`./start.sh` is the deploy path and the test gate (ADR 0001): it runs backend pytest and frontend vitest before bringing the Docker stack up, so a red test never reaches the live app.
Run backend tests directly with the backend virtualenv:

```sh
cd backend && .venv/bin/python -m pytest          # layers 1-2, free
cd backend && .venv/bin/python -m pytest -m eval  # layers 3-4, calls a real model, costs money
```

Never touch `data/garmin_bot.db` from the host while Docker is running; go through `docker exec` instead.

## Operational gotchas (hard-won, do not re-learn)

- Anything touching Garmin must run inside the container (`docker compose exec -T backend python ...`) - the OAuth tokens live there.
- Never rebuild the backend container while a backfill is running (it kills the thread).
- Garmin 429s must propagate - never swallow them per-metric; backfill/enrichment back off and retry.
- Always `db.rollback()` in loop error handlers - one poisoned flush silently kills every subsequent commit.
- Predeploy backups go through the in-container SQLite backup API, never a host-side file copy of the WAL DB.

## Skills

Repo skills live in `.claude/skills/`.
Claude Code discovers them automatically; other agents and humans should read them as the documented procedures for their tasks - e.g. `add-eval-case` encodes the TESTING.md steps for adding a layer 3-4 eval.
