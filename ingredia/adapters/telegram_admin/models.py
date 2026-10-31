"""Administrative confirmation state, isolated by trusted actor."""

from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from aiogram.fsm.state import State, StatesGroup
from pydantic import BaseModel, Field

from ingredia.accounts.models import AccountFilter


@dataclass(frozen=True)
class StatusConfirmation:
    """Short-lived intent bound to an actor, target and displayed version."""

    actor: int
    target: str
    version: int
    blocked: bool
    reason: str
    expires: float
    target_name: str = ""

    @property
    def expired(self) -> bool:
        """Report whether the confirmation is no longer usable."""
        return monotonic() >= self.expires


class AdminFlow(StatesGroup):
    """Explicit short text steps, kept separate from user purchase input."""

    search = State()
    reason = State()


class StatusSelection(BaseModel):
    """An actor-scoped pointer to the latest displayed status action."""

    token: str = Field(default_factory=lambda: uuid4().hex[:12])
    target: str
    version: int
    blocked: bool
    expires: float


class DirectoryContext(BaseModel):
    """Preserve search, filter and page while opening and leaving account cards."""

    token: str = Field(default_factory=lambda: uuid4().hex[:12])
    query: str = Field(default="", max_length=128)
    status: AccountFilter = AccountFilter.ALL
    page: int = Field(default=0, ge=0, le=100000)
    selection: StatusSelection | None = None
