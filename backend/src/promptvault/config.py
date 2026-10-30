"""Runtime configuration. Precedence: env vars (PV_*) > .env > defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PV_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"  # loopback only; Docker image overrides this
    port: int = 8080
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".promptvault")
    database_url: str | None = None
    log_level: str = "info"
    seed_on_start: bool = True
    auto_migrate: bool = True
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v: object) -> object:
        return Path(str(v)).expanduser() if v is not None else v

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'promptvault.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
