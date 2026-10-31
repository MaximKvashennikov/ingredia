"""Z.ai routing and error policy for the shared bounded HTTP transport."""

import httpx
from pydantic import SecretStr

from ingredia.adapters.chat_completions.client import ChatCompletionClient
from ingredia.adapters.chat_completions.client import read_bounded as read_bounded
from ingredia.adapters.zai.constants import ENDPOINT
from ingredia.adapters.zai.errors import provider_failure


class ZaiClient(ChatCompletionClient):
    """Preserve the GLM route and business codes without coupling other adapters to Z.ai."""

    def __init__(self, client: httpx.AsyncClient, api_key: SecretStr) -> None:
        """Configure the existing provider endpoint with no fallback."""
        super().__init__(client, api_key, ENDPOINT, provider_failure)
