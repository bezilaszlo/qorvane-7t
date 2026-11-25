from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Only what differs per environment; tuning defaults live in code (app/db.py)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sensors"


@lru_cache
def get_settings() -> Settings:
    return Settings()
