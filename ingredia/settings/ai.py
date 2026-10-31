"""Cloud provider selection and independently masked credentials."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ProviderCredentials(BaseModel):
    """Credentials of one provider; inactive providers need no key."""

    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr | None = None


class AISettings(BaseModel):
    """Explicit provider selection without automatic or paid fallback."""

    model_config = ConfigDict(extra="forbid")
    provider: Literal["zai", "groq"] = "zai"
    groq: ProviderCredentials = Field(default_factory=ProviderCredentials)
    zai: ProviderCredentials = Field(default_factory=ProviderCredentials)
