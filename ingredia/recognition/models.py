"""Validated observations extracted from a photograph."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=300)]


class Observation(BaseModel):
    """A value explicitly visible on a label or countable in the photograph."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    value: float = Field(gt=0, le=1_000_000, allow_inf_nan=False)
    unit: Literal["g", "kg", "ml", "l", "pcs"]
    evidence: ShortText


class ProductObservation(BaseModel):
    """One visible product, with unknown attributes represented by null."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ShortText | None
    visual_description: ShortText
    brand: ShortText | None
    package_count: int | None = Field(ge=1, le=1000)
    quantity_per_package: Observation | None
    expiry_date: date | None
    expiry_evidence: ShortText | None
    needs_clarification: bool
    clarification_question: ShortText | None

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        """Reject unsupported dates and unclear products without a question."""
        if self.expiry_date is not None and self.expiry_evidence is None:
            raise ValueError("An expiry date needs visible label evidence")
        if self.name is None and not self.needs_clarification:
            raise ValueError("An unknown product needs clarification")
        if self.needs_clarification and self.clarification_question is None:
            raise ValueError("Clarification needs a specific question")
        if not self.needs_clarification and self.clarification_question is not None:
            raise ValueError("A question requires the clarification flag")
        return self


class PhotoRecognition(BaseModel):
    """Validated photo observations; these are candidates, not inventory changes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    products: list[ProductObservation] = Field(max_length=20)
    warnings: list[ShortText] = Field(max_length=10)
