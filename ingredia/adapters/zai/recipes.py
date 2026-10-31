"""Recipe generation through the retained Z.ai free text model."""

import httpx
from pydantic import SecretStr

from ingredia.accounts.models import BatchView
from ingredia.adapters.chat_completions.models import RecipeInputMessage, SystemMessage
from ingredia.adapters.chat_completions.output import parse_model
from ingredia.adapters.zai.client import ZaiClient
from ingredia.adapters.zai.models import RecipeRequest
from ingredia.recipes.models import RecipeSuggestions
from ingredia.recipes.prompting import recipe_prompt, stock_context


class ZaiRecipeGenerator:
    """Keep GLM support behind the same recipe port without automatic fallback."""

    source = "AI · Z.ai / glm-4.7-flash"

    def __init__(self, client: httpx.AsyncClient, key: SecretStr) -> None:
        """Reuse the provider-specific client and externally owned HTTP resources."""
        self._api = ZaiClient(client, key)

    async def suggest(self, stock: list[BatchView]) -> RecipeSuggestions:
        """Return locally validated proposals with one free-model request."""
        request = RecipeRequest(
            messages=(
                SystemMessage(content=recipe_prompt()),
                RecipeInputMessage(content=stock_context(stock)),
            )
        )
        return parse_model(await self._api.complete(request), RecipeSuggestions)
