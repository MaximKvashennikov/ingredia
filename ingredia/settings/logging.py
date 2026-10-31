"""Configuration of the centrally installed logging handlers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LoggingSettings(BaseModel):
    """The application's root log level."""

    model_config = ConfigDict(extra="forbid")
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
