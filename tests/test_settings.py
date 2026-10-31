"""Nested configuration precedence and secret masking without real credentials."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from ingredia.clock import calendar_date
from ingredia.settings import Settings


def test_nested_environment_fields_and_secret_representations(monkeypatch):
    """Double underscores populate independently typed bot, provider and database settings."""
    values = {
        "TELEGRAM__USER__TOKEN": "synthetic-user-token",
        "TELEGRAM__USER__USERNAME": "synthetic_bot",
        "TELEGRAM__ADMIN__TOKEN": "synthetic-admin-token",
        "TELEGRAM__ADMIN__USER_IDS": "[99, 100]",
        "TELEGRAM__TRIAL__OPEN_ACCESS": "true",
        "TELEGRAM__TRIAL__ALLOWED_USER_IDS": "[1, 2]",
        "AI__PROVIDER": "groq",
        "AI__GROQ__API_KEY": "synthetic-groq-key",
        "AI__ZAI__API_KEY": "synthetic-zai-key",
        "DATABASE__URL": "postgresql+asyncpg://synthetic:password@localhost/db",
        "LOGGING__LEVEL": "WARNING",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    config = Settings(_env_file=None)
    assert config.telegram.user.username == "synthetic_bot"
    assert config.telegram.admin.user_ids == frozenset({99, 100})
    assert config.telegram.trial.open_access
    assert config.telegram.trial.allowed_user_ids == frozenset({1, 2})
    assert config.ai.provider == "groq" and config.logging.level == "WARNING"
    assert config.ai.groq.api_key.get_secret_value() == values["AI__GROQ__API_KEY"]
    assert config.database.url.get_secret_value() == values["DATABASE__URL"]
    for name in [
        "TELEGRAM__USER__TOKEN",
        "TELEGRAM__ADMIN__TOKEN",
        "AI__GROQ__API_KEY",
        "AI__ZAI__API_KEY",
        "DATABASE__URL",
    ]:
        assert values[name] not in repr(config)


def test_process_environment_overrides_one_nested_dotenv_field(tmp_path, monkeypatch):
    """A leaf override keeps sibling secrets and default nested models intact."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "TELEGRAM__USER__TOKEN=synthetic-token\n"
        "TELEGRAM__USER__USERNAME=synthetic_bot\n"
        "AI__PROVIDER=zai\nAI__ZAI__API_KEY=synthetic-zai\n"
        "AI__GROQ__API_KEY=synthetic-groq\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI__PROVIDER", "groq")
    config = Settings(_env_file=dotenv)
    assert config.ai.provider == "groq"
    assert config.ai.zai.api_key.get_secret_value() == "synthetic-zai"
    assert config.ai.groq.api_key.get_secret_value() == "synthetic-groq"
    assert config.telegram.admin.token is None and not config.telegram.admin.user_ids
    assert config.database.url is None and config.logging.level == "INFO"


def test_missing_nested_bot_credentials_fail_without_loading_private_dotenv():
    """Missing required user credentials fail before any network connection."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_calendar_policy_uses_moscow_midnight():
    """Windows and Docker classify a UTC evening under the same Moscow calendar day."""
    assert calendar_date(datetime(2026, 10, 30, 21, 1, tzinfo=UTC)) == date(2026, 10, 31)
    assert calendar_date(datetime(2026, 10, 30, 20, 59, tzinfo=UTC)) == date(2026, 10, 30)
    with pytest.raises(ValueError):
        calendar_date(datetime(2026, 10, 30))
