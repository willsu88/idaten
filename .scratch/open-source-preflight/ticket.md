# Ticket: open-source pre-flight

Filed 2026-07-27 (from the 2026-07-20 security audit, ROADMAP - dissolved into tickets, see git history). Status: ready - run before the repo goes public.

## Already done

`.gitignore` before first commit (secrets never entered history), Garmin credentials encrypted at rest (ADR 0013), cookie `Secure`, login throttle, tenant isolation verified.

## Remaining before pushing public

0. **DECISION GATE - personal data review: RESOLVED 2026-07-27.**
   Full-history and working-tree privacy review completed; findings addressed and the outcome accepted.
   No further action.
1. **DONE 2026-07-27**: `gitleaks` scanned all 31 commits of history - no leaks found.
2. **DONE 2026-07-27**: README / docker-compose / `.env.example` swept.
   Household timezone moved out of `docker-compose.yml` into `.env` (documented as `TZ=UTC` in `.env.example`); `INITIAL_USERNAME` example genericized; `start.sh` checked clean (placeholder domains only).
   Along the way the README's "back up by copying the file" advice was replaced with the in-container SQLite backup command (verified working) since a host-side copy of the live WAL DB is unsafe.
3. **DONE 2026-07-27**: Garmin OAuth token cache settled as accepted risk in ADR 0015 (encryption with a same-disk key protects nothing; revocation via Garmin password change is the mitigation).
   README security section now carries the user-facing remediation procedure; revisit at VPS migration / BYOB when the key can live off-disk.
4. Treat `.db` backups as secrets stays an operational habit (they're gitignored; the encryption key file is never inside a `.db` backup).

Related: [[llm-seam-extraction]] publishes the seam first; [[byob-user-keys]] is phase 2 after going public.
