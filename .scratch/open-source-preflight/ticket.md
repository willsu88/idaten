# Ticket: open-source pre-flight

Filed 2026-07-27 (from the 2026-07-20 security audit, ROADMAP - dissolved into tickets, see git history). Status: ready - run before the repo goes public.

## Already done

`.gitignore` before first commit (secrets never entered history), Garmin credentials encrypted at rest (ADR 0013), cookie `Secure`, login throttle, tenant isolation verified.

## Remaining before pushing public

0. **DECISION GATE - personal health data in git history (found 2026-07-27 review).**
   The deleted ROADMAP.md lives in history and contained Julianne's name alongside HRV values, menstrual-cycle discussions, race goals, and training specifics; API_CONTRACT.md still names her with real race times in its changelog sections.
   A secret scan will not flag any of this - it is not a credential.
   Options: scrub/anonymize and publish a fresh or squashed repo, or get her explicit OK and accept the history.
   This decides HOW the repo is published, so settle it before anything below.
   (Will's own training data in the README screenshots: reviewed and accepted, 2026-07-27 - no action.)
1. One-time secret scan over the full history (`gitleaks` or `trufflehog`) - cheap insurance even though `.gitignore` predates the first commit.
2. Scrub README / docker-compose / `.env.example` for any real values.
3. Decide on the Garmin OAuth token cache on disk (`data/garmin_tokens/*/garmin_tokens.json`, plaintext, dir 0700) - same class as the DB password but lower priority; either encrypt via `app/crypto.py` or document it as an accepted risk.
4. Treat `.db` backups as secrets stays an operational habit (they're gitignored; the encryption key file is never inside a `.db` backup).

Related: [[llm-seam-extraction]] publishes the seam first; [[byob-user-keys]] is phase 2 after going public.
