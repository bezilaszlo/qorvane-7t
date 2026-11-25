from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/sensors"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_connect_timeout: float = 5.0
    db_pool_timeout: float = 5.0
    db_statement_timeout_ms: int = 5000
    db_idle_in_transaction_timeout_ms: int = 10000
    db_lock_timeout_ms: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
