"""Application configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SECURE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
SUPPORTED_DRIVERS = frozenset({"postgresql", "postgresql+psycopg2"})
API_KEY_PLACEHOLDER_PREFIX = "replace-with"


class DatabaseSettings(BaseSettings):
    """Settings needed to reach the database (used by the API, Alembic and scripts)."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr = Field(
        description="SQLAlchemy URL, e.g. postgresql+psycopg2://user:pass@127.0.0.1:55432/postgres?sslmode=disable",
    )
    db_pool_size: int = Field(default=1, ge=1, le=50)
    db_max_overflow: int = Field(default=0, ge=0, le=50)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60)

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        try:
            url = make_url(raw)
        except ArgumentError as exc:
            raise ValueError("DATABASE_URL is not a valid SQLAlchemy database URL") from exc
        if url.drivername not in SUPPORTED_DRIVERS:
            raise ValueError(
                "DATABASE_URL must use the postgresql+psycopg2:// driver "
                f"(got '{url.drivername}://')"
            )
        if not url.host:
            raise ValueError("DATABASE_URL must include a host")
        sslmode = str(url.query.get("sslmode", "prefer"))
        if url.host not in LOCAL_DATABASE_HOSTS and sslmode not in SECURE_SSL_MODES:
            # Protects a future remote database (for example Supabase) from being
            # used over an unencrypted connection by accident.
            raise ValueError(
                "DATABASE_URL points to a non-local host, so it must set "
                "sslmode=require, verify-ca or verify-full"
            )
        return value

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url.get_secret_value()


class Settings(DatabaseSettings):
    """Full settings for the HTTP API."""

    app_name: str = "Crescent Motors Customer Support Ticket Management System"
    app_version: str = "1.0.0"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_key: SecretStr = Field(min_length=16, description="Shared secret expected in the X-API-Key header")
    company_name: str = Field(default="Crescent Motors", min_length=1, max_length=200)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().strip().lower().startswith(API_KEY_PLACEHOLDER_PREFIX):
            raise ValueError("API_KEY still contains the .env.example placeholder; set a real random value")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()  # type: ignore[call-arg]
