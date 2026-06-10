import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root is three levels above this file's directory:
# backend/app/core/config.py → backend/app/core → backend/app → backend → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://light:light@localhost:5436/investintell_light"
    )
    # Tiingo API token — used from F1 onward. NEVER expose to frontend or logs.
    tiingo_token: str | None = None
    # Read-only connection to the investintell-allocation mother DB — used from F6 onward.
    investintell_db_url: str | None = None


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
