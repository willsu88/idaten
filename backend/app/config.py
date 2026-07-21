"""Environment-driven configuration.

Everything operational (credentials, provider choice, paths) comes from env /
.env. User-editable preferences (race goal, plan hour, auto-push) live in the
settings table and are managed through the API; env values act as defaults.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Secrets / crypto. `secret_key` (env SECRET_KEY) drives encryption-at-rest
    # for stored Garmin passwords; if empty, an auto-generated key file under the
    # data dir is used instead (see app/crypto.py). `cookie_secure` marks the
    # session cookie Secure (HTTPS-only) - default on; only turn off for a
    # plain-HTTP deployment with no TLS in front.
    secret_key: str = ""
    cookie_secure: bool = True

    # LLM
    llm_provider: str = "anthropic"  # "anthropic" | "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.1"

    # Garmin (used to seed the first user's credentials at bootstrap; after
    # that, credentials live per-user in the users table)
    garmin_email: str = ""
    garmin_password: str = ""
    garmin_token_dir: str = "/data/garmin_tokens"

    # First user bootstrapped at startup when the users table is empty
    initial_username: str = "will"
    initial_password: str = "changeme"

    # Storage / scheduling
    db_path: str = "/data/garmin_bot.db"
    # IANA zone the household lives in. `plan_hour` and all "today"/date logic are
    # interpreted here, NOT in the container's UTC clock. Reads the standard `TZ`
    # env so one value drives both libc (naive datetimes) and the scheduler.
    timezone: str = Field("Asia/Taipei", validation_alias="TZ")
    plan_hour: int = 6           # local hour for the daily sync+plan job
    sync_lookback_days: int = 14
    auto_push_workouts: bool = False  # workouts go to the watch only when you click send
    backfill_days: int = 300          # deep-history stage of onboarding


config = Config()
