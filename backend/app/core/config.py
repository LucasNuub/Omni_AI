"""Application settings, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_path: Path = Path("./data/gateway.db")

    jwt_secret: str = "dev-only-insecure-secret-change-me-before-deploying"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    master_encryption_key: str | None = None

    admin_email: str | None = None
    admin_bootstrap_password: str | None = None

    invite_expire_hours: int = 72

    # SPEC.md section 9: benchmark is capped at a sane sample size so
    # onboarding a key doesn't itself burn the day's quota.
    discovery_benchmark_sample_size: int = 10

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
