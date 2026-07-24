---
title: Stand up frontend test infrastructure
labels: []
status: done
created: 2026-07-24
blocked-by: []
---

# Stand up frontend test infrastructure

## Design (settled in the 2026-07-24 grilling session)

1. **Runner: Vitest**, and nothing else.
   jsdom and Testing Library are explicitly deferred until a ticket first needs a component test (add `// @vitest-environment jsdom` per-file then).
2. **Default test layer: pure logic.**
   Tests target pure modules in `frontend/lib/`; components stay thin and untested for now.
3. **E2E: out of scope, no Playwright ticket filed.**
   The revisit trigger is a real regression escaping manual live-app testing - that event names the first flow worth automating.
4. **Layout: colocated** - `foo.test.ts` next to `foo.ts`.
5. **Enforcement: `./start.sh` is the gate** (see `docs/adr/0001-start-sh-is-the-test-gate.md`).
   It runs backend pytest and frontend `vitest run` before `docker compose up --build` and aborts on failure; `SKIP_TESTS=1` bypasses for hotfixes.
   No GitHub Actions *as the gate*; a test-only Actions workflow for commit hygiene is `.scratch/ci-test-workflow`.
6. **First coverage: `frontend/lib/reorder.ts`, thoroughly.**
   Other `lib/` modules get tests when next touched.

## Shipped

- `frontend/vitest.config.ts` (node environment, `@` alias mirroring tsconfig) and `npm test` → `vitest run`.
- `frontend/lib/reorder.test.ts`: 17 tests covering `isLockedDay` boundaries, `swapSlots` no-op cases (locked, out-of-range, self-swap), `hasChanges`/`buildMoves` (identity → zero moves, swap → exactly two moves, undo → zero), and `adjacentQualityDates` (separated/pair/triple, staged-arrangement adjacency, missing-day handling).
- `start.sh` test gate running backend pytest (via `.venv/bin/python -m pytest`, shebang-proof) and frontend vitest.
