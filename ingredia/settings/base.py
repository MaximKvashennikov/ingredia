"""Load component models from nested environment variables or the local dotenv file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ingredia.settings.ai import AISettings
from ingredia.settings.database import DatabaseSettings
from ingredia.settings.logging import LoggingSettings
from ingredia.settings.telegram import TelegramSettings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Compose independent settings; double underscores select nested fields."""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
        extra="ignore",
    )
    telegram: TelegramSettings
    ai: AISettings = Field(default_factory=AISettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


@lru_cache
def get_settings() -> Settings:
    """Load and cache validated nested application settings."""
    return Settings()
