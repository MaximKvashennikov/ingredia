"""Bounded recipe proposals and availability calculated by the application."""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingredia.accounts.models import StockUnit

Text = Annotated[str, Field(min_length=1, max_length=220)]


class Ingredient(BaseModel):
    """A required ingredient; even basic pantry items must be listed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, le=1000000, allow_inf_nan=False)
    unit: StockUnit


class RecipeProposal(BaseModel):
    """A generated recipe, independent of account state and transport."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)
    servings: int = Field(ge=1, le=8)
    minutes: int = Field(ge=1, le=240)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=10)
    steps: list[Text] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def unique_ingredients(self) -> "RecipeProposal":
        """Reject duplicate ingredients that would otherwise undercount required stock."""
        names = [
            " ".join(item.name.casefold().replace("ё", "е").split()) for item in self.ingredients
        ]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate ingredients")
        return self


class RecipeSuggestions(BaseModel):
    """At most three generated dishes from a single bounded request."""

    model_config = ConfigDict(extra="forbid")
    recipes: list[RecipeProposal] = Field(min_length=1, max_length=3)


class RecipeSnapshot(BaseModel):
    """Persisted content and honest attribution, without computed stock claims."""

    proposal: RecipeProposal
    source: str


class Availability(StrEnum):
    """Server-calculated availability rather than an LLM assertion."""

    AVAILABLE = "available"
    MISSING = "missing"
    CHECK = "check"


class IngredientView(BaseModel):
    """Show required quantity, uncertainty and current availability together."""

    ingredient: Ingredient
    status: Availability
    note: str
    confirmed_expiry: date | None = None


class RecipeView(BaseModel):
    """An authorized snapshot with freshly calculated ingredient state."""

    id: str
    snapshot: RecipeSnapshot
    favorite: bool
    ingredients: list[IngredientView]
