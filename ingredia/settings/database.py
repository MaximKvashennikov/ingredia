"""Database connection configuration independent of deployment password variables."""

from pydantic import BaseModel, ConfigDict, SecretStr


class DatabaseSettings(BaseModel):
    """Keep the complete connection URL masked in diagnostic representations."""

    model_config = ConfigDict(extra="forbid")
    url: SecretStr | None = None
