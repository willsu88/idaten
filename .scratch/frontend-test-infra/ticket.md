---
title: Stand up frontend test infrastructure
labels: [needs-grilling]
status: open
created: 2026-07-24
blocked-by: []
---

# Stand up frontend test infrastructure

## Idea

The frontend (Next.js 14, React 18, TypeScript) has zero test infrastructure: no runner, no test script, no test dependencies, no test files.
All ~50 automated tests in the repo are backend pytest.
Stand up a minimal frontend testing stack so frontend behavior can be tested going forward.

## Why now

The week-reorder feature (see .scratch/week-reorder/spec.md) introduces real client-side logic worth testing: a staging reducer (drags mutate local state, Cancel/Esc restore, Done emits one batch request), locked-card exclusion from sorting, and a quality-day adjacency heuristic.
That spec deliberately keeps those as pure, importable modules so this ticket can cover them without refactoring.

## Not yet designed

This ticket is NOT ready for an agent.
Run a /grill-with-docs session first to settle at least:

- Runner and stack choice (leading candidate from prior discussion: Vitest + jsdom + Testing Library; Playwright for E2E is a separate question).
- What layer to test by default: pure logic only, component behavior, or both.
- Whether real-browser E2E belongs in scope now or later.
- Test file location convention (colocated vs __tests__) and CI wiring.
- First coverage targets (week-reorder staging logic and adjacency heuristic are the natural candidates).
