# Third-party credentials are encrypted at rest, with the key outside the DB

The stored Garmin password is Fernet-encrypted (`backend/app/crypto.py`), never plaintext.
It cannot be bcrypt-hashed like the app password: the `garminconnect` library needs it back to re-authenticate when cached OAuth tokens expire, so it must be recoverable - symmetric encryption, not hashing.
The key resolves as: `SECRET_KEY` env (any passphrase, SHA-256-derived into a Fernet key) else an auto-generated `<data_dir>/.secret_key` file created `0600` with O_EXCL.
The key lives deliberately outside the database and is not captured by a `.db` backup, so a database or backup leak alone cannot decrypt the credentials - that separation is the whole point.

## Considered Options

- **Plaintext in the DB** (the original state) - rejected by the 2026-07 security audit: the DB and its backups hold members' most sensitive third-party credential.
- **Hash it like the app password** - impossible: hashing is one-way and the credential must be recoverable for re-auth.
- **Key stored in the DB or alongside it in backups** - rejected: encryption whose key travels with the ciphertext protects nothing when the common leak unit is the DB file or a backup copy.
- **Don't store the password at all (OAuth tokens only)** - the direction the code already leans (tokens are cached and password login is rare), but tokens expire and Garmin has no re-consent flow the app can trigger; dropping the password would strand members on token expiry.
- **Fernet with an external key** - chosen.

## Consequences

- Stored values are tagged `gb1:<token>`; an untagged value is treated as legacy plaintext and returned unchanged on read, so nothing broke mid-migration, and an idempotent startup migration rewrote legacy rows in place.
- A tagged value that fails to decrypt fails loudly (the key changed) rather than handing ciphertext to Garmin as a password.
- The key is a real operational responsibility: if `SECRET_KEY` / `.secret_key` is lost, every member re-enters their Garmin credentials.
  The VPS-migration runbook (`.scratch/vps-migration/ticket.md`) carries this as an explicit checklist item.
- `.db` backups remain secrets (they hold health and location data) but no longer leak credentials on their own.
- The same encrypt-at-rest path is the designated home for future stored secrets (per-user BYOB LLM keys).
- Known accepted gap: the on-disk Garmin OAuth token cache stays plaintext in a `0700` directory - tracked, lower stakes than the password.
