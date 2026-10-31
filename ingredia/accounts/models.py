"""Validated commands and immutable application views."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingredia.accounts.expiry import ExpiryEstimate


class AccessDenied(Exception):
    """The verified actor cannot perform this operation."""


class Conflict(Exception):
    """The resource changed after the displayed version."""


class StockUnit(StrEnum):
    """Supported quantity dimensions."""

    GRAM = "g"
    KILOGRAM = "kg"
    MILLILITER = "ml"
    LITER = "l"
    PIECE = "pcs"


class BatchInput(BaseModel):
    """Explicit manual input; missing information remains unknown."""

    name: str = Field(min_length=1, max_length=128)
    quantity: Decimal | None = Field(default=None, gt=0, le=1000000, decimal_places=3)
    unit: StockUnit | None = None
    expiry: date | None = None

    @model_validator(mode="after")
    def consistent_quantity(self) -> "BatchInput":
        """Require amount and unit together."""
        if (self.quantity is None) != (self.unit is None):
            raise ValueError("quantity and unit must be specified together")
        return self


class AccountView(BaseModel):
    """Safe account metadata."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    telegram_id: int
    created_at: datetime
    name: str
    blocked: bool
    version: int


class BatchView(BaseModel):
    """Private stock view returned only after owner verification."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    quantity: Decimal | None
    unit: str | None
    expiry: date | None
    expiry_source: str
    expiry_estimate: ExpiryEstimate | None = None


class AccountFilter(StrEnum):
    """Supported directory views, independent of a Telegram keyboard."""

    ALL = "all"
    ACTIVE = "active"
    BLOCKED = "blocked"


class AccountPage(BaseModel):
    """A bounded page with an exact count for reliable navigation."""

    items: list[AccountView]
    total: int
    page: int
    page_size: int = 8

    @property
    def has_next(self) -> bool:
        """Report whether the next directory page contains any users."""
        return (self.page + 1) * self.page_size < self.total


class StockPage(BaseModel):
    """A compact inventory page with exact navigation boundaries."""

    items: list[BatchView]
    total: int
    page: int
    page_size: int = 6

    @property
    def has_next(self) -> bool:
        """Report another page without showing an empty next page."""
        return (self.page + 1) * self.page_size < self.total
