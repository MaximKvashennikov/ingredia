"""Independent configuration models for both Telegram bots and trial access."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class UserBotSettings(BaseModel):
    """Required credentials of the user-facing bot."""

    model_config = ConfigDict(extra="forbid")
    token: SecretStr
    username: str


class AdminBotSettings(BaseModel):
    """Optional administrative bot credentials and trusted numeric identities."""

    model_config = ConfigDict(extra="forbid")
    token: SecretStr | None = None
    username: str = "ingredia_admin_helper_bot"
    user_ids: frozenset[int] = frozenset()


class TrialSettings(BaseModel):
    """Explicit trial access policy without granting administrative rights."""

    model_config = ConfigDict(extra="forbid")
    allowed_user_ids: frozenset[int] = frozenset()
    open_access: bool = False


class TelegramSettings(BaseModel):
    """Keep user, administrator and trial concerns separate."""

    model_config = ConfigDict(extra="forbid")
    user: UserBotSettings
    admin: AdminBotSettings = Field(default_factory=AdminBotSettings)
    trial: TrialSettings = Field(default_factory=TrialSettings)
