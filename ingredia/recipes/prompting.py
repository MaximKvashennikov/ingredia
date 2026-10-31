"""Load versioned recipe instructions outside provider and Telegram handlers."""

import json
from importlib.resources import files
from string import Template

from ingredia.accounts.models import BatchView
from ingredia.recipes.models import RecipeSuggestions


def recipe_prompt(schema_in_response: bool = False) -> str:
    """Build trusted recipe instructions with the validated response contract."""
    template = files("ingredia.recipes").joinpath("prompts/recipes_v1.txt").read_text("utf-8")
    schema = "Схема задана в response_format."
    if not schema_in_response:
        schema = json.dumps(RecipeSuggestions.model_json_schema(), ensure_ascii=False)
    return Template(template).substitute(schema=schema)


def stock_context(stock: list[BatchView]) -> str:
    """Send only necessary grocery attributes, with no account or Telegram identifiers."""
    return json.dumps(
        [
            row.model_dump(
                mode="json", include={"name", "quantity", "unit", "expiry", "expiry_source"}
            )
            for row in stock
        ],
        ensure_ascii=False,
    )
