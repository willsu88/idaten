# Ticket: redesign README.md as the repo's front door

Filed 2026-07-27. Status: ready - do in a fresh session that reads the current README cold, the way a first-time visitor would.

## The problem

The repo now contains real depth - 14 ADRs, docs/TESTING.md (five-layer test architecture), COACH_QUALITY.md, DEPLOYMENT.md - but the README routes a reader to none of it.
A first-time visitor sees the product surface and never finds the engineering record.

## The README has three jobs, in order

1. **Sell the product in one screen**: what Idaten does for a runner (editor above the Garmin plan, morning coach note, approval queue), with a screenshot.
2. **Route to the engineering depth**: agent loop, provider seam, five-layer testing, the ADR index - each one line + link, not re-explained.
3. **Show operational maturity**: start.sh test gate, tunnel deployment, encrypted credentials - proof this runs in production for real users.

## Constraints

- Written in the same voice the seam-repo README will use; the two link to each other (seam README carries the paragraph-level echo of the testing layer map, links to docs/TESTING.md as the worked example).
- No claims ahead of reality: layer 5 is designed-not-built and stays labeled that way everywhere.
- Fresh-session protocol: read the current README first without context, list what a cold reader misses, then restructure.

## Also in scope: root CLAUDE.md

The repo has no root agent-instructions file.
Write a `CLAUDE.md` in the same pass and voice: what to read first (CONTEXT.md, docs/TESTING.md, the ADR index), how to run the test gate (`./start.sh`), and a pointer to the repo skills (`.claude/skills/`).
Claude Code discovers the skills automatically; the file exists for other agents and for humans reading the repo as a contribution target.
