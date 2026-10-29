"""Application configuration loaded from the process environment or .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Validated settings; missing credentials fail when settings are loaded."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: SecretStr
    telegram_bot_username: str


@lru_cache
def get_settings() -> Settings:
    """Load and cache the application settings.

    Returns:
        Settings: Validated configuration from the environment or .env.
    """
    return Settings()
