"""Central logging configuration and secret-safe formatting."""

import logging
import time
from logging.config import dictConfig

from pydantic import SecretStr


class SecretRedactingFormatter(logging.Formatter):
    """Format UTC records and redact configured secrets, including exception text."""

    converter = staticmethod(time.gmtime)

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        """Keep sensitive values outside configuration representations."""
        super().__init__(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        self._secrets = tuple(value for value in secrets if value)

    def format(self, record: logging.LogRecord) -> str:
        """Redact secrets after formatting the complete record and traceback."""
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return text


def configure_logging(level: str, secrets: tuple[SecretStr, ...]) -> None:
    """Configure application and framework logging once, before starting the server."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "safe": {
                    "()": SecretRedactingFormatter,
                    "secrets": tuple(secret.get_secret_value() for secret in secrets),
                },
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "safe"},
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": [], "level": "INFO", "propagate": True},
                "uvicorn.error": {"handlers": [], "level": "INFO", "propagate": True},
                "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": True},
                "aiogram": {"handlers": [], "level": "INFO", "propagate": True},
                "httpx": {"handlers": [], "level": "WARNING", "propagate": True},
                "httpcore": {"handlers": [], "level": "WARNING", "propagate": True},
                "aiohttp": {"handlers": [], "level": "WARNING", "propagate": True},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger without adding handlers or configuring global logging."""
    return logging.getLogger(name)
