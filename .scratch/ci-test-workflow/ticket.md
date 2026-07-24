---
title: Add a test-only GitHub Actions workflow (commit hygiene, not the gate)
labels: [needs-grilling]
status: open
created: 2026-07-24
blocked-by: [frontend-test-infra]
---

# Add a test-only GitHub Actions workflow

## Idea

Add a minimal GitHub Actions workflow that runs the full test suite on every push: backend pytest and frontend `vitest run`.
No deploy steps, no secrets, no artifacts - tests only.

## Why

`./start.sh` is and remains the deploy gate (see the frontend-test-infra design), but it tests the working tree, not the commit.
CI is the only guard against the repo being silently non-self-contained: an un-added file, a package in `.venv` missing from requirements, a stale `node_modules`.
That failure class matters more as agents work from fresh clones (ultrareview, remote sessions).

## Scope boundaries

- CI does not gate deploys and never will in this design - deploys do not flow through GitHub.
- This slightly amends the frontend-test-infra decision "no GitHub Actions" to "no GitHub Actions as the deploy gate."

## Open question (resolve before implementing)

Are the backend pytest tests hermetic?
If any touch the live SQLite, Garmin credentials, or a running Docker stack, they need marking (e.g. a `pytest -m "not live"` split) so CI runs only the hermetic set.
Check this first; it is the one thing that could grow the ticket beyond ~30 lines of YAML.

## Sketch

- `.github/workflows/tests.yml`, triggered on push.
- Backend job: setup Python, `pip install -r backend/requirements.txt`, run pytest.
- Frontend job: setup Node, `npm ci`, `vitest run` (exists only after frontend-test-infra lands - hence blocked-by).
