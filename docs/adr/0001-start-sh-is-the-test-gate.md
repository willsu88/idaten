# The deploy script is the test gate, not CI

Idaten has no CI server and deploys do not flow through GitHub: every change reaches the live app through `./start.sh` on the host Mac.
We therefore made `start.sh` the enforcement point - it runs backend pytest and frontend vitest and aborts the deploy on any failure, so a red test can never reach the live app.
A GitHub Actions workflow would put the gate where deploys never pass; it may be added later for commit hygiene (proving the repo is self-contained from a fresh clone - see `.scratch/ci-test-workflow`), but it will not be the gate in this design.

## Consequences

- Deploys pay the full-suite cost (~2 minutes of backend pytest as of 2026-07).
  `SKIP_TESTS=1 ./start.sh` exists for deliberate hotfixes only.
- The gate tests the working tree, not the commit - "forgot to git add" failures are invisible to it.
  That failure class is what the optional Actions workflow would cover.
