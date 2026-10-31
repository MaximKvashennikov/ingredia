"""Recipe generation through the explicitly selected Groq model."""

import httpx
from pydantic import SecretStr

from ingredia.accounts.models import BatchView
from ingredia.adapters.chat_completions.models import RecipeInputMessage, SystemMessage
from ingredia.adapters.chat_completions.output import parse_model
from ingredia.adapters.groq.client import GroqClient
from ingredia.adapters.groq.constants import MODEL
from ingredia.adapters.groq.models import (
    GroqRequest,
    ObservationSchema,
    ResponseFormat,
    schema_structure,
)
from ingredia.recipes.models import RecipeSuggestions
from ingredia.recipes.prompting import recipe_prompt, stock_context


class GroqRecipeGenerator:
    """Use one bounded structured request, with no implicit fallback."""

    source = f"AI · Groq / {MODEL}"

    def __init__(self, client: httpx.AsyncClient, key: SecretStr) -> None:
        """Reuse the provider transport and lifecycle managed by the composition root."""
        self._api = GroqClient(client, key)

    async def suggest(self, stock: list[BatchView]) -> RecipeSuggestions:
        """Generate proposals; availability is subsequently checked by application code."""
        request = GroqRequest(
            messages=(
                SystemMessage(content=recipe_prompt(schema_in_response=True)),
                RecipeInputMessage(content=stock_context(stock)),
            ),
            response_format=ResponseFormat(
                json_schema=ObservationSchema(
                    name="recipe_suggestions",
                    schema=schema_structure(RecipeSuggestions.model_json_schema()),
                )
            ),
        )
        return parse_model(await self._api.complete(request), RecipeSuggestions)
