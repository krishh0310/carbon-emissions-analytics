from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://carbonscope:carbonscope@localhost:5432/carbonscope"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str  # required — no insecure default
    jwt_algorithm: str = "HS256"
    access_minutes: int = 15
    refresh_days: int = 7
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"
    admin_email: str | None = None      # bootstrap admin (created on seed if set)
    admin_password: str | None = None
    max_page_size: int = 200


@lru_cache
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # jwt_secret comes from env; fails fast if missing
