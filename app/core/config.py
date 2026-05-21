"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: str = os.getenv("DB_PORT", "5432")
    db_username: str = os.getenv("DB_USERNAME", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "postgres")
    db_name: str = os.getenv("DB_NAME", "food_ai_db")
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-me-in-local-env")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_expire_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    run_seed_on_startup: bool = _env_bool("RUN_SEED_ON_STARTUP", False)
    sync_tags_on_startup: bool = _env_bool("SYNC_TAGS_ON_STARTUP", False)
    sync_foods_on_startup: bool = _env_bool("SYNC_FOODS_ON_STARTUP", False)
    sync_foods_delete_stale_on_startup: bool = _env_bool("SYNC_FOODS_DELETE_STALE_ON_STARTUP", False)
    run_embedding_on_startup: bool = _env_bool("RUN_EMBEDDING_ON_STARTUP", False)
    embedding_backfill_limit: int = int(os.getenv("EMBEDDING_BACKFILL_LIMIT", "0"))
    embedding_backfill_sleep_seconds: float = float(os.getenv("EMBEDDING_BACKFILL_SLEEP_SECONDS", "3"))
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    places_cache_ttl_days: int = int(os.getenv("PLACES_CACHE_TTL_DAYS", "7"))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    password_reset_token_expire_minutes: int = int(os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "30"))
    gemini_text_model: str = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash-lite")

    @property
    def database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.db_username}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
