"""Conservative planning estimates kept separate from observed label dates."""

import json
import re
from datetime import date, timedelta
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingredia.recognition.models import ProductObservation


class ExpiryRule(BaseModel):
    """One reviewed rule with explicit product form, conditions and provenance."""

    id: str
    names: list[str]
    days: int = Field(ge=1, le=365)
    conditions: str
    source: str


class ExpiryEstimate(BaseModel):
    """A planning date calculated from a purchase-day assumption, never label evidence."""

    model_config = ConfigDict(extra="forbid")
    expiry: date
    reference_date: date
    days: int = Field(ge=1, le=365)
    rule_id: str
    conditions: str
    source: str

    @model_validator(mode="after")
    def consistent_date(self) -> "ExpiryEstimate":
        """Keep stored arithmetic and the displayed reference date consistent."""
        if self.expiry != self.reference_date + timedelta(days=self.days):
            raise ValueError("Inconsistent estimate date")
        return self


@lru_cache
def rules() -> list[ExpiryRule]:
    """Load the small reviewed catalogue; unmatched products keep an unknown date."""
    resource = files("ingredia.accounts").joinpath("data/expiry_v1.json")
    return [ExpiryRule.model_validate(item) for item in json.loads(resource.read_text("utf-8"))]


def estimate_expiry(product: ProductObservation, reference_date: date) -> ExpiryEstimate | None:
    """Suggest dates only for unambiguous plain products without an explicit expiry."""
    if product.expiry_date is not None or product.needs_clarification or product.name is None:
        return None
    normalized = re.sub(r"\s+", " ", product.name.casefold().replace("ё", "е")).strip()
    for rule in rules():
        if normalized in rule.names:
            return ExpiryEstimate(
                expiry=reference_date + timedelta(days=rule.days),
                reference_date=reference_date,
                days=rule.days,
                rule_id=rule.id,
                conditions=rule.conditions,
                source=rule.source,
            )
    return None
