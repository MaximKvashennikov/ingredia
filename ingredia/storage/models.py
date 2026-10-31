"""Relational schema for private accounts, stock and administrative audit."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared SQLAlchemy metadata for versioned migrations."""


class Account(Base):
    """Internal identity independent of Telegram identifiers."""

    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(128))
    blocked: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Batch(Base):
    """Separate purchase batch with explicit quantity and expiry provenance."""

    __tablename__ = "batches"
    __table_args__ = (CheckConstraint("quantity IS NULL OR quantity > 0"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(8))
    expiry: Mapped[date | None] = mapped_column(Date, index=True)
    expiry_source: Mapped[str] = mapped_column(String(20), default="unknown")
    expiry_estimate: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(default=1)


class Audit(Base):
    """Atomic administrative status history without private content."""

    __tablename__ = "administrative_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    reason: Mapped[str] = mapped_column(String(200))
    blocked: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseDraft(Base):
    """Validated purchase candidates awaiting an explicit owner decision."""

    __tablename__ = "purchase_drafts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(100), unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Recipe(Base):
    """Owner-bound generated recipe snapshot retained for favorites without regeneration."""

    __tablename__ = "recipes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    favorite: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RemovedStockEvent(Base):
    """Retain only event identity so redelivery cannot recreate a purged stock batch."""

    __tablename__ = "removed_stock_events"
    event_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    removed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
