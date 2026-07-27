# The Garmin OAuth token cache stays plaintext; revocation, not encryption, is the mitigation

The unofficial `garminconnect` library (via `garth`) owns the whole token lifecycle: `Garmin.login(tokenstore)` in `backend/app/garmin/client.py` loads cached OAuth tokens from `data/garmin_tokens/<user_id>/garmin_tokens.json` if present, otherwise performs a password login and writes fresh tokens there itself.
The file is plaintext JSON holding an OAuth1 token (valid roughly a year) and the OAuth2 pair minted from it; whoever reads it can act as that member on Garmin Connect - read the full health history and GPS tracks, push or delete watch workouts - until the tokens are revoked.
Protections in place: `get_garmin` enforces `0700` directories and `0600` files itself after every login (the library writes with umask-default modes, world-readable on a stock Linux host, so the umask is not trusted - `tests/test_garmin_token_perms.py`), the path is gitignored (never entered history, verified by a full-history `gitleaks` scan 2026-07-27), and the tokens are not captured by `.db` backups, which copy only the database.
ADR 0013 encrypts the stored Garmin password and named this cache as its known accepted gap; this ADR settles it.

## Considered Options

- **Encrypt the cache via `backend/app/crypto.py`** - rejected: the default encryption key lives at `data/.secret_key`, in the same `data/` directory as the tokens, so against the realistic leak units (host compromise, a copied `data/` directory, a stray Time Machine / synced-folder copy) key and ciphertext travel together and the encryption protects nothing.
  The slice it does cover - an attacker who obtains the token file but not its neighbor the key - is thin, and paying for it means fighting the library: `garth` reads and writes the directory itself, so encryption requires decrypt-to-disk before every `login()` and re-encrypt after, with a plaintext window anyway.
  This is the same judgment that killed key-alongside-ciphertext in ADR 0013, applied in the other direction.
- **Store tokens encrypted in the DB instead of on disk** - rejected for the same key-proximity reason, plus it would put a live third-party credential inside `.db` backups, which ADR 0013 deliberately keeps credential-free.
- **Don't cache tokens at all** - rejected: Garmin aggressively rate-limits password logins; the cache is what makes daily sync viable (the reason `data/garmin_tokens` is a persisted volume).
- **Accept the plaintext cache, bound the blast radius by revocation** - chosen.

## Consequences

- The threat model is exactly filesystem access to `data/` on the host; the file never travels otherwise.
  The operational rule follows: a copy of `data/` is as sensitive as the tokens inside it - the same habit that already treats `.db` backups as secrets.
- Remediation is fast and total, and is documented user-facing in the README's security section: if `data/` may have leaked, change the Garmin password immediately, then reconnect Garmin in Settings.
  Garmin invalidates outstanding OAuth tokens on password change; blast radius is bounded by how quickly that happens.
- Revocation is all-or-nothing: the tokens impersonate the official Garmin Connect mobile app, so they appear in no connected-apps list and cannot be revoked individually - the password change also signs out the member's real Garmin apps.
- Each member's cache is independent (`data/garmin_tokens/<user_id>/`); a leak response is per-member password changes.
- Re-evaluate if the deployment story changes: the accept rests on key-and-tokens sharing a disk.
  A deployment where `SECRET_KEY` is supplied via environment and never touches `data/` (the likely multi-tenant / BYOB shape, and worth revisiting at the VPS migration) makes the encryption slice meaningful, and the first option above becomes live again.
