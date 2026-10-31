"""Validated purchase previews and explicit conversion to inventory commands."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from ingredia.accounts.expiry import ExpiryEstimate
from ingredia.accounts.models import BatchInput, StockUnit
from ingredia.recognition.models import PhotoRecognition, ProductObservation


class PurchaseContents(BaseModel):
    """Persist extraction and separately calculated estimates without mixing their evidence."""

    result: PhotoRecognition
    estimates: list[ExpiryEstimate | None] = Field(default_factory=list)


class PurchasePreview(PurchaseContents):
    """One durable confirmation token and its validated observations."""

    id: UUID


def to_stock(product: ProductObservation) -> BatchInput:
    """Preserve unknown values and multiply known package volumes exactly once."""
    if product.name is None or product.needs_clarification:
        raise ValueError("Unclear product cannot be saved")
    amount = product.quantity_per_package
    quantity = None
    unit = None
    if amount is not None:
        quantity = Decimal(str(amount.value)) * (product.package_count or 1)
        quantity = quantity.quantize(Decimal("0.001"))
        unit = StockUnit(amount.unit)
    elif product.package_count is not None:
        quantity = Decimal(product.package_count)
        unit = StockUnit.PIECE
    return BatchInput(
        name=product.name,
        quantity=quantity,
        unit=unit,
        expiry=product.expiry_date,
    )


def load_contents(payload: dict[str, object]) -> PurchaseContents:
    """Read old pending drafts without inventing new dates during confirmation."""
    if "result" in payload:
        return PurchaseContents.model_validate(payload)
    return PurchaseContents(result=PhotoRecognition.model_validate(payload))
